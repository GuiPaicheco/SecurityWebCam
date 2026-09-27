import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from .config import atomic_json


class Auth:
    def __init__(self, home):
        self.path = Path(home) / 'auth.json'
        self.sessions = {}
        self.failures = []
        self.lock = threading.RLock()

    def set_password(self, password):
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError('Use uma senha entre 12 e 256 caracteres')
        salt = secrets.token_hex(32)
        encoded = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
        with self.lock:
            atomic_json(self.path, dict(salt=salt, hash=encoded))
            self.sessions.clear()

    def login(self, password):
        with self.lock:
            now = time.time()
            self.failures = [t for t in self.failures if now - t < 300]
            if len(self.failures) >= 8:
                raise ValueError('Muitas tentativas; aguarde cinco minutos')
            self.failures.append(now)
            if not self.path.exists() or not isinstance(password, str) or len(password) > 256:
                raise ValueError('Senha inválida')
            stored = json.loads(self.path.read_text())
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(stored['salt']), 600000).hex()
            if not hmac.compare_digest(actual, stored['hash']):
                raise ValueError('Senha inválida')
            self.failures.clear()
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions = {k: v for k, v in self.sessions.items() if v['expires'] > now}
            if len(self.sessions) >= 32:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[token] = dict(csrf=csrf, expires=now + 12 * 3600)
            return token

    def session(self, token):
        with self.lock:
            value = self.sessions.get(token)
            return value if value and value['expires'] > time.time() else None
