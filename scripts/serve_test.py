"""Servidor de teste em localhost; não habilita autostart, nuvem ou câmera."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from securitywebcam.auth import Auth
from securitywebcam.config import Config
from securitywebcam.database import Database
from securitywebcam.storage import Storage
from securitywebcam.capture import Recorder
from securitywebcam.web import create_app
from securitywebcam.platform import run
from waitress import serve
home=Path(os.environ['LOCALAPPDATA'])/'SecurityWebCam-ui-test'
c=Config(home)
for key in ['destination','fallback']:Path(c.snapshot()[key]).mkdir(parents=True,exist_ok=True)
db=Database(home/'catalog.sqlite3');s=Storage(c,db);r=Recorder(c,db,s);auth=Auth(home)
auth.set_password('test-only-password-123')
root=s.destination();p=root/'20260927T120000-0300_av_00000000000000000000000000000001_000000.mp4.partial'
if not db.rows('SELECT id FROM recordings'):
    result=run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x480:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-f','mp4',str(p)])
    assert result.returncode==0,result.stderr
    import time
    s.publish(root,p,time.time(),'av')
print('Servidor de teste pronto',flush=True)
serve(create_app(c,db,s,r,auth),host='127.0.0.1',port=8765,threads=6,clear_untrusted_proxy_headers=False)
