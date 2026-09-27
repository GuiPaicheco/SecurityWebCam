import pytest
from securitywebcam.storage import safe_path


@pytest.mark.parametrize('route', ['/api/status', '/api/config', '/api/recordings', '/api/export', '/api/recordings/fake/media', '/api/devices'])
def test_private_routes(client, route):
    assert client.get(route, base_url='http://localhost:8765').status_code == 401


def test_login_csrf_logout(logged):
    client, headers = logged
    assert client.get('/api/status', base_url='http://localhost:8765').status_code == 200
    assert client.post('/api/control', base_url='http://localhost:8765', json={'command':'start'}, headers={'Origin':'http://localhost:8765'}).status_code == 403
    assert client.post('/api/control', base_url='http://localhost:8765', json={'command':'start'}, headers={**headers,'Origin':'https://evil.invalid'}).status_code == 403
    assert client.post('/api/control', base_url='http://localhost:8765', json={'command':'start'}, headers=headers).status_code == 200
    assert client.post('/api/logout', base_url='http://localhost:8765', json={}, headers=headers).status_code == 200
    assert client.get('/api/status', base_url='http://localhost:8765').status_code == 401


def test_host_and_headers(client):
    assert client.get('/', base_url='http://evil.invalid').status_code == 403
    r=client.get('/', base_url='http://localhost:8765')
    assert r.headers['X-Frame-Options']=='DENY'
    assert "script-src 'self'" in r.headers['Content-Security-Policy']


def test_rate_limit_and_password(system):
    auth=system[4]
    for _ in range(8):
        with pytest.raises(ValueError):auth.login('wrong')
    with pytest.raises(ValueError,match='tentativas'):auth.login('test-only-password-123')
    auth.failures=[]
    token=auth.login('test-only-password-123')
    auth.set_password('another-long-password')
    assert auth.session(token) is None
    assert 'another-long-password' not in auth.path.read_text()


@pytest.mark.parametrize('path',['../outside.mp4','/outside','C:\\outside.mp4','file:stream','nested/../../outside'])
def test_path_escape(tmp_path,path):
    with pytest.raises(ValueError):safe_path(tmp_path,path)


def test_export_and_validation(system,logged):
    c=system[0]
    client,headers=logged
    exported=client.get('/api/export',base_url='http://localhost:8765').json
    assert 'hash' not in exported and 'salt' not in exported and 'volume' not in exported
    with pytest.raises(ValueError):c.save({'unknown':'secret'})
    with pytest.raises(ValueError):c.save({'segment_seconds':0})
    with pytest.raises(ValueError):c.save({'destination':str(c.home/'fallback')})
    assert client.get('/api/recordings/../../auth.json/media',base_url='http://localhost:8765').status_code==404


def test_remote_secure_cookie(system,client):
    c=system[0]
    c.save({'remote_host':'pc.example.ts.net','remote_enabled':True})
    assert client.get('/',base_url='https://pc.example.ts.net').status_code==403
    r=client.post('/api/login',base_url='https://pc.example.ts.net',json={'password':'test-only-password-123'},headers={'Origin':'https://pc.example.ts.net','X-Forwarded-Proto':'https'})
    assert r.status_code==200
    assert 'Secure;' in r.headers['Set-Cookie'] and 'HttpOnly;' in r.headers['Set-Cookie']
    assert 'SameSite=Strict' in r.headers['Set-Cookie']
