"""Exercita o launcher real, HTTP e encerramento silencioso sem ligar dispositivos."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from securitywebcam.auth import Auth
from securitywebcam.platform import NO_WINDOW

home=Path(os.environ['LOCALAPPDATA'])/'SecurityWebCam-lifecycle-tests'
home.mkdir(exist_ok=True)
Auth(home).set_password('test-only-password-123')
launcher=Path(__file__).resolve().parents[1]/'launcher.pyw'
pythonw=Path(sys.executable).with_name('pythonw.exe')
p=subprocess.Popen([str(pythonw),str(launcher),'--home',str(home)],creationflags=NO_WINDOW)
base='http://127.0.0.1:8765'
try:
    end=time.monotonic()+20
    while True:
        try:
            assert requests.get(base+'/api/status',timeout=2).status_code==401
            break
        except requests.ConnectionError:
            if time.monotonic()>end:raise
            time.sleep(.25)
    session=requests.Session()
    response=session.post(base+'/api/login',json={'password':'test-only-password-123'},headers={'Origin':base},timeout=5)
    assert response.status_code==200,response.text
    assert session.get(base+'/api/status',timeout=5).json()['capture']['state']=='stopped'
    duplicate=subprocess.run([str(pythonw),str(launcher),'--home',str(home)],timeout=10,creationflags=NO_WINDOW)
    assert duplicate.returncode==0
    stop=subprocess.run([sys.executable,'-m','securitywebcam','--home',str(home),'--shutdown'],timeout=30,creationflags=NO_WINDOW)
    assert stop.returncode==0
    p.wait(timeout=10)
    assert p.returncode==0
    result={'pythonw_launcher':True,'http_login':True,'unauthorized_blocked':True,'duplicate_launch_exits':True,'graceful_shutdown':True,'capture_default_stopped':True}
    (home/'lifecycle-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
finally:
    if p.poll() is None:p.kill()
