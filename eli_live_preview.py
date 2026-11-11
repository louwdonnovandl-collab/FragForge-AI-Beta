"""Real-time V1 opacity crossfades using a second muted Qt video decoder.

The edited V1 remains authoritative. Preview never writes files or changes
the FFmpeg export graph, trims, effects or source files.
"""
import os
import math
import subprocess
from PySide6.QtCore import QUrl, QThread, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink


def _seconds(clip):
    return (float(clip['end'])-float(clip['start'])) / max(.01,float(clip.get('speed',1.)))


def incoming_fade(clips, t, preload=2.0):
    """Return source-accurate V1 opacity fade information near an edit point."""
    t=float(t)
    primary=sorted(
        (clip for clip in clips if clip.get('track')=='V1'
         and clip.get('kind','video')=='video'),
        key=lambda clip:float(clip.get('at',0.)))
    for old,new in zip(primary, primary[1:]):
        boundary=float(new.get('at',0.))
        seconds=float(new.get('crossfade_seconds',0.))
        if (new.get('transition')!='fade' or seconds<.05
                or not boundary-seconds-max(0.,float(preload))<=t<boundary):
            continue
        if abs(float(old.get('at',0.))+_seconds(old)-boundary)>.05:
            continue
        if min(_seconds(old),_seconds(new)) < 2*seconds-.005:
            continue
        same=(os.path.normcase(os.path.abspath(str(old['path'])))==
              os.path.normcase(os.path.abspath(str(new['path']))))
        if (same and abs(float(old['end'])-float(new['start']))<=.05
                and abs(float(old.get('speed',1.))-float(new.get('speed',1.)))<=.0001
                and not new.get('eli_force_transition',False)):
            continue # FFmpeg joins consecutive source frames without blending
        rate=max(.01,float(new.get('speed',1.)))
        alpha=max(0.,min(1.,(t-(boundary-seconds))/seconds))
        source_start=max(0.,float(new['start'])-seconds*rate)
        return {'clip':new,'boundary':boundary,'seconds':seconds,
                'alpha':alpha,'rate':rate,'source_start':source_start,
                'source_at':boundary-seconds}
    return None


def ending_fade_gain(clips, t):
    """Match the final exported whole-picture one-second fade to black."""
    videos=sorted((c for c in clips if c.get('track')=='V1'
                   and c.get('kind','video')=='video'),
                  key=lambda c:float(c.get('at',0.)))
    if not videos or not videos[-1].get('eli_end_fade',False):
        return 1.
    end=float(videos[-1]['at'])+_seconds(videos[-1])
    fade=min(1.,end)
    return max(0.,min(1.,(end-float(t))/fade)) if fade else 1.



