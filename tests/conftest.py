import pytest
from securitywebcam.auth import Auth
from securitywebcam.config import Config
from securitywebcam.database import Database
from securitywebcam.storage import Storage
from securitywebcam.capture import Recorder
from securitywebcam.web import create_app


@pytest.fixture
def system(tmp_path):
    c = Config(tmp_path / 'app')
    for name in ['recordings', 'fallback', 'cloud']:
        (tmp_path / 'app' / name).mkdir()
    db = Database(c.home / 'catalog.sqlite3')
    s = Storage(c, db)
    r = Recorder(c, db, s)
    a = Auth(c.home)
    a.set_password('test-only-password-123')
    app = create_app(c, db, s, r, a)
    app.config['TESTING'] = True
    return c, db, s, r, a, app


@pytest.fixture
def client(system):
    return system[-1].test_client()


@pytest.fixture
def logged(client):
    response = client.post('/api/login', base_url='http://localhost:8765',
                           json={'password': 'test-only-password-123'}, headers={'Origin':'http://localhost:8765'})
    return client, {'Origin':'http://localhost:8765', 'X-CSRF-Token':response.json['csrf']}
