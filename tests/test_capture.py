import os
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock
import pytest
from securitywebcam.capture import Recorder
from securitywebcam.platform import InstanceLock, volume_identity, resolve_volume


def test_duplicate_process_lock(tmp_path):
    first=InstanceLock(tmp_path)
    with pytest.raises(OSError):InstanceLock(tmp_path)
    first.file.close()
    second=InstanceLock(tmp_path)
    second.file.close()


def test_autostart_opt_in_reversible(system,monkeypatch):
    c=system[0];calls=[]
    monkeypatch.setattr('securitywebcam.config.autostart',lambda enabled:calls.append(enabled))
    assert c.snapshot()['autostart'] is False
    c.save({'autostart':True});c.save({'autostart':False})
    assert calls==[True,False]


def test_space_guard_does_not_launch(system,monkeypatch):
    c,db,s,r,*_=system
    c.save({'camera':'test-camera','microphone':'test-mic','min_free_gb':100000})
    popen=Mock();monkeypatch.setattr('securitywebcam.capture.subprocess.Popen',popen)
    with pytest.raises(OSError,match='Espaço'):r._spawn()
    popen.assert_not_called()


def test_modes_and_segment_command(system):
    c,db,s,r,*_=system
    data=c.snapshot();data.update(camera='USB Camera',microphone='Mic')
    for mode,source in [('audio','audio=Mic'),('video','video=USB Camera'),('av','video=USB Camera:audio=Mic')]:
        args=r._args(data,mode,Path('test_%06d.mp4.partial'),Path('list.csv'))
        assert args[args.index('-i')+1]==source
        assert args[args.index('-segment_time')+1]=='600'
        assert 'movflags=+frag_keyframe+empty_moov+default_base_moof' in args


@pytest.mark.skipif(os.name!='nt',reason='API de volume Windows')
def test_volume_guid_roundtrip(tmp_path):
    identity=volume_identity(tmp_path)
    assert identity['guid'].startswith('\\\\?\\Volume{')
    assert resolve_volume(identity,tmp_path).resolve()==tmp_path.resolve()


def test_stop_pause_resume_commands(system):
    r=system[3]
    with pytest.raises(ValueError):r.command('resume')
    r.command('start');assert r.wanted=='recording'
    r.command('pause');assert r.wanted=='paused'
    r.command('resume');assert r.wanted=='recording'
    r.command('stop');assert r.wanted=='stopped'
    with pytest.raises(ValueError):r.command('arbitrary-command')
