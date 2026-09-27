import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, creationflags=NO_WINDOW)


def devices(ffmpeg='ffmpeg'):
    result = run([ffmpeg, '-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'])
    return [{'name': name, 'kind': kind} for name, kind in
            re.findall(r'"([^"\r\n]+)" \((video|audio)\)', result.stderr)]


def device_options(name, kind, ffmpeg='ffmpeg'):
    return run([ffmpeg, '-hide_banner', '-list_options', 'true', '-f', 'dshow',
                '-i', f'{kind}={name}']).stderr[-16000:]


def volume_identity(path):
    """GUID de volume Windows + caminho relativo; acompanha mudança de letra."""
    path = Path(path).absolute()
    if os.name != 'nt':
        return None
    root = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetVolumePathNameW(str(path), root, 1024):
        raise OSError('Pasta precisa existir para identificar o volume')
    guid = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(root.value, guid, 1024):
        raise OSError('Não foi possível obter o GUID do volume; selecione um disco local')
    return {'guid': guid.value, 'relative': os.path.relpath(path, root.value)}


def resolve_volume(identity, original):
    if not identity or os.name != 'nt':
        return Path(original)
    buf = ctypes.create_unicode_buffer(32768)
    length = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetVolumePathNamesForVolumeNameW(
        identity['guid'], buf, len(buf), ctypes.byref(length))
    if not ok or not buf.value:
        return None
    return Path(buf.value) / identity['relative']


def autostart(enabled):
    if os.name != 'nt':
        if enabled:
            raise OSError('Inicialização automática disponível somente no Windows')
        return
    import winreg
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    launcher = Path(__file__).resolve().parents[1] / 'launcher.pyw'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                         r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            winreg.SetValueEx(key, 'SecurityWebCam', 0, winreg.REG_SZ,
                             f'"{pythonw}" "{launcher}" --autostart')
        else:
            try:
                winreg.DeleteValue(key, 'SecurityWebCam')
            except FileNotFoundError:
                pass


class InstanceLock:
    def __init__(self, home):
        self.file = open(Path(home) / 'instance.lock', 'a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def protect_directory(home):
    if os.name == 'nt':
        import getpass
        result = run(['icacls', str(home), '/inheritance:r', '/grant:r',
                      f'{getpass.getuser()}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'])
        if result.returncode:
            raise OSError('Não foi possível restringir as permissões da pasta de dados')
    else:
        Path(home).chmod(0o700)
