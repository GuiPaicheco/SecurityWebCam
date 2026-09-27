import csv
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from .config import atomic_json
from .platform import NO_WINDOW, devices
from .storage import GB, safe_path


def attach_job(process):
    """Encerra o FFmpeg se o processo Python morrer (Windows Job Object)."""
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    class BASIC(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                    ('Flags', wintypes.DWORD), ('MinWorking', ctypes.c_size_t),
                    ('MaxWorking', ctypes.c_size_t), ('ActiveLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('Priority', wintypes.DWORD), ('Scheduling', wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(x, ctypes.c_ulonglong) for x in ['read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes']]
    class EXTENDED(ctypes.Structure):
        _fields_ = [('Basic', BASIC), ('IO', IO), ('ProcessMemory', ctypes.c_size_t),
                    ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        process.kill()
        if job:
            kernel.CloseHandle(job)
        raise OSError('Não foi possível vincular a captura ao processo principal')
    return (kernel, job)


class Recorder:
    def __init__(self, config, db, storage):
        self.config, self.db, self.storage = config, db, storage
        self.lock = threading.RLock()
        self.wanted = 'stopped'
        self.state = 'stopped'
        self.actual_mode = None
        self.error = ''
        self.process = None
        self.job = None
        self.session = None
        self.closed = threading.Event()
        self.work = queue.Queue()
        self.queued = set()
        self.worker = threading.Thread(target=self._files, daemon=True)
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.last_maintenance = 0
        self.last_progress = 0
        self.bytes_seen = -1
        self.retry_at = 0
        self.failures = 0
        self.degrade_next = None
        self.stderr_tail = []

    def start_workers(self):
        self.recover()
        self.worker.start()
        self.thread.start()

    def status(self):
        with self.lock:
            return dict(state=self.state, requested=self.wanted, actual_mode=self.actual_mode,
                        error=self.error, pid=self.process.pid if self.process else None)

    def command(self, command):
        with self.lock:
            if command not in ['start', 'pause', 'resume', 'stop']:
                raise ValueError('Comando inválido')
            if command == 'resume' and self.wanted != 'paused':
                raise ValueError('A captura não está pausada')
            if command == 'pause' and self.wanted != 'recording':
                raise ValueError('A captura não está ativa')
            self.wanted = {'start': 'recording', 'resume': 'recording', 'pause': 'paused', 'stop': 'stopped'}[command]
            self.retry_at = 0
            self.db.event('info', 'Comando explícito: ' + command)

    def _args(self, c, mode, pattern, manifest):
        args = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', '-thread_queue_size', '1024',
                '-f', 'dshow', '-rtbufsize', '128M']
        if mode != 'audio':
            args += ['-video_size', c['resolution'], '-framerate', str(c['fps'])]
        source = []
        if mode != 'audio':
            source.append('video=' + c['camera'])
        if mode != 'video':
            source.append('audio=' + c['microphone'])
        args += ['-i', ':'.join(source)]
        if mode != 'audio':
            rate = {'economy': '800k', 'balanced': '2000k', 'high': '5000k'}[c['quality']]
            args += ['-map', '0:v:0', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
                     '-bf', '0', '-b:v', rate, '-maxrate', rate, '-bufsize', '10M', '-g', str(c['fps'] * 2),
                     '-force_key_frames', f"expr:gte(t,n_forced*{c['segment_seconds']})"]
        if mode != 'video':
            args += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '128k', '-af', 'aresample=async=1:first_pts=0']
        args += ['-max_muxing_queue_size', '1024', '-f', 'segment', '-segment_time', str(c['segment_seconds']),
                 '-reset_timestamps', '1', '-segment_format', 'mp4', '-segment_format_options',
                 'movflags=+frag_keyframe+empty_moov+default_base_moof',
                 '-segment_list', str(manifest), '-segment_list_type', 'csv', str(pattern)]
        return args

    def _spawn(self):
        c = self.config.snapshot()
        root = self.storage.destination()
        space = self.storage.space()
        # Reserva para captura e arquivo de finalização, além do mínimo configurado.
        reserve = 2 * space['estimated_daily'] / 86400 * c['segment_seconds'] + 32 * 1024 ** 2
        with self.storage.lock:
            self.storage.retain(c, reserve=reserve)
        space = self.storage.space()
        if space['free'] < c['min_free_gb'] * GB + reserve:
            raise OSError('Espaço livre insuficiente; capture aguarda liberação segura')
        if c['max_storage_gb'] and space['local_bytes'] + reserve > c['max_storage_gb'] * GB:
            raise OSError('Limite de armazenamento atingido; aguardando retenção ou ajuste')
        mode = c['mode']
        if not c['camera'] and mode != 'audio' or not c['microphone'] and mode != 'video':
            raise ValueError('Selecione os dispositivos na configuração')
        if mode == 'av' and c['device_failure'] == 'available':
            found = devices()
            camera = any(x['name'] == c['camera'] and x['kind'] == 'video' for x in found)
            mic = any(x['name'] == c['microphone'] and x['kind'] == 'audio' for x in found)
            if camera and not mic:
                mode = 'video'
            elif mic and not camera:
                mode = 'audio'
            elif self.degrade_next:
                mode = self.degrade_next
            self.degrade_next = None
        ident = uuid.uuid4().hex
        stamp = datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%z')
        prefix = f'{stamp}_{mode}_{ident}'
        session = dict(root=str(root), prefix=prefix, created=time.time(), mode=mode,
                       manifest=prefix + '.csv', sidecar=prefix + '.session.json', collected=[])
        atomic_json(root / session['sidecar'], session)
        self.stderr_tail = []
        p = subprocess.Popen(self._args(c, mode, root / (prefix + '_%06d.mp4.partial'), root / session['manifest']),
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             creationflags=NO_WINDOW)
        self.job = attach_job(p)
        self.process, self.session, self.actual_mode = p, session, mode
        self.state, self.error = 'starting', ''
        self.last_progress, self.bytes_seen = time.monotonic(), -1
        self.spawned = time.monotonic()
        self.stderr_thread = threading.Thread(target=self._stderr, args=(p,), daemon=True)
        self.stderr_thread.start()
        self.db.event('info', 'Captura iniciada no modo ' + mode)

    def _stderr(self, p):
        try:
            for line in iter(p.stderr.readline, b''):
                text = line.decode('utf-8', errors='replace').strip()
                if text:
                    self.stderr_tail.append(text[:500])
                    self.stderr_tail = self.stderr_tail[-12:]
        except (OSError, ValueError):
            pass

    def collect(self, session, recover=False):
        root = Path(session['root'])
        manifest = root / session['manifest']
        if manifest.exists():
            with open(manifest, encoding='utf-8') as f:
                entries = list(csv.reader(f))
            for row in entries:
                if len(row) != 3 or row[0] in session['collected']:
                    continue
                try:
                    offset = float(row[1])
                except ValueError:
                    continue
                path = safe_path(root, Path(row[0]).name)
                if not path.exists():
                    continue
                created = session['created'] + offset
                name = datetime.fromtimestamp(created).astimezone().strftime('%Y%m%dT%H%M%S%z') + '_' + session['mode'] + '_' + path.name.split('_')[-2] + '_' + path.name.split('_')[-1]
                renamed = root / name
                if path != renamed:
                    os.replace(path, renamed)
                self._enqueue(root, renamed, created, session['mode'], recover)
                session['collected'].append(row[0])
            atomic_json(root / session['sidecar'], session)

    def recover(self):
        c = self.config.snapshot()
        roots = {r['root'] for r in self.db.rows('SELECT DISTINCT root FROM recordings')}
        for parent in [c['destination'], c['fallback']]:
            if Path(parent).is_dir():
                roots.add(str(self.storage.managed(parent)))
        for root in roots:
            try:
                self.storage.validate_root(root)
                known = {r['name'] for r in self.db.rows('SELECT name FROM recordings WHERE root=?', (root,))}
                for p in [*Path(root).glob('*.mp4.partial'), *Path(root).glob('*.mp4')]:
                    if p.name in known:
                        continue
                    parts = p.name.split('_')
                    if len(parts) != 4 or parts[1] not in ['audio', 'video', 'av']:
                        continue
                    try:
                        created = datetime.strptime(parts[0], '%Y%m%dT%H%M%S%z').timestamp()
                    except ValueError:
                        continue
                    self._enqueue(Path(root), p, created, parts[1], True)
            except (ValueError, OSError) as e:
                self.db.event('warning', 'Recuperação pendente: ' + str(e))

    def _stop(self):
        p = self.process
        if p:
            if p.poll() is None:
                try:
                    p.stdin.write(b'q\n')
                    p.stdin.flush()
                    p.wait(timeout=12)
                except (OSError, subprocess.TimeoutExpired):
                    p.kill()
                    p.wait(timeout=5)
                    self.db.event('warning', 'Captura encerrou sem finalizar o último fragmento')
            # O executável no PATH pode ser um shim que mantém descendentes vivos.
            # Fechar o Job antes dos pipes elimina os descendentes e libera os arquivos.
            if self.job:
                self.job[0].CloseHandle(self.job[1])
                self.job = None
            self.stderr_thread.join(timeout=3)
            try:
                self.collect(self.session)
                # Último fragmento de uma captura abortada: validar antes de publicar.
                root = Path(self.session['root'])
                for path in root.glob(self.session['prefix'] + '_*.partial'):
                    self._enqueue(root, path, path.stat().st_mtime, self.actual_mode, True)
                (root / self.session['manifest']).unlink(missing_ok=True)
                (root / self.session['sidecar']).unlink(missing_ok=True)
            except (OSError, ValueError) as e:
                self.db.event('warning', 'Finalização pendente: ' + str(e))
            for f in [p.stdin, p.stderr]:
                if f:
                    f.close()
            self.process = None

    def _loop(self):
        while not self.closed.wait(0.5):
            try:
                with self.lock:
                    if self.wanted != 'recording':
                        self._stop()
                        self.state = self.wanted
                        continue
                    if self.process is None:
                        if time.monotonic() >= self.retry_at:
                            self._spawn()
                        continue
                    if self.process.poll() is not None:
                        mode = self.actual_mode
                        self._stop()
                        if self.config.snapshot()['device_failure'] == 'available':
                            self.degrade_next = 'audio' if mode in ['av', 'video'] else 'video'
                        raise OSError('Dispositivo indisponível ou formato não suportado. ' + ' '.join(self.stderr_tail)[-900:])
                    self.collect(self.session)
                    active = list(Path(self.session['root']).glob(self.session['prefix'] + '_*.partial'))
                    size = sum(p.stat().st_size for p in active)
                    if size != self.bytes_seen and size > 0:
                        self.last_progress, self.bytes_seen = time.monotonic(), size
                        self.state = 'recording'
                        self.failures = 0
                    if time.monotonic() - self.last_progress > 30:
                        if self.config.snapshot()['device_failure'] == 'available':
                            self.degrade_next = 'audio' if self.actual_mode in ['av', 'video'] else 'video'
                        self._stop()
                        raise OSError('Captura sem progresso por 30 segundos; tentando reconectar')
                    c = self.config.snapshot()
                    space = self.storage.space()
                    if space['destination'] and Path(space['destination']) != Path(self.session['root']):
                        self._stop()
                        raise OSError('Destino mudou; reiniciando captura na pasta disponível')
                    if space['free'] is None or space['free'] < c['min_free_gb'] * GB + 16 * 1024 ** 2:
                        self._stop()
                        raise OSError('Destino ausente ou espaço mínimo atingido')
                    if c['max_storage_gb'] and space['local_bytes'] + size > c['max_storage_gb'] * GB:
                        self._stop()
                        raise OSError('Limite de armazenamento atingido')
                    if self.actual_mode != c['mode'] and time.monotonic() - self.spawned > 60:
                        self._stop()  # tenta recuperar ambos os dispositivos
            except Exception as e:
                self.error, self.state = str(e), 'waiting'
                self.failures += 1
                self.retry_at = time.monotonic() + min(60, 2 ** min(self.failures, 6))
                self.db.event('error', self.error)
        with self.lock:
            self._stop()

    def _enqueue(self, root, path, created, mode, recover):
        key = str(path)
        if key not in self.queued:
            self.queued.add(key)
            self.work.put((root, path, created, mode, recover))

    def _files(self):
        while not self.closed.is_set() or self.thread.is_alive() or not self.work.empty():
            try:
                item = self.work.get(timeout=1)
            except queue.Empty:
                item = None
            if item:
                try:
                    self.storage.publish(*item)
                except Exception as e:
                    self.db.event('error', 'Finalização: ' + str(e))
                finally:
                    self.work.task_done()
                    self.queued.discard(str(item[1]))
            if time.monotonic() - self.last_maintenance > 10:
                try:
                    self.storage.maintain()
                except Exception as e:
                    self.db.event('warning', 'Armazenamento: ' + str(e))
                self.last_maintenance = time.monotonic()

    def shutdown(self):
        self.closed.set()
        if self.thread.is_alive():
            self.thread.join(timeout=20)
        if self.worker.is_alive():
            self.worker.join(timeout=90)
