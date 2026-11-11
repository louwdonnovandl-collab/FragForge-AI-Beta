"""On-demand V1 transition preview. Renders only the half-second transition.

Uses the same FFmpeg xfade preset as export. Unlike Qt source playback, it
predecodes both sides of a cut, caches composite frames, and paints those frames
in the existing monitor. It never exports or modifies the full timeline.
"""
import math
import os
import subprocess
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


PREVIEW_FPS=30
PREVIEW_WIDTH=640
PREVIEW_HEIGHT=360
PREFETCH_SECONDS=9.


def _seconds(c):
    return (float(c['end'])-float(c['start']))/max(.01,float(c.get('speed',1.)))


def incoming_fade(clips, t, preload=2.):
    """Return export-matched transition details around an edited V1 boundary."""
    from media import eli_transition_profile
    t=float(t)
    primary=sorted((c for c in clips if c.get('track')=='V1' and
                    c.get('kind','video')=='video'),
                   key=lambda c:float(c.get('at',0.)))
    for before,after in zip(primary,primary[1:]):
        boundary=float(after['at'])
        seconds=float(after.get('crossfade_seconds',0.))
        style=str(after.get('transition','cut')).lower()
        if (seconds<.05 or style=='cut' or
                not boundary-seconds-max(0.,float(preload))<=t<boundary):
            continue
        if abs(float(before['at'])+_seconds(before)-boundary)>.05:
            continue
        policy=eli_transition_profile(before,after)
        if policy['kind']!='blend':continue
        rate_a=max(.01,float(before.get('speed',1.)))
        rate_b=max(.01,float(after.get('speed',1.)))
        preroll=float(policy['preroll'])
        return {
            'before':before,'clip':after,'boundary':boundary,
            'seconds':seconds,'style':style,
            'rate_a':rate_a,'rate':rate_b,'preroll':preroll,
            'freeze_pad':float(policy['freeze_pad']),
            'source_a':max(0.,float(before['end'])-seconds*rate_a),
            'source_start':max(0.,float(after['start'])-preroll*rate_b),
            'source_at':boundary-seconds,
            'alpha':max(0.,min(1.,(t-(boundary-seconds))/seconds))
        }
    return None


def ending_fade_gain(clips,t):
    videos=sorted((c for c in clips if c.get('track')=='V1' and
                   c.get('kind','video')=='video'),
                  key=lambda c:float(c.get('at',0.)))
    if not videos or not videos[-1].get('eli_end_fade',False):return 1.
    end=float(videos[-1]['at'])+_seconds(videos[-1])
    fade=min(1.,end)
    return max(0.,min(1.,(end-float(t))/fade)) if fade else 1.


def _key(w):
    before,after=w['before'],w['clip']
    return (
        os.path.normcase(os.path.abspath(str(before['path']))),
        round(w['source_a'],4),round(w['rate_a'],5),
        os.path.normcase(os.path.abspath(str(after['path']))),
        round(w['source_start'],4),round(w['rate'],5),
        w['style'],round(w['seconds'],4),
        round(w['freeze_pad'],4))


def _ffmpeg_command(w):
    """Produce a few FFmpeg xfade frames, not a rendered video file."""
    from media import binary
    d=w['seconds'];rate_a=w['rate_a'];rate_b=w['rate']
    preroll=w['preroll'];pad=w['freeze_pad']
    width=PREVIEW_WIDTH;height=PREVIEW_HEIGHT;fps=PREVIEW_FPS
    video=(f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
           f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
           f'fps={fps},format=yuv420p')
    freeze=(f'tpad=start_mode=clone:start_duration={pad:.6f},'
            if pad>.001 else '')
    # The short inputs are already limited by -ss/-t. Adding trim and
    # settb=AVTB here caused FFmpeg to report "rate 1/0 is invalid" for
    # xfade on Windows/Linux. Keep explicit CFR via fps=30 and no pre-xfade
    # trim; export continues using its own (already working) graph.
    graph=(
        f'[0:v]setpts=(PTS-STARTPTS)/{rate_a:.6f},{video}[a];'
        f'[1:v]setpts=(PTS-STARTPTS)/{rate_b:.6f},{video},'
        f'{freeze}format=yuv420p[b];'
        f'[a][b]xfade=transition={w["style"]}:duration={d:.6f}:offset=0,'
        f'format=rgb24,fps={fps}[out]')
    # Request slightly more decoded footage than the transition length to
    # survive seek rounding and sparse keyframes.
    return [
        binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','error',
        '-ss',f'{w["source_a"]:.6f}',
        '-t',f'{max(.40,d*rate_a+.25):.6f}',
        '-i',str(w['before']['path']),
        '-ss',f'{w["source_start"]:.6f}',
        '-t',f'{max(.40,preroll*rate_b+.25):.6f}',
        '-i',str(w['clip']['path']),
        '-filter_complex',graph,'-map','[out]','-frames:v',
        str(max(2,int(math.ceil(d*fps)))),'-an',
        '-f','rawvideo','-pix_fmt','rgb24','pipe:1']


