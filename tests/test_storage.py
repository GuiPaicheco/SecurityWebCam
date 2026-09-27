import os
from pathlib import Path
import time
import uuid
import pytest
from securitywebcam.storage import digest, Storage


def add(system, *, created=None, preserved=0, pending=False, root=None):
    c,db,s,*_=system
    root=root or s.destination()
    name=uuid.uuid4().hex+'.mp4'
    p=root/name
    p.write_bytes(b'fixture-only-no-real-recording'*100)
    ident=uuid.uuid4().hex
    db.execute('''INSERT INTO recordings(id,root,name,created,mode,size,sha256,duration,preserved,cloud_state)
                  VALUES(?,?,?,?,?,?,?,?,?,?)''',(ident,str(root),name,created or time.time(),'av',p.stat().st_size,digest(p),1,preserved,'pending' if pending else 'not_selected'))
    return db.rows('SELECT * FROM recordings WHERE id=?',(ident,))[0]


def test_copy_restart_integrity_dedup_and_retention(system):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'cloud')})
    row=add(system,created=time.time()-3*86400,pending=True)
    s.maintain()
    row=db.rows('SELECT * FROM recordings')[0]
    target=s.path(row,True)
    assert row['cloud_state']=='copied' and digest(target)==row['sha256']
    before=target.stat().st_mtime_ns
    db.execute("UPDATE recordings SET cloud_state='pending'")
    Storage(c,db).maintain()
    assert target.stat().st_mtime_ns==before
    c.save({'retention_days':1})
    s.maintain()
    assert not s.path(row).exists() and target.exists()
    assert db.rows('SELECT * FROM recordings')[0]['local_state']=='deleted'
    c.save({'cloud_retention_days':1})
    s.maintain()
    assert not target.exists()


def test_unavailable_cloud_retry_restart(system):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'offline')})
    row=add(system,pending=True)
    s.maintain()
    r=db.rows('SELECT * FROM recordings')[0]
    assert r['cloud_state']=='pending' and r['attempts']==1
    (c.home/'offline').mkdir()
    db.execute('UPDATE recordings SET retry_at=0')
    Storage(c,db).maintain()
    r=db.rows('SELECT * FROM recordings')[0]
    assert r['cloud_state']=='copied'
    assert digest(s.path(r,True))==row['sha256']


def test_retention_preserves_pending_marked_and_unowned(system):
    c,db,s,*_=system
    old=time.time()-5*86400
    marked=add(system,created=old,preserved=1)
    pending=add(system,created=old,pending=True)
    removable=add(system,created=old)
    foreign=s.destination()/'unowned.txt';foreign.write_text('never delete')
    c.save({'retention_days':1})
    s.maintain()
    assert s.path(marked).exists() and s.path(pending).exists()
    assert not s.path(removable).exists() and foreign.exists()


def test_size_limit_oldest_first(system):
    c,db,s,*_=system
    old=add(system,created=time.time()-20)
    new=add(system)
    c.save({'max_storage_gb':new['size']/1024**3+0.0000001})
    s.maintain()
    assert not s.path(old).exists() and s.path(new).exists()


def test_changed_file_not_deleted(system):
    c,db,s,*_=system
    row=add(system,created=time.time()-2*86400)
    s.path(row).write_text('changed by someone else')
    c.save({'retention_days':1})
    s.maintain()
    assert s.path(row).exists()


def test_fallback_migration(system,monkeypatch):
    c,db,s,*_=system
    c.save({'missing_destination':'fallback'})
    monkeypatch.setattr('securitywebcam.storage.resolve_volume',lambda *args:None)
    root=s.destination()
    assert root.parent==c.home/'fallback'
    row=add(system,root=root)
    monkeypatch.setattr('securitywebcam.storage.resolve_volume',lambda *args:c.home/'recordings')
    s.maintain()
    updated=db.rows('SELECT * FROM recordings')[0]
    assert s.path(updated).exists() and not (root/row['name']).exists()
    assert digest(s.path(updated))==row['sha256']


def test_copy_conflict_is_not_overwritten(system):
    c,db,s,*_=system
    source=c.home/'source';source.write_bytes(b'abc')
    target=c.home/'target';target.write_bytes(b'xyz')
    with pytest.raises(OSError):s.copy_verified(source,target,digest(source),3)
    assert target.read_bytes()==b'xyz'


def test_interrupted_copy_recovers_without_duplicate(system,monkeypatch):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'cloud')})
    add(system,pending=True)
    import shutil
    original=shutil.copyfileobj
    def fail(source,out,length):
        out.write(source.read(8))
        raise OSError('Falha de I/O simulada')
    monkeypatch.setattr('securitywebcam.storage.shutil.copyfileobj',fail)
    s.maintain()
    row=db.rows('SELECT * FROM recordings')[0]
    assert row['cloud_state']=='pending' and not s.path(row,True).exists()
    monkeypatch.setattr('securitywebcam.storage.shutil.copyfileobj',original)
    db.execute('UPDATE recordings SET retry_at=0')
    Storage(c,db).maintain()
    row=db.rows('SELECT * FROM recordings')[0]
    assert row['cloud_state']=='copied' and digest(s.path(row,True))==row['sha256']
    assert len(list(Path(row['cloud_root']).rglob('*.mp4')))==1


def test_cloud_retention_keeps_local(system):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'cloud'),'cloud_retention_days':1})
    add(system,pending=True,created=time.time()-3*86400)
    s.maintain()
    row=db.rows('SELECT * FROM recordings')[0]
    assert row['cloud_state']=='deleted' and row['local_state']=='local'
    assert s.path(row).exists()


def test_absent_destination_waits(system,monkeypatch):
    c,db,s,*_=system
    monkeypatch.setattr('securitywebcam.storage.resolve_volume',lambda *args:None)
    with pytest.raises(OSError,match='desconectado'):s.destination()


def test_full_cloud_disk_keeps_pending(system,monkeypatch):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'cloud')})
    add(system,pending=True)
    from collections import namedtuple
    Usage=namedtuple('Usage','total used free')
    monkeypatch.setattr('securitywebcam.storage.shutil.disk_usage',lambda path:Usage(100,100,0))
    s.maintain()
    row=db.rows('SELECT * FROM recordings')[0]
    assert row['cloud_state']=='pending' and s.path(row).exists()


def test_cloud_filters_and_preservation(system):
    c,db,s,*_=system
    c.save({'cloud_enabled':True,'cloud_folder':str(c.home/'cloud'),'cloud_preserved_only':True,'cloud_modes':['audio']})
    row=add(system)
    s.preserve(row['id'],True)
    assert db.rows('SELECT * FROM recordings')[0]['cloud_state']=='not_selected'
    c.save({'cloud_modes':['av']})
    s.preserve(row['id'],True)
    assert db.rows('SELECT * FROM recordings')[0]['cloud_state']=='pending'


def test_media_ranges_and_unknown_files(system,logged):
    row=add(system)
    client,headers=logged
    r=client.get('/api/recordings/'+row['id']+'/media',base_url='http://localhost:8765',headers={'Range':'bytes=0-9'})
    assert r.status_code==206 and len(r.data)==10
    r=client.get('/api/recordings/'+row['id']+'/media?download=1',base_url='http://localhost:8765')
    assert r.status_code==200 and 'attachment' in r.headers['Content-Disposition']
    assert client.get('/api/recordings/missing/media',base_url='http://localhost:8765').status_code==404
