"""Offline scene-change based editing assistant. No external service or ML model."""
import re, subprocess
from media import binary

def find_scene_changes(path, start=0.0, end=180.0, sensitivity=0.24,
                       progress=None, stage=None, cancel=None, idle_timeout=30):
    """Single-pass, bounded FFmpeg analysis. No unread pipe or hidden second scan.

    Progress comes from FFmpeg's -progress output; a watchdog aborts silent
    processes rather than allowing an indefinite 0% animation.
    """
    import os, queue, tempfile, threading, time
    from pathlib import Path
    if not Path(path).is_file():
        raise FileNotFoundError('Video file not found: '+str(path))
    if end <= start:
        raise ValueError('The selected clip has no valid source duration.')
    duration=float(end-start)
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    if stage: stage('Launching FFmpeg scene analysis…')
    if progress: progress(0)
    # showinfo goes to stderr; store it in a file to avoid PIPE deadlocks.
    # -progress goes to stdout and is drained by a dedicated reader thread.
    filtergraph=f"fps=2,scale=320:-2,select='gt(scene,{float(sensitivity):.3f})',showinfo"
    command=[binary('ffmpeg'),'-hide_banner','-nostdin','-y',
             '-loglevel','info','-stats_period','0.5',
             '-ss',str(max(0.,float(start))),'-i',str(path),
             '-t',str(duration),'-vf',filtergraph,'-an',
             '-progress','pipe:1','-f','null','-']
    with tempfile.TemporaryFile(mode='w+t',encoding='utf-8',errors='replace') as errors:
        try:
            proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,
                                  text=True,bufsize=1,creationflags=flags)
        except OSError as exc:
            raise RuntimeError('Could not start bundled FFmpeg: '+str(exc)) from exc
        updates=queue.Queue()
        def drain():
            try:
                for line in proc.stdout:
                    updates.put(line.strip())
            finally:
                updates.put(None)
        reader=threading.Thread(target=drain,daemon=True)
        reader.start()
        last_activity=time.monotonic()
        began=last_activity
        max_seconds=max(120.,duration*4.)
        complete=False
        last_pct=-1
        if stage: stage('Scanning frames and detecting scene changes…')
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise RuntimeError('Analysis cancelled by user.')
                now=time.monotonic()
                if now-last_activity>idle_timeout:
                    raise TimeoutError(f'FFmpeg produced no progress for {idle_timeout} seconds. Check the source codec or FFmpeg installation.')
                if now-began>max_seconds:
                    raise TimeoutError(f'Analysis exceeded {int(max_seconds)} seconds and was stopped.')
                try: line=updates.get(timeout=0.25)
                except queue.Empty:
                    if proc.poll() is not None and not reader.is_alive():
                        break
                    continue
                if line is None:
                    complete=True
                    break
                if line.startswith('out_time='):
                    try:
                        hh,mm,ss=line.partition('=')[2].split(':')
                        seconds=int(hh)*3600+int(mm)*60+float(ss)
                        pct=max(0,min(99,int(100*seconds/duration)))
                        last_activity=time.monotonic()
                        if pct>last_pct:
                            last_pct=pct
                            if progress: progress(pct)
                    except (ValueError,OverflowError):
                        pass
                elif line.startswith('progress='):
                    last_activity=time.monotonic()
            code=proc.wait(timeout=5)
            if code:
                errors.seek(0)
                raise RuntimeError('FFmpeg analysis failed (exit '+str(code)+'): '+errors.read()[-1800:])
            errors.seek(0)
            log=errors.read()
        except Exception:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            raise
        finally:
            try: proc.stdout.close()
            except Exception: pass
    times=[]
    for match in re.finditer(r'pts_time:([0-9]+(?:\.[0-9]+)?)',log):
        value=float(start)+float(match.group(1))
        if start+.5<value<end-.5 and (not times or value-times[-1]>=1.):
            times.append(value)
    if progress: progress(100)
    if stage: stage('Analysis complete')
    return times

def full_length_segments(start,end,segment_seconds=60):
    """Keep the entire selected recording, up to one hour, in ordered clips."""
    stop=min(float(end),float(start)+3600.)
    points=[];cursor=float(start)
    while cursor<stop-.01:
        next_point=min(stop,cursor+max(5.,float(segment_seconds)))
        points.append((cursor,next_point));cursor=next_point
    return points

def choose_highlights(cuts, start, end, count=6, seconds=4.0):
    """Space candidate highlight windows across detected cuts; never claim semantic understanding."""
    count=max(1,min(20,int(count)))
    seconds=max(1.,float(seconds))
    candidates=[float(t) for t in cuts if start<=t<end]
    if not candidates:
        span=max(0.,end-start-seconds)
        candidates=[start+span*(i+.5)/count for i in range(count)]
    chosen=[]
    for i in range(min(count,len(candidates))):
        index=min(len(candidates)-1,int((i+.5)*len(candidates)/min(count,len(candidates))))
        center=candidates[index]
        a=max(start,min(center-seconds*.35,end-seconds))
        b=min(end,a+seconds)
        if b-a>=.5 and not any(abs(a-x[0])<seconds*.6 for x in chosen):chosen.append((a,b))
    return sorted(chosen)