class FadeFrameWorker(QThread):
    ready=Signal(object,object)
    failed=Signal(object,str)

    def __init__(self,key,window,parent=None):
        super().__init__(parent)
        self.key=key
        self.window=dict(window)

    def run(self):
        try:
            result=subprocess.run(
                _ffmpeg_command(self.window),capture_output=True,timeout=35,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                raise RuntimeError(
                    result.stderr.decode('utf-8','replace')[-500:])
            width,height=PREVIEW_WIDTH,PREVIEW_HEIGHT
            frame_bytes=width*height*3
            frames=[]
            for i in range(min(int(math.ceil(self.window['seconds']*PREVIEW_FPS)),
                               len(result.stdout)//frame_bytes)):
                data=result.stdout[i*frame_bytes:(i+1)*frame_bytes]
                frames.append(QImage(data,width,height,width*3,QImage.Format_RGB888).copy())
            if not frames:raise RuntimeError('FFmpeg returned zero V1 transition frames')
            self.ready.emit(self.key,frames)
        except Exception as exc:
            self.failed.emit(self.key,str(exc))


class LiveFadeController:
    """Caches final xfade pictures so V1 playback and paused scrubbing work."""
    def __init__(self,editor,overlay):
        self.editor=editor
        self.overlay=overlay
        self.frames_cache={}
        self.workers={}
        self.failures={}
        self.current_key=None

    def reset(self):
        self.current_key=None
        self.overlay.clear_fade_frame()

    def shutdown(self):
        self.reset()
        for worker in list(self.workers.values()):
            if worker.isRunning():worker.wait(36000)

    def _request(self,w):
        key=_key(w)
        if key in self.frames_cache or key in self.workers or key in self.failures:
            return
        if len(self.workers)>=2:return
        worker=FadeFrameWorker(key,w,self.editor)
        self.workers[key]=worker
        def success(result_key,frames):
            self.frames_cache[result_key]=frames
            while len(self.frames_cache)>5:
                self.frames_cache.pop(next(iter(self.frames_cache)))
            self.update(self.editor.playhead,False)
        def failure(result_key,msg):
            self.failures[result_key]=msg
            self.editor.note.setText('V1 transition preview failed: '+msg[:180])
        def finished():
            self.workers.pop(key,None)
            worker.deleteLater()
        worker.ready.connect(success)
        worker.failed.connect(failure)
        worker.finished.connect(finished)
        worker.start()

    def update(self,seconds,playing=False):
        # Preload the *complete composited* transition, including wipes and
        # dissolves, well before the playhead reaches it.
        ahead=incoming_fade(self.editor.clips,seconds,preload=PREFETCH_SECONDS)
        if ahead is not None:self._request(ahead)
        actual=incoming_fade(self.editor.clips,seconds,preload=0.)
        if actual is None:
            if self.current_key is not None:self.reset()
            return
        key=_key(actual)
        self.current_key=key
        frames=self.frames_cache.get(key)
        if not frames:
            self.overlay.clear_fade_frame()
            return
        elapsed=max(0.,float(seconds)-(actual['boundary']-actual['seconds']))
        pos=min(len(frames)-1,int(elapsed*PREVIEW_FPS))
        # Precomposited image already includes BOTH clips, so draw it at 100%.
        self.overlay.fade_image=frames[max(0,pos)]
        self.overlay.set_fade_alpha(1.)
