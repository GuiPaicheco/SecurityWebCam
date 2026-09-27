from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid
from .config import atomic_json
from .platform import resolve_volume, run

GB = 1024 ** 3


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_path(root, relative):
    base = Path(root).resolve(strict=True)
    part = Path(relative)
    if part.is_absolute() or '..' in part.parts or ':' in str(part):
        raise ValueError('Caminho fora da pasta administrada')
    target = base / part
    resolved = target.resolve()
    if base not in resolved.parents or resolved == base:
        raise ValueError('Caminho fora da pasta administrada')
    # Recusa links/reparse points em toda a cadeia abaixo da raiz.
    for parent in [target, *target.parents]:
        if parent == base:
            break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Links não são permitidos')
    return target


class Storage:
    def __init__(self, config, db):
        self.config, self.db = config, db
        self.lock = threading.RLock()
        rows = db.rows("SELECT value FROM metadata WHERE key='installation'")
        self.installation = rows[0]['value'] if rows else uuid.uuid4().hex
        db.execute("INSERT OR IGNORE INTO metadata VALUES('installation',?)", (self.installation,))

    def managed(self, parent, create=True):
        parent = Path(parent)
        if not parent.is_dir():
            raise OSError('Destino ausente: conecte a unidade ou escolha uma pasta existente')
        root = parent / ('SecurityWebCam-' + self.installation)
        if create:
            root.mkdir(exist_ok=True)
        marker = root / '.securitywebcam.json'
        if not marker.exists() and create:
            # Não assume propriedade sobre uma pasta preexistente com dados.
            if any(root.iterdir()):
                raise OSError('Pasta sem identificação contém arquivos')
            atomic_json(marker, {'installation': self.installation})
        self.validate_root(root)
        return root

    def validate_root(self, root):
        root = Path(root)
        if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
            raise ValueError('A raiz administrada não pode ser um link')
        if json.loads((root / '.securitywebcam.json').read_text())['installation'] != self.installation:
            raise ValueError('Pasta não pertence a esta instalação')
        return root

    def destination(self):
        c = self.config.snapshot()
        dest = resolve_volume(c.get('volume'), c['destination'])
        if dest is not None and dest.is_dir():
            return self.managed(dest)
        if c['missing_destination'] == 'fallback':
            return self.managed(c['fallback'])
        raise OSError('Destino desconectado; aguardando reconexão')

    def path(self, row, cloud=False):
        root = row['cloud_root'] if cloud else row['root']
        name = row['cloud_name'] if cloud else row['name']
        self.validate_root(root)
        return safe_path(root, name)

    def probe(self, path):
        p = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], 60)
        if p.returncode:
            raise ValueError('Segmento inválido ou incompleto')
        info = json.loads(p.stdout)
        duration = float(info['format'].get('duration', 0))
        if duration <= 0 or not info.get('streams'):
            raise ValueError('Segmento sem mídia reproduzível')
        return duration

    def publish(self, root, partial, created, mode, recovery=False):
        with self.lock:
            self.validate_root(root)
            partial = safe_path(root, Path(partial).name)
            duration = self.probe(partial)
            final = partial.with_suffix('') if partial.suffix == '.partial' else partial
            staged = partial.with_suffix('.finalizing')
            info = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(partial)], 60).stdout)
            ends = [float(x.get('start_time', 0)) + float(x['duration']) for x in info['streams'] if 'duration' in x]
            # Remove a cauda sem áudio/vídeo comum ao parar e converte fragmentos em
            # MP4 convencional com índice no início, sem recodificar ou usar RAM proporcional.
            args = ['ffmpeg', '-v', 'error', '-y', '-i', str(partial), '-map', '0', '-c', 'copy']
            if mode == 'av' and len(ends) >= 2:
                args += ['-t', str(min(ends))]
            args += ['-movflags', '+faststart', '-f', 'mp4', str(staged)]
            remux = run(args, max(90, duration * 2))
            if remux.returncode:
                raise ValueError('Falha ao finalizar o contêiner MP4')
            duration = self.probe(staged)
            # Verificação completa em fluxo, sem guardar o segmento na memória.
            result = run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(staged), '-f', 'null', '-'],
                         max(90, duration * 2))
            if result.returncode:
                raise ValueError('Falha ao decodificar segmento; arquivo preservado para diagnóstico')
            sha, size = digest(staged), staged.stat().st_size
            os.replace(staged, final)
            if partial != final:
                partial.unlink(missing_ok=True)
            c = self.config.snapshot()
            selected = c['cloud_enabled'] and mode in c['cloud_modes'] and not c['cloud_preserved_only']
            selected = selected and (not c['cloud_hours'] or datetime.fromtimestamp(created).hour in c['cloud_hours'])
            self.db.execute('''INSERT OR IGNORE INTO recordings
                (id,root,name,created,mode,size,sha256,duration,cloud_state)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (uuid.uuid4().hex, str(root), final.name, created, mode, size, sha, duration,
                 'pending' if selected else 'not_selected'))
            if recovery:
                self.db.event('warning', 'Segmento recuperado após interrupção: ' + final.name)

    def copy_verified(self, source, target, sha, size):
        if target.exists():
            if target.stat().st_size == size and digest(target) == sha:
                return
            raise OSError('Conflito: destino existente com conteúdo diferente; preservado')
        target.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(target.parent).free < size + 16 * 1024 ** 2:
            raise OSError('Espaço insuficiente para a cópia')
        temp = target.with_suffix(target.suffix + '.copying')
        with open(source, 'rb') as src, open(temp, 'wb') as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if temp.stat().st_size != size or digest(temp) != sha:
            raise OSError('Integridade da cópia divergente')
        os.replace(temp, target)

    def maintain(self):
        with self.lock:
            c = self.config.snapshot()
            dest = resolve_volume(c.get('volume'), c['destination'])
            if dest and dest.is_dir():
                target_root = self.managed(dest)
                # Reassocia caminhos após mudança da letra do volume.
                for row in self.db.rows("SELECT * FROM recordings WHERE local_state='local'"):
                    if not Path(row['root']).is_dir() and safe_path(target_root, row['name']).is_file():
                        p = safe_path(target_root, row['name'])
                        if p.stat().st_size == row['size'] and digest(p) == row['sha256']:
                            self.db.execute('UPDATE recordings SET root=? WHERE id=?', (str(target_root), row['id']))
                fallback_root = str(Path(c['fallback']) / ('SecurityWebCam-' + self.installation))
                for row in self.db.rows("SELECT * FROM recordings WHERE root=? AND local_state='local'", (fallback_root,)):
                    try:
                        src = self.path(row)
                        target = safe_path(target_root, row['name'])
                        self.copy_verified(src, target, row['sha256'], row['size'])
                        self.db.execute('UPDATE recordings SET root=? WHERE id=?', (str(target_root), row['id']))
                        src.unlink()
                    except (OSError, ValueError) as e:
                        self.db.event('warning', 'Migração pendente: ' + str(e))
                        break
            if c['cloud_enabled']:
                self.copy_cloud(c)
            self.retain(c)

    def copy_cloud(self, c):
        rows = self.db.rows("SELECT * FROM recordings WHERE cloud_state='pending' AND retry_at<=? ORDER BY created LIMIT 10", (time.time(),))
        for row in rows:
            try:
                root = self.managed(c['cloud_folder'])
                name = datetime.fromtimestamp(row['created']).strftime('%Y/%m/%d/') + row['name']
                # Persistir o destino escolhido antes de copiar permite recuperação idempotente.
                if row['cloud_root']:
                    root, name = Path(row['cloud_root']), row['cloud_name']
                    self.validate_root(root)
                else:
                    self.db.execute('UPDATE recordings SET cloud_root=?,cloud_name=? WHERE id=?', (str(root), name, row['id']))
                target = safe_path(root, name)
                self.copy_verified(self.path(row), target, row['sha256'], row['size'])
                self.db.execute("UPDATE recordings SET cloud_state='copied',cloud_error='' WHERE id=?", (row['id'],))
            except (OSError, ValueError) as e:
                attempts = row['attempts'] + 1
                self.db.execute('UPDATE recordings SET attempts=?,retry_at=?,cloud_error=? WHERE id=?',
                                (attempts, time.time() + min(3600, 2 ** min(attempts, 11)), str(e)[:300], row['id']))

    def preserve(self, ident, enabled):
        c = self.config.snapshot()
        self.db.execute('UPDATE recordings SET preserved=? WHERE id=?', (int(enabled), ident))
        if enabled and c['cloud_enabled']:
            row = self.db.rows('SELECT * FROM recordings WHERE id=?', (ident,))
            if row and row[0]['mode'] in c['cloud_modes'] and (not c['cloud_hours'] or datetime.fromtimestamp(row[0]['created']).hour in c['cloud_hours']):
                self.db.execute("UPDATE recordings SET cloud_state='pending' WHERE id=? AND cloud_state='not_selected' AND local_state='local'", (ident,))

    def retain(self, c, reserve=0):
        rows = self.db.rows("SELECT * FROM recordings WHERE local_state='local' ORDER BY created")
        total = sum(r['size'] for r in rows)
        for row in rows:
            # Nunca sacrificar um segmento preservado ou ainda aguardando cópia.
            if row['preserved'] or row['cloud_state'] == 'pending':
                continue
            expired = c['retention_days'] > 0 and row['created'] < time.time() - c['retention_days'] * 86400
            over = c['max_storage_gb'] > 0 and total + reserve > c['max_storage_gb'] * GB
            if not (expired or over):
                continue
            try:
                path = self.path(row)
                if path.exists() and (path.stat().st_size != row['size'] or digest(path) != row['sha256']):
                    raise ValueError('Arquivo modificado; exclusão recusada')
                path.unlink(missing_ok=True)
                self.db.execute("UPDATE recordings SET local_state='deleted' WHERE id=?", (row['id'],))
                total -= row['size']
            except (OSError, ValueError):
                continue
        if c['cloud_retention_days'] > 0:
            for row in self.db.rows("SELECT * FROM recordings WHERE cloud_state='copied' AND preserved=0 AND created<?", (time.time() - c['cloud_retention_days'] * 86400,)):
                try:
                    path = self.path(row, cloud=True)
                    if path.exists() and digest(path) != row['sha256']:
                        continue
                    path.unlink(missing_ok=True)
                    self.db.execute("UPDATE recordings SET cloud_state='deleted' WHERE id=?", (row['id'],))
                except (OSError, ValueError):
                    continue

    def space(self):
        c = self.config.snapshot()
        bitrate = {'economy': 800000, 'balanced': 2000000, 'high': 5000000}[c['quality']]
        bitrate = (0 if c['mode'] == 'audio' else bitrate) + (0 if c['mode'] == 'video' else 128000)
        daily = bitrate * 86400 / 8
        try:
            root = self.destination()
            free = shutil.disk_usage(root).free
            destination = str(root)
        except (OSError, ValueError):
            free, destination = None, None
        total = self.db.rows("SELECT COALESCE(SUM(size),0) AS n FROM recordings WHERE local_state='local'")[0]['n']
        pending = self.db.rows("SELECT COALESCE(SUM(size),0) AS n FROM recordings WHERE cloud_state='pending'")[0]['n']
        try:
            cloud_free = shutil.disk_usage(c['cloud_folder']).free if c['cloud_folder'] else None
        except OSError:
            cloud_free = None
        return dict(free=free, destination=destination, local_bytes=total, estimated_daily=daily,
                    estimated_monthly=daily * 30, pending_bytes=pending, cloud_disk_free=cloud_free,
                    cloud_quota='Desconhecida: consulte a cota no aplicativo OneDrive',
                    cloud_capacity_insufficient=cloud_free is not None and pending > cloud_free)