def detect_stagnant_ranges(path, start, end, min_seconds=5.0, progress=None, stage=None, cancel=None):
    """Detect near-identical frames with a low-resolution 1-fps grayscale scan.
    A conservative threshold reduces false positives; not semantic loading-screen recognition.
    """
    import os, time
    from pathlib import Path
    if not Path(path).is_file(): raise FileNotFoundError(path)
    if stage: stage('Checking for loading screens and stagnant footage…')
    w,h=96,54
    size=w*h
    command=[binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','error',
             '-ss',str(max(0.,start)),'-i',str(path),'-t',str(max(.1,end-start)),
             '-vf',f'fps=1,scale={w}:{h},format=gray','-an',
             '-f','rawvideo','-pix_fmt','gray','pipe:1']
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    prev=None;still_begin=None;index=0;ranges=[]
    last_change=time.monotonic()
    try:
        while True:
            if cancel is not None and cancel.is_set():raise RuntimeError('Analysis cancelled.')
            frame=proc.stdout.read(size)
            if not frame:break
            if len(frame)!=size:break
            t=start+index
            if prev is not None:
                # Sample 1/4 of pixels. Normal video motion exceeds ~2.5 gray levels.
                diff=sum(abs(frame[k]-prev[k]) for k in range(0,size,4))/(size//4)
                if diff<2.5:
                    if still_begin is None:still_begin=t-1
                else:
                    if still_begin is not None and t-still_begin>=min_seconds:
                        ranges.append((still_begin,t))
                    still_begin=None
            prev=frame;index+=1;last_change=time.monotonic()
            if progress:progress(min(99,int(index/max(1,end-start)*100)))
        if still_begin is not None and end-still_begin>=min_seconds:
            ranges.append((still_begin,end))
        if proc.wait(timeout=5)!=0:raise RuntimeError('FFmpeg stagnant-frame scan failed.')
    except Exception:
        if proc.poll() is None:proc.kill()
        proc.wait()
        raise
    finally:
        if proc.stdout:proc.stdout.close()
    if progress:progress(100)
    return ranges

def keep_ranges_after_removal(start,end,removed,minimum_clip=0.5):
    """Preserve all footage except detected stagnant spans."""
    kept=[];cursor=float(start)
    for a,b in sorted(removed):
        a=max(cursor,min(end,a));b=max(a,min(end,b))
        if a-cursor>=minimum_clip:kept.append((cursor,a))
        cursor=max(cursor,b)
    if end-cursor>=minimum_clip:kept.append((cursor,end))
    return kept


def analyze_motion_profile(path, start, end, progress=None, stage=None, cancel=None):
    """Offline visual activity heuristic; not object or game-event recognition.

    Classifies long stretches of low frame-to-frame change as candidates for 2x
    speed. Returns stagnant spans and low-motion spans in source seconds.
    """
    import os
    if stage: stage('Scanning visual activity for quiet sections…')
    w,h=96,54; size=w*h
    command=[binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','error',
             '-ss',str(max(0.,start)),'-i',str(path),'-t',str(max(.1,end-start)),
             '-vf',f'fps=1,scale={w}:{h},format=gray','-an',
             '-f','rawvideo','-pix_fmt','gray','pipe:1']
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    prev=None;index=0;diffs=[]
    try:
        while True:
            if cancel is not None and cancel.is_set(): raise RuntimeError('Analysis cancelled.')
            frame=proc.stdout.read(size)
            if not frame:break
            if len(frame)!=size:break
            if prev is not None:
                diff=sum(abs(frame[k]-prev[k]) for k in range(0,size,4))/(size//4)
                diffs.append((start+index-1,diff))
            prev=frame;index+=1
            if progress and index%4==0:progress(min(99,int(index/max(1,end-start)*100)))
        if proc.wait(timeout=10)!=0:raise RuntimeError('FFmpeg motion scan failed.')
    except Exception:
        if proc.poll() is None:proc.kill()
        proc.wait();raise
    finally:
        if proc.stdout:proc.stdout.close()
    def spans(predicate,min_len):
        result=[];begin=None;last=None
        for t,d in diffs:
            if predicate(d):
                if begin is None:begin=t
                last=t+1
            else:
                if begin is not None and last-begin>=min_len:result.append((begin,last))
                begin=None;last=None
        if begin is not None and last-begin>=min_len:result.append((begin,last))
        return result
    stagnant=spans(lambda d:d<2.5,5.)
    # Motion alone cannot identify walking/looting; use conservative thresholds.
    quiet=spans(lambda d:2.5<=d<9.0,12.)
    # Rank isolated activity peaks; these are NOT confirmed combat events.
    # Local contrast reduces false positives from continuous scrolling/movement.
    peaks=[]
    for i in range(3,len(diffs)-3):
        t,score=diffs[i]
        local=[v for _,v in diffs[i-3:i+4]]
        baseline=sorted(local)[len(local)//2]
        if score>=14. and score>=max(local) and score-baseline>=4.:
            if not peaks or t-peaks[-1][0]>=6.:
                peaks.append((t,round(score-baseline,2)))
            elif score-baseline>peaks[-1][1]:
                peaks[-1]=(t,round(score-baseline,2))
    if progress:progress(100)
    if stage:stage('Visual activity scan complete')
    return {'stagnant':stagnant,'quiet':quiet,'activity_peaks':peaks}


def smart_pacing_segments(start,end,stagnant,quiet,fast_speed=2.0):
    """Return (source start, source end, playback speed), preserving time order."""
    kept=keep_ranges_after_removal(start,end,stagnant)
    result=[]
    for a,b in kept:
        boundaries={a,b}
        for x,y in quiet:
            if a<x<b:boundaries.add(x)
            if a<y<b:boundaries.add(y)
        points=sorted(boundaries)
        for x,y in zip(points,points[1:]):
            if y-x<.5:continue
            midpoint=(x+y)/2
            quick=any(q0<=midpoint<q1 for q0,q1 in quiet)
            speed=fast_speed if quick and y-x>=3 else 1.
            # Keep export filter graphs bounded to two-minute source sections.
            cursor=x
            while cursor<y-.01:
                stop=min(y,cursor+120.)
                result.append((cursor,stop,speed));cursor=stop
    return result
