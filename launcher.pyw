"""Entrada sem console; falhas ficam em arquivo privado, sem notificações."""
import os
from pathlib import Path
import traceback

if __name__ == '__main__':
    try:
        from securitywebcam.__main__ import main
        main()
    except Exception:
        home = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SecurityWebCam'
        home.mkdir(parents=True, exist_ok=True)
        (home / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
