"""Integration test: V1 preview must produce real mixed frames, not hard cuts."""
import os
import subprocess
import tempfile
from pathlib import Path

from eli_live_preview import incoming_fade, _ffmpeg_command, PREVIEW_WIDTH, PREVIEW_HEIGHT
from media import binary


def run(*args):
    return subprocess.run(list(args),capture_output=True,check=True,timeout=50,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


with tempfile.TemporaryDirectory(prefix='eli_v1_fade_') as directory:
    clips=[]
    for color in ('red','blue'):
        path=str(Path(directory)/(color+'.mp4'))
        run(binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','error',
            '-y','-f','lavfi','-i',f'color=c={color}:s=640x360:r=30:d=2',
            '-c:v','mpeg4','-q:v','3',path)
        clips.append(path)
    a={'path':clips[0],'start':0.,'end':1.,'at':0.,'track':'V1',
       'kind':'video','speed':1.,'transition':'fade','crossfade_seconds':.5}
    b=dict(a,path=clips[1],start=0.5,end=1.5,at=1.,
           eli_force_transition=True)
    window=incoming_fade([a,b],.75,preload=0.)
    assert window and abs(window['alpha']-.5)<.01,window
    result=run(*_ffmpeg_command(window))
    frame_size=PREVIEW_WIDTH*PREVIEW_HEIGHT*3
    count=len(result.stdout)//frame_size
    assert count>=10,(count,len(result.stdout),result.stderr[-200:])
    def rgb(frame):
        index=(frame*frame_size)+(PREVIEW_WIDTH*(PREVIEW_HEIGHT//2)
                                  +(PREVIEW_WIDTH//2))*3
        return tuple(result.stdout[index:index+3])
    first=rgb(0)
    middle=rgb(count//2)
    last=rgb(count-1)
    assert first[0]>first[2]*2,(first,middle,last)
    assert 40<middle[0]<220 and 40<middle[2]<220,(first,middle,last)
    assert last[2]>last[0]*2,(first,middle,last)
    print('PASS: Live V1 fade renders real red/blue composite frames:',
          'first',first,'middle',middle,'last',last,'frames',count)
    for style in ('dissolve','wipeleft','radial','pixelize'):
        other=dict(b,transition=style)
        candidate=incoming_fade([a,other],.75,preload=0.)
        assert candidate and candidate['style']==style,candidate
        filtered=run(*_ffmpeg_command(candidate))
        assert len(filtered.stdout)>=10*frame_size,(style,len(filtered.stdout))
        print('PASS: V1 transition style',style)
