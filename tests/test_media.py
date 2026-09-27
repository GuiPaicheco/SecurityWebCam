import json
import shutil
import time
import pytest
from securitywebcam.platform import run

pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg/FFprobe necessários para testes de mídia')


@pytest.mark.parametrize('mode',['audio','video','av'])
def test_publish_decodable_media_and_av_end_alignment(system,mode):
    c,db,s,*_=system
    root=s.destination();source=root/'synthetic.mp4.partial'
    args=['ffmpeg','-v','error','-y']
    if mode!='audio':args+=['-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1.5']
    if mode!='video':args+=['-f','lavfi','-i','sine=sample_rate=48000:duration=1']
    if mode!='audio':args+=['-c:v','libx264','-bf','0','-pix_fmt','yuv420p']
    if mode!='video':args+=['-c:a','aac']
    args+=['-movflags','+frag_keyframe+empty_moov+default_base_moof','-f','mp4',str(source)]
    p=run(args);assert p.returncode==0,p.stderr
    s.publish(root,source,time.time(),mode)
    row=db.rows('SELECT * FROM recordings')[0];published=s.path(row)
    assert published.is_file() and not source.exists()
    info=json.loads(run(['ffprobe','-v','error','-show_streams','-of','json',str(published)]).stdout)
    assert sorted(x['codec_type'] for x in info['streams'])==sorted({'audio':['audio'],'video':['video'],'av':['audio','video']}[mode])
    if mode=='av':
        durations=[float(x['duration']) for x in info['streams']]
        assert max(durations)-min(durations)<0.08
    assert run(['ffmpeg','-v','error','-xerror','-i',str(published),'-f','null','-']).returncode==0
    assert b'moof' not in published.read_bytes()
