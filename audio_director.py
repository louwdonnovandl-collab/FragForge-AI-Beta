"""Local gameplay audio activity analyzer. Detects transients, not confirmed gunshots or kills."""
import array, math, subprocess, sys
from media import binary


def scan_audio(path, end, progress=None, cancel=None, sample_rate=8000, seconds_per_window=0.5):
    """Decode mono PCM in a bounded subprocess and identify relatively loud, abrupt events."""
    cmd=[binary('ffmpeg'),'-hide_banner','-loglevel','error','-i',str(path),'-vn',
         '-ac','1','-ar',str(sample_rate),'-f','s16le','-t',str(max(0.1,end)),'pipe:1']
    proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    size=int(sample_rate*seconds_per_window)*2
    levels=[]
    try:
        while True:
            if cancel is not None and cancel.is_set():raise RuntimeError('Audio scan cancelled')
            chunk=proc.stdout.read(size)
            if not chunk:break
            chunk=chunk[:len(chunk)//2*2]
            if not chunk:break
            samples=array.array('h');samples.frombytes(chunk)
            if sys.byteorder!='little':samples.byteswap()
            rms=math.sqrt(sum(x*x for x in samples)/len(samples))/32768.
            levels.append(rms)
            if progress and len(levels)%40==0:progress(min(99,int(len(levels)*seconds_per_window/max(end,1)*100)))
        if proc.wait(timeout=10)!=0:raise RuntimeError('FFmpeg could not decode the source audio')
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        if proc.stdout:proc.stdout.close()
    if not levels:return {'events':[],'status':'No decodable audio track','window_seconds':seconds_per_window}
    sorted_levels=sorted(levels)
    median=sorted_levels[len(sorted_levels)//2]
    events=[];last=-10.
    for i in range(2,len(levels)-2):
        baseline=sum(levels[max(0,i-8):i])/min(i,8)
        level=levels[i]
        # A transient must be loud relative to local background and recording baseline.
        if level>max(.015,median*1.8,baseline*2.2) and level>=max(levels[i-1],levels[i+1]):
            t=(i+.5)*seconds_per_window
            if t-last<2.5:continue
            strength=min(1.,level/max(.03,median*4))
            events.append({'time':round(t,2),'event':'audio_transient','strength':round(strength,3)})
            last=t
    if progress:progress(100)
    return {'events':events[:500],'status':'Audio transients estimated (not classified gunshots or kills)',
            'window_seconds':seconds_per_window}


def corroborate_vision(samples,audio_events,radius=7.):
    """Audio can boost ranked combat candidates, never turn a noncombat frame into a kill."""
    output=[]
    for item in samples:
        item=dict(item)
        nearby=[e for e in audio_events if abs(e['time']-item['time'])<=radius]
        item['audio_support']=bool(nearby)
        if item.get('event')=='combat' and nearby:
            item['confidence']=round(min(1.,float(item.get('confidence',0))+.08),3)
        output.append(item)
    return output