class FadeFrameWorker(QThread):
    """Prefetch a short incoming V1 video segment, without exporting the video."""
    ready=Signal(object,object)
    failed=Signal(object,str)

    def __init__(self,key,window,parent=None):
        super().__init__(parent)
        self.key=key
        self.window=dict(window)

    def run(self):
        try:
            from media import binary
            w=self.window
            count=max(2,int(math.ceil(w['seconds']*30))+1)
            width,height=640,360
            source_start=float(w['source_start'])
            command=[
                binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','error',
                '-ss',str(source_start),'-i',str(w['clip']['path']),
                '-vf',('fps=30,scale=640:360:force_original_aspect_ratio=decrease,'
                       'pad=640:360:(ow-iw)/2:(oh-ih)/2,format=rgb24'),
                '-frames:v',str(count),'-an','-f','rawvideo',
                '-pix_fmt','rgb24','pipe:1']
            result=subprocess.run(
                command,capture_output=True,timeout=40,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors='replace')[-600:])
            size=width*height*3
            frames=[]
            for i in range(min(count,len(result.stdout)//size)):
                data=result.stdout[i*size:(i+1)*size]
                frame=QImage(data,width,height,width*3,QImage.Format_RGB888)
                frames.append(frame.copy())
            if not frames:
                raise RuntimeError('No frames decoded for incoming fade')
            self.ready.emit(self.key,frames)
        except Exception as exc:
            self.failed.emit(self.key,str(exc))


class LiveFadeController:
    """Preload and decode the incoming clip on a muted secondary video sink."""
    def __init__(self, editor, overlay):
        self.editor=editor
        self.overlay=overlay
        self.player=QMediaPlayer(editor)
        self.audio=QAudioOutput(editor)
        self.audio.setVolume(0.)
        self.player.setAudioOutput(self.audio)
        self.sink=QVideoSink(editor)
        self.player.setVideoOutput(self.sink)
        self.sink.videoFrameChanged.connect(self.on_frame)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.key=None
        self.window=None
        self.playing=False
        self.ready=False
        self.frames_cache={}
        self.frame_workers={}
        self.frame_failures=set()

    def _frame_key(self,window):
        clip=window['clip']
        return (os.path.normcase(os.path.abspath(str(clip['path']))),
                round(float(window['source_start']),3),
                round(float(window['seconds']),3),
                round(float(window['rate']),5))

    def _request_frames(self,window):
        key=self._frame_key(window)
        if (key in self.frames_cache or key in self.frame_workers
                or key in self.frame_failures):
            return
        if len(self.frame_workers)>=2:return
        worker=FadeFrameWorker(key,window,self.editor)
        self.frame_workers[key]=worker
        def received(result_key,frames):
            self.frames_cache[result_key]=frames
            if len(self.frames_cache)>5:
                oldest=next(iter(self.frames_cache))
                if oldest!=result_key:self.frames_cache.pop(oldest,None)
            self.update(self.editor.playhead,
                        self.editor.player.playbackState()==QMediaPlayer.PlayingState)
        worker.ready.connect(received)
        worker.failed.connect(lambda result_key,msg:self.frame_failures.add(result_key))
        worker.finished.connect(lambda:self.frame_workers.pop(key,None))
        worker.start()

    def on_frame(self,frame):
        if self.window is not None and frame.isValid():
            if self._frame_key(self.window) not in self.frames_cache:
                self.overlay.receive_fade_frame(frame)

    def on_status(self,status):
        if status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia,
                      QMediaPlayer.BufferingMedia):
            self.ready=True
            if self.window is not None:
                self._seek_to_timeline()
                if self.playing and self.window['alpha']>0.:
                    self.player.play()

    def _seek_to_timeline(self):
        if self.window is None:return
        w=self.window
        t=float(self.editor.playhead)
        expected=max(0.,w['source_start']+
                     (t-w['source_at'])*w['rate'])
        ms=round(expected*1000)
        if abs(self.player.position()-ms)>160:
            self.player.setPosition(ms)

    def reset(self):
        if self.key is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self.key=None
        self.window=None
        self.ready=False
        self.playing=False
        self.overlay.clear_fade_frame()

    def update(self,seconds,playing):
        ahead=incoming_fade(self.editor.clips,seconds,preload=10.)
        if ahead is not None:self._request_frames(ahead)
        w=incoming_fade(self.editor.clips,seconds)
        if w is None:
            if self.key is not None:self.reset()
            return
        following=w['clip']
        identity=(id(following),os.path.abspath(following['path']),
                  float(following['start']),float(following['at']),
                  w['seconds'],w['rate'])
        if self.key!=identity:
            self.reset()
            self.key=identity
            self.window=w
            self.playing=bool(playing)
            self.player.setPlaybackRate(w['rate'])
            self.player.setSource(QUrl.fromLocalFile(os.path.abspath(following['path'])))
        else:
            self.window=w
            self.playing=bool(playing)
        cached=self.frames_cache.get(self._frame_key(w))
        if cached and w['alpha']>0.:
            frame_index=min(len(cached)-1,max(0,int(
                (float(seconds)-(w['boundary']-w['seconds']))*30.)))
            self.overlay.fade_image=cached[frame_index]
        self.overlay.set_fade_alpha(
            w['alpha'] if (cached or not self.overlay.fade_image.isNull()) else 0.)
        if not self.ready:return
        self._seek_to_timeline()
        if playing and w['alpha']>0:
            if self.player.playbackState()!=QMediaPlayer.PlayingState:
                self.player.play()
        elif self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause()
