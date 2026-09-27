"""Teste explícito da câmera/microfone; gravações permanecem fora do Git."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from securitywebcam.config import Config
from securitywebcam.database import Database
from securitywebcam.storage import Storage
from securitywebcam.capture import Recorder
from securitywebcam.platform import run


def wait(predicate, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.25)
    raise AssertionError('Tempo excedido aguardando condição')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--camera',default='USB Camera')
    parser.add_argument('--microphone',default='Microfone (USB Camera)')
    parser.add_argument('--home',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'SecurityWebCam-hardware-tests')
    args=parser.parse_args()
    c=Config(args.home)
    for key in ['destination','fallback']:Path(c.snapshot()[key]).mkdir(parents=True,exist_ok=True)
    c.save({'camera':args.camera,'microphone':args.microphone,'segment_seconds':5,'min_free_gb':0.1})
    db=Database(args.home/'catalog.sqlite3');s=Storage(c,db)
    report={'platform':sys.platform,'tests':[]}
    for mode in ['audio','video','av']:
        c.save({'mode':mode})
        r=Recorder(c,db,s);r.start_workers()
        since=time.time()
        try:
            r.command('start')
            wait(lambda:r.status()['state']=='recording',40)
            time.sleep(12)
            r.command('pause');wait(lambda:r.status()['state']=='paused')
            r.work.join()
            first=db.rows('SELECT * FROM recordings WHERE created>=?',(since,))
            assert len(first)>=2,(r.status(),db.rows('SELECT * FROM events ORDER BY id DESC LIMIT 4'))
            r.command('resume');wait(lambda:r.status()['state']=='recording',40)
            time.sleep(3)
            r.command('stop');wait(lambda:r.status()['state']=='stopped');r.work.join()
            rows=db.rows('SELECT * FROM recordings WHERE created>=?',(since,))
            evidence=[]
            for row in rows:
                p=s.path(row)
                info=json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]).stdout)
                kinds=[stream['codec_type'] for stream in info['streams']]
                assert sorted(kinds)==sorted({'audio':['audio'],'video':['video'],'av':['audio','video']}[mode])
                decoded=run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'],60)
                assert decoded.returncode==0,decoded.stderr
                streams=[{'type':x['codec_type'],'codec':x['codec_name'],'start':x.get('start_time'),'duration':x.get('duration')} for x in info['streams']]
                evidence.append({'duration':row['duration'],'bytes':row['size'],'streams':streams,'decode_exit':decoded.returncode})
            report['tests'].append({'mode':mode,'passed':True,'segments':evidence,'pause_resume':True})
            print(mode,'PASS',len(rows),'segmentos',flush=True)
        except Exception as e:
            report['tests'].append({'mode':mode,'passed':False,'error':str(e),'status':r.status(),'events':db.rows('SELECT * FROM events ORDER BY id DESC LIMIT 8')})
            print(mode,'FAIL',str(e),flush=True)
        finally:r.shutdown()
    args.home.mkdir(parents=True,exist_ok=True)
    (args.home/'hardware-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Relatório:',args.home/'hardware-report.json',flush=True)
    return 0 if all(t['passed'] for t in report['tests']) else 1

if __name__=='__main__':sys.exit(main())
