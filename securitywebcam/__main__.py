import argparse
import atexit
import getpass
import os
from pathlib import Path
import sys
import webbrowser
from .auth import Auth
from .capture import Recorder
from .config import Config
from .database import Database
from .platform import InstanceLock, protect_directory
from .storage import Storage
from .web import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SecurityWebCam')
    parser.add_argument('--set-password', action='store_true')
    parser.add_argument('--autostart', action='store_true')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--shutdown', action='store_true')
    args = parser.parse_args()
    args.home.mkdir(parents=True, exist_ok=True)
    protect_directory(args.home)
    if args.shutdown:
        (args.home / 'stop.request').touch()
        import time
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            try:
                stopped = InstanceLock(args.home)
                stopped.file.close()
                return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError('O aplicativo ainda está finalizando segmentos; tente novamente antes de atualizar')
    try:
        instance = InstanceLock(args.home)
    except OSError:
        if args.open:
            webbrowser.open('http://127.0.0.1:8765')
        return
    auth = Auth(args.home)
    (args.home / 'stop.request').unlink(missing_ok=True)
    if args.set_password:
        password = getpass.getpass('Nova senha (mínimo 12 caracteres): ')
        if password != getpass.getpass('Confirme a senha: '):
            raise ValueError('As senhas não coincidem')
        auth.set_password(password)
        return
    if not auth.path.exists():
        if args.autostart:
            return
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        window = tk.Tk()
        window.withdraw()
        try:
            while True:
                password = simpledialog.askstring('SecurityWebCam — primeira execução', 'Defina a senha do painel (mínimo 12 caracteres):', show='*', parent=window)
                if password is None:
                    return
                confirm = simpledialog.askstring('SecurityWebCam', 'Confirme a senha:', show='*', parent=window)
                try:
                    if password != confirm:
                        raise ValueError('As senhas não coincidem')
                    auth.set_password(password)
                    break
                except ValueError as e:
                    messagebox.showerror('SecurityWebCam', str(e), parent=window)
        finally:
            window.destroy()
    config = Config(args.home)
    for key in ['destination', 'fallback']:
        if config.snapshot()[key] == str(args.home / ('recordings' if key == 'destination' else 'fallback')):
            Path(config.snapshot()[key]).mkdir(exist_ok=True)
    db = Database(args.home / 'catalog.sqlite3')
    storage = Storage(config, db)
    recorder = Recorder(config, db, storage)
    recorder.start_workers()
    import threading
    def watch_shutdown():
        import time
        while True:
            time.sleep(1)
            if (args.home / 'stop.request').exists():
                recorder.shutdown()
                (args.home / 'stop.request').unlink(missing_ok=True)
                db.event('info', 'Aplicativo encerrado por comando local')
                os._exit(0)
    threading.Thread(target=watch_shutdown, daemon=True).start()
    atexit.register(recorder.shutdown)
    if args.autostart and config.snapshot()['autostart']:
        recorder.command('start')
    app = create_app(config, db, storage, recorder, auth)
    db.event('info', 'Aplicativo iniciado' + (' após login (opção automática)' if args.autostart else ' manualmente'))
    if args.open:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:8765')).start()
    from waitress import serve
    try:
        serve(app, host='127.0.0.1', port=8765, threads=6, max_request_body_size=65536,
              clear_untrusted_proxy_headers=False, ident='SecurityWebCam')
    finally:
        recorder.shutdown()


if __name__ == '__main__':
    main()
