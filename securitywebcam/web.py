from datetime import datetime
import hmac
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from flask import Flask, request, jsonify, send_file, render_template, abort
from .platform import devices, device_options, run


def create_app(config, db, storage, recorder, auth):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024

    def remote():
        return request.host == config.snapshot()['remote_host'] and config.snapshot()['remote_enabled']

    @app.before_request
    def protect():
        c = config.snapshot()
        allowed = {'127.0.0.1:8765', 'localhost:8765'}
        if c['remote_enabled']:
            allowed.add(c['remote_host'])
        if request.host not in allowed:
            abort(403)
        # Host permitido também evita DNS rebinding; cabeçalhos proxy não concedem autenticação.
        if remote() and request.headers.get('X-Forwarded-Proto') != 'https':
            abort(403)
        if request.method not in ['GET', 'HEAD', 'OPTIONS']:
            expected = ('https://' if remote() else 'http://') + request.host
            if request.headers.get('Origin') != expected:
                abort(403)
            if not request.is_json:
                abort(415)
            if not isinstance(request.get_json(silent=True), dict):
                abort(400)
        if request.path in ['/', '/api/login'] or request.path.startswith('/static/'):
            return
        session = auth.session(request.cookies.get('swc_session'))
        if not session:
            abort(401)
        if request.method not in ['GET', 'HEAD', 'OPTIONS'] and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
            abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if remote():
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(ValueError)
    def invalid(e):
        return jsonify(error=str(e)), 400

    @app.errorhandler(OSError)
    def io_error(e):
        db.event('error', str(e))
        return jsonify(error='Operação indisponível. Consulte os erros recentes.'), 409

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.post('/api/login')
    def login():
        token = auth.login(request.json.get('password'))
        response = jsonify(csrf=auth.session(token)['csrf'])
        response.set_cookie('swc_session', token, httponly=True, secure=remote(), samesite='Strict', max_age=43200, path='/')
        return response

    @app.get('/api/session')
    def session():
        return jsonify(csrf=auth.session(request.cookies.get('swc_session'))['csrf'])

    @app.post('/api/logout')
    def logout():
        with auth.lock:
            auth.sessions.pop(request.cookies.get('swc_session'), None)
        response = jsonify(ok=True)
        response.delete_cookie('swc_session')
        return response

    @app.post('/api/password')
    def password():
        auth.set_password(request.json.get('password'))
        return jsonify(ok=True)

    @app.get('/api/status')
    def status():
        return jsonify(capture=recorder.status(), space=storage.space(),
                       cloud_upload_verified=False, direct_access_requires_pc=True,
                       events=db.rows('SELECT * FROM events ORDER BY id DESC LIMIT 30'))

    @app.post('/api/control')
    def control():
        recorder.command(request.json.get('command'))
        return jsonify(recorder.status())

    @app.route('/api/config', methods=['GET', 'POST'])
    def configuration():
        if request.method == 'POST':
            if recorder.status()['requested'] == 'recording' or recorder.status()['pid']:
                raise ValueError('Pare a gravação antes de alterar ou importar configurações')
            return jsonify(config.save(request.json))
        return jsonify(config.export())

    @app.get('/api/export')
    def export():
        response = jsonify(config.export())
        response.headers['Content-Disposition'] = 'attachment; filename=securitywebcam-config.json'
        return response

    @app.get('/api/devices')
    def list_devices():
        return jsonify(devices=devices())

    @app.get('/api/device-options')
    def options():
        name, kind = request.args.get('name'), request.args.get('kind')
        if not any(d['name'] == name and d['kind'] == kind for d in devices()):
            raise ValueError('Selecione um dispositivo disponível')
        return jsonify(options=device_options(name, kind))

    @app.post('/api/folder')
    def folder():
        if remote():
            abort(403)
        # Apenas uma escolha explícita do proprietário local abre o seletor nativo.
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        try:
            selected = filedialog.askdirectory(title='SecurityWebCam — selecione a pasta', parent=root)
        finally:
            root.destroy()
        return jsonify(path=selected)

    @app.get('/api/recordings')
    def recordings():
        conditions, args = [], []
        for key, op in [('from', '>='), ('to', '<')]:
            value = request.args.get(key)
            if value:
                try:
                    stamp = datetime.fromisoformat(value).timestamp()
                except ValueError:
                    raise ValueError('Data inválida')
                conditions.append('created' + op + '?')
                args.append(stamp)
        if request.args.get('mode'):
            conditions.append('mode=?')
            args.append(request.args['mode'])
        try:
            offset = max(0, int(request.args.get('offset', 0)))
        except ValueError:
            raise ValueError('Página inválida')
        sql = 'SELECT id,name,created,mode,size,duration,preserved,local_state,cloud_state,cloud_error FROM recordings'
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        return jsonify(items=db.rows(sql + ' ORDER BY created DESC LIMIT 100 OFFSET ?', (*args, offset)))

    @app.post('/api/recordings/<ident>/preserve')
    def preserve(ident):
        if type(request.json.get('preserved')) is not bool:
            raise ValueError('Valor inválido')
        with storage.lock:
            storage.preserve(ident, request.json['preserved'])
        return jsonify(ok=True)

    @app.get('/api/recordings/<ident>/media')
    def media(ident):
        rows = db.rows("SELECT * FROM recordings WHERE id=? AND local_state='local'", (ident,))
        if not rows:
            abort(404)
        try:
            path = storage.path(rows[0])
            if not path.is_file():
                abort(404)
        except (ValueError, OSError):
            abort(404)
        return send_file(path, mimetype='video/mp4' if rows[0]['mode'] != 'audio' else 'audio/mp4',
                         as_attachment=request.args.get('download') == '1', download_name=rows[0]['name'], conditional=True)

    @app.post('/api/cloud/retry')
    def retry():
        db.execute("UPDATE recordings SET retry_at=0 WHERE cloud_state='pending'")
        return jsonify(ok=True)

    @app.post('/api/remote/serve')
    def serve():
        if remote():
            abort(403)
        c = config.snapshot()
        if not c['remote_enabled']:
            raise ValueError('Ative e salve o acesso remoto primeiro')
        binary = shutil.which('tailscale') or r'C:\Program Files\Tailscale\tailscale.exe'
        result = run([binary, 'serve', '--bg', 'http://127.0.0.1:8765'], timeout=30)
        return jsonify(ok=result.returncode == 0, detail=(result.stdout + result.stderr)[-4000:])

    return app
