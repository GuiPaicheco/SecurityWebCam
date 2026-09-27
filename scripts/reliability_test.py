"""Interrupção abrupta real do processo e recuperação usando hardware selecionado."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from securitywebcam.config import Config, atomic_json
from securitywebcam.database import Database
from securitywebcam.storage import Storage, digest
from securitywebcam.capture import Recorder
from securitywebcam.platform import InstanceLock, NO_WINDOW
from hardware_test import wait


def setup(home):
    c=Config(home)
    for key in ['destination','fallback']:Path(c.snapshot()[key]).mkdir(parents=True,exist_ok=True)
    c.save({'camera':'USB Camera','microphone':'Microfone (USB Camera)','mode':'av','segment_seconds':5,'min_free_gb':0.1})
    db=Database(home/'catalog.sqlite3');s=Storage(c,db)
    return c,db,s,Recorder(c,db,s)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--child',action='store_true');parser.add_argument('--home',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'SecurityWebCam-reliability-tests')
    args=parser.parse_args();c,db,s,r=setup(args.home)
    if args.child:
        lock=InstanceLock(args.home)
        r.start_workers();r.command('start')
        wait(lambda:r.status()['state']=='recording',40)
        atomic_json(args.home/'child.json',{'ffmpeg_pid':r.process.pid})
        while True:time.sleep(1)
    (args.home/'child.json').unlink(missing_ok=True)
    p=subprocess.Popen([sys.executable,__file__,'--child','--home',str(args.home)],creationflags=NO_WINDOW)
    try:
        wait(lambda:(args.home/'child.json').exists(),45)
        pid=json.loads((args.home/'child.json').read_text())['ffmpeg_pid']
        wait(lambda:len(db.rows('SELECT * FROM recordings'))>=1,30)
        rows=db.rows('SELECT * FROM recordings');before={x['id']:digest(s.path(x)) for x in rows}
        try:
            duplicate=InstanceLock(args.home)
            raise AssertionError('Instância duplicada aceita')
        except OSError:pass
        p.kill();p.wait(timeout=10)
        import ctypes
        kernel=ctypes.WinDLL('kernel32');kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        def gone():
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:return True
            code=ctypes.c_ulong();kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
            kernel.GetExitCodeProcess(handle,ctypes.byref(code));kernel.CloseHandle(handle)
            return code.value!=259
        wait(gone,10)
        lock=InstanceLock(args.home)
        r.start_workers();r.work.join()
        for row in rows:assert digest(s.path(row))==before[row['id']]
        r.command('start');wait(lambda:r.status()['state']=='recording',40)
        old_pid=r.process.pid
        r.process.kill()
        wait(lambda:r.status()['state']=='recording' and r.process is not None and r.process.pid!=old_pid,50)
        r.command('start');assert r.process.pid!=old_pid
        time.sleep(7)
        r.command('stop');wait(lambda:r.status()['state']=='stopped');r.work.join()
        report={'abrupt_app_kill':True,'ffmpeg_killed_by_job':True,'completed_hashes_preserved':len(before),
                'duplicate_instance_blocked':True,'encoder_failure_recovered':True,'restart_recording':True,
                'segments_after_recovery':len(db.rows('SELECT * FROM recordings')),
                'physical_unplug_tested':False}
        atomic_json(args.home/'reliability-report.json',report)
        print(json.dumps(report,indent=2),flush=True)
    finally:
        if p.poll() is None:p.kill()
        r.shutdown()

if __name__=='__main__':main()
