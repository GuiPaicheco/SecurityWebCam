import json
import os
from pathlib import Path
import re
import threading
from .platform import volume_identity, autostart

DEFAULTS = {
    'mode': 'av', 'camera': '', 'microphone': '', 'resolution': '640x480',
    'fps': 30, 'quality': 'balanced', 'segment_seconds': 600,
    'destination': '', 'missing_destination': 'wait', 'fallback': '',
    'device_failure': 'wait', 'autostart': False,
    'min_free_gb': 2.0, 'max_storage_gb': 0.0, 'retention_days': 0,
    'cloud_enabled': False, 'cloud_folder': '', 'cloud_modes': ['audio', 'video', 'av'],
    'cloud_hours': [], 'cloud_preserved_only': False, 'cloud_retention_days': 0,
    'remote_host': '', 'remote_enabled': False,
}


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class Config:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / 'config.json'
        self.lock = threading.RLock()
        self.data = dict(DEFAULTS)
        self.data.update(destination=str(self.home / 'recordings'), fallback=str(self.home / 'fallback'))
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding='utf-8')))
        else:
            atomic_json(self.path, self.data)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def export(self):
        return {k: v for k, v in self.snapshot().items() if k in DEFAULTS}

    def save(self, supplied):
        with self.lock:
            if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
                raise ValueError('Configuração contém campos desconhecidos')
            data = self.snapshot()
            data.update(supplied)
            for key in ['autostart', 'cloud_enabled', 'cloud_preserved_only', 'remote_enabled']:
                if type(data[key]) is not bool:
                    raise ValueError(f'{key}: informe verdadeiro ou falso')
            for key, low, high in [('fps', 1, 120), ('segment_seconds', 5, 3600),
                                   ('retention_days', 0, 36500), ('cloud_retention_days', 0, 36500)]:
                if type(data[key]) is not int or not low <= data[key] <= high:
                    raise ValueError(f'{key}: valor entre {low} e {high}')
            for key in ['min_free_gb', 'max_storage_gb']:
                if type(data[key]) not in (float, int) or not 0 <= data[key] <= 100000:
                    raise ValueError(f'{key}: limite inválido')
            for key, choices in [('mode', ['audio', 'video', 'av']),
                                 ('quality', ['economy', 'balanced', 'high']),
                                 ('device_failure', ['wait', 'available']),
                                 ('missing_destination', ['wait', 'fallback'])]:
                if data[key] not in choices:
                    raise ValueError(f'{key}: opção inválida')
            if not isinstance(data['resolution'], str) or not re.fullmatch(r'\d{2,4}x\d{2,4}', data['resolution']):
                raise ValueError('Resolução inválida')
            for key in ['camera', 'microphone']:
                if not isinstance(data[key], str) or len(data[key]) > 512 or any(c in data[key] for c in '\r\n\0'):
                    raise ValueError('Dispositivo inválido')
            if not isinstance(data['remote_host'], str) or (data['remote_host'] and not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', data['remote_host'])):
                raise ValueError('Use o nome DNS exato do computador na tailnet (*.ts.net)')
            if data['remote_enabled'] and not data['remote_host']:
                raise ValueError('Configure o nome DNS da tailnet')
            if not isinstance(data['cloud_modes'], list) or any(m not in ['audio', 'video', 'av'] for m in data['cloud_modes']):
                raise ValueError('Modos de cópia inválidos')
            if not isinstance(data['cloud_hours'], list) or any(type(h) is not int or not 0 <= h <= 23 for h in data['cloud_hours']):
                raise ValueError('Horários precisam ser horas inteiras de 0 a 23')
            for key in ['destination', 'fallback', 'cloud_folder']:
                if not isinstance(data[key], str) or len(data[key]) > 2000:
                    raise ValueError('Pasta inválida')
                if data[key] and (not Path(data[key]).is_absolute() or '..' in Path(data[key]).parts):
                    raise ValueError('Use um caminho absoluto, sem ..')
            if not data['destination'] or not data['fallback']:
                raise ValueError('Informe as pastas de gravação e contingência')
            if data['cloud_enabled'] and not data['cloud_folder']:
                raise ValueError('Informe a pasta sincronizada pelo cliente OneDrive')
            paths = [Path(data[k]).resolve() for k in ['destination', 'fallback', 'cloud_folder'] if data[k]]
            for i, p in enumerate(paths):
                if any(p == q or p in q.parents or q in p.parents for q in paths[i+1:]):
                    raise ValueError('As pastas de gravação, contingência e nuvem devem ser separadas')
            if data['destination'] != self.data['destination']:
                if not Path(data['destination']).is_dir():
                    raise ValueError('Crie ou selecione uma pasta de destino existente')
                data['volume'] = volume_identity(data['destination'])
            elif not data.get('volume') and Path(data['destination']).is_dir():
                data['volume'] = volume_identity(data['destination'])
            if data['autostart'] != self.data['autostart']:
                autostart(data['autostart'])
            atomic_json(self.path, data)
            self.data = data
            return self.export()
