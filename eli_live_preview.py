"""Real-time V1 opacity crossfades using a second muted Qt video decoder.

The edited V1 remains authoritative. Preview never writes files or changes
the FFmpeg export graph, trims, effects or source files.
"""
import os
from PySide6.QtCore import QUrl
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

    def on_frame(self,frame):
        if self.window is not None and frame.isValid():
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
        self.overlay.set_fade_alpha(w['alpha'])
        if not self.ready:return
        self._seek_to_timeline()
        if playing and w['alpha']>0:
            if self.player.playbackState()!=QMediaPlayer.PlayingState:
                self.player.play()
        elif self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause()
