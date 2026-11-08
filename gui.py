"""FragForge 0.10.1: Qt multi-track editing workspace (preview uses source player)."""
import copy, math, os, sys, json, subprocess, struct, threading, re, time
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Signal, QThread, QTimer, QRectF, QMimeData, QObject, QEvent, QSize
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QShortcut, QKeySequence, QPainter, QDrag, QPixmap, QImage, QIcon, QMovie
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QPushButton,QLabel,QListWidget,QFileDialog,QMessageBox,QSplitter,QGraphicsView,QGraphicsScene,QSlider,QFrame,QInputDialog,QDoubleSpinBox,QScrollArea,QTabWidget,QProgressBar,QComboBox,QToolButton, QAbstractItemView, QCheckBox, QSizePolicy, QLayout, QDialog, QLineEdit, QPlainTextEdit, QListWidgetItem, QStackedLayout)
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput,QMediaDevices,QSoundEffect,QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from media import probe, export_layers, nvenc_available, binary
from effects import EFFECTS, effect_path
from sounds import SOUNDS, resolve_sound, user_sounds, import_user_sound
from director_executor import runtime, select_runtime, intro_candidates, intro_from_activity, ranked_activity_cues, precision_montage
from version import DISPLAY_NAME
from vision_director import installed_models, scan as vision_scan, combat_windows
from audio_director import scan_audio, corroborate_vision
from recognition_markers import build_markers, director_report, export_report
from music_intelligence import scan_library, choose_track, genre_for_request
from ai_runtime import PROFILES, acquire as acquire_ai_job, release as release_ai_job, busy as ai_job_busy
from auto_editor import find_scene_changes, choose_highlights, full_length_segments, detect_stagnant_ranges, keep_ranges_after_removal, analyze_motion_profile, smart_pacing_segments

BG='#0b1019'; PANEL='#142131'; CARD='#1c2c3e'; FG='#dceaf6'; CYAN='#25e2df'; BORDER='#2d4860'
TRACKS=['V3','V2','V1','A1','A2']; LABELS={'V3':'Text / Overlay','V2':'Facecam','V1':'Gameplay','A1':'Game Audio','A2':'Music'}
COLORS={'V3':'#714ba3','V2':'#256ca5','V1':'#185d98','A1':'#237e5a','A2':'#9b751f'}

def tc(t):
    frames=max(0,round(t*30));h,frames=divmod(frames,108000);m,frames=divmod(frames,1800);s,f=divmod(frames,30)
    return f'{h:02}:{m:02}:{s:02}:{f:02}'

def duration(c):return (c['end']-c['start'])/max(.01,float(c.get('speed',1.0)))

class LiveOverlay(QWidget):
    """Composite decoded video frames and timeline PNG/title overlays in one QWidget."""
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor=editor
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._drag_start=None
        self.cache={}
        self.frame_image=QImage()
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def mousePressEvent(self,event):
        c=self.editor.selected_clip()
        if event.button()==Qt.LeftButton and c and c.get('kind')=='effect' and c.get('at',0)<=self.editor.playhead<c.get('at',0)+duration(c):
            self._drag_start=(event.position(),float(c.get('overlay_x',0.)),float(c.get('overlay_y',0.)))
            event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_start is None:return super().mouseMoveEvent(event)
        c=self.editor.selected_clip()
        if c:
            point,x,y=self._drag_start
            c['overlay_x']=x+(event.position().x()-point.x())*1280/max(1,self.width())
            c['overlay_y']=y+(event.position().y()-point.y())*720/max(1,self.height())
            self.update()
        event.accept()

    def mouseReleaseEvent(self,event):
        if self._drag_start is not None:
            self._drag_start=None;self.editor.update_all();event.accept();return
        super().mouseReleaseEvent(event)

    def receive_frame(self, frame):
        # QVideoSink delivers frames on the GUI thread. Convert immediately so
        # the underlying decoder buffer can safely be reused.
        self.frame_image=frame.toImage().copy() if frame.isValid() else QImage()
        self.update()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.fillRect(self.rect(), QColor('black'))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.frame_image.isNull():
            iw=self.frame_image.width(); ih=self.frame_image.height()
            if iw and ih:
                scale=min(self.width()/iw,self.height()/ih)
                w=iw*scale; h=ih*scale
                painter.drawImage(QRectF((self.width()-w)/2,(self.height()-h)/2,w,h),self.frame_image,QRectF(self.frame_image.rect()))
        t=self.editor.playhead
        for c in self.editor.clips:
            if c.get('kind')!='effect' or not c.get('track','').startswith('V'):
                continue
            start=float(c.get('at',0)); length=duration(c)
            if not (start<=t<start+length):continue
            path=c.get('path','')
            if path not in self.cache:
                if len(self.cache)>150:self.cache.clear()
                self.cache[path]=QPixmap(path)
            pix=self.cache[path]
            if pix.isNull():continue
            alpha=max(0.,min(1.,float(c.get('opacity',1.))))
            fade=max(0.,min(float(c.get('fade',0)),length/2))
            elapsed=t-start
            if fade>0:
                alpha*=min(1.,elapsed/fade,(length-elapsed)/fade)
            if alpha<=0:continue
            # Same aspect-fit as the export compositor; transparent PNG pixels stay transparent.
            scale=min(self.width()/pix.width(),self.height()/pix.height())
            factor=max(.1,min(3.,float(c.get('overlay_scale',1.))))
            w=pix.width()*scale*factor;h=pix.height()*scale*factor
            dx=float(c.get('overlay_x',0.))*self.width()/1280
            dy=float(c.get('overlay_y',0.))*self.height()/720
            painter.setOpacity(alpha)
            painter.save();painter.translate(self.width()/2+dx,self.height()/2+dy)
            painter.rotate(float(c.get('overlay_rotation',0.)))
            painter.drawPixmap(QRectF(-w/2,-h/2,w,h),pix,QRectF(pix.rect()))
            painter.restore()
        painter.end()

class MediaLibrary(QListWidget):
    """Drag imported media by library index, without altering the original file."""
    def startDrag(self, supportedActions):
        item=self.currentItem()
        if item is None:return
        drag=QDrag(self)
        mime=QMimeData();mime.setData('application/x-fragforge-media-index',str(self.row(item)).encode('ascii'))
        drag.setMimeData(mime);drag.exec(Qt.CopyAction)

class VisualCache(QObject):
    ready=Signal(str)
    def __init__(self):
        super().__init__()
        self.frames={}
        self.waves={}
        self.inflight=set()
        self.lock=threading.Lock()
    def request(self,path,kind):
        with self.lock:
            if path in self.inflight or path in self.frames or path in self.waves:return
            self.inflight.add(path)
        threading.Thread(target=self._generate,args=(path,kind),daemon=True).start()
    def _generate(self,path,kind):
        try:
            if kind=='audio':
                cmd=[binary('ffmpeg'),'-v','error','-i',path,'-vn','-ac','1','-ar','2000','-f','s16le','-t','300','pipe:1']
                data=subprocess.run(cmd,capture_output=True,timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
                samples=struct.unpack('<'+str(len(data)//2)+'h',data[:len(data)//2*2]) if data else ()
                # 100 amplitude buckets per second; 300 seconds maximum.
                buckets=[max(abs(x) for x in samples[i:i+20])/32768 for i in range(0,len(samples),20) if samples[i:i+20]]
                self.waves[path]=buckets
            else:
                length,_=probe(path)
                count=min(32,max(1,math.ceil(length/2)))
                images=[]
                for i in range(count):
                    second=min(length-.01,i*max(2,length/count))
                    cmd=[binary('ffmpeg'),'-v','error','-ss',str(max(0,second)),'-i',path,'-frames:v','1','-vf','scale=112:64:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','mjpeg','pipe:1']
                    result=subprocess.run(cmd,capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if result.returncode==0 and result.stdout:images.append((second,result.stdout))
                self.frames[path]=images
        except Exception:
            if kind=='audio':self.waves[path]=[]
            else:self.frames[path]=[]
        finally:
            with self.lock:self.inflight.discard(path)
            self.ready.emit(path)

class Timeline(QGraphicsView):
    picked=Signal(int,float,str)
    dropped=Signal(int,float,str)
    moved=Signal(int,float,str)
    def __init__(self):
        super().__init__();self.setScene(QGraphicsScene(self));self.setMinimumHeight(280)
        self.setAcceptDrops(True);self.setDragMode(QGraphicsView.NoDrag);self.drag_index=None;self.drag_origin=None;self.drag_start_at=0.;self.drag_start_track=None;self.snap_enabled=True
        self.setBackgroundBrush(QColor('#142032'));self.setRenderHint(QPainter.Antialiasing)
        self.visual_cache=None;self.clips=[];self.selected=None;self.playhead=0;self.scale=30;self.total=30;self.playhead_line=None;self.playhead_handle=None
    def refresh(self):
        sc=self.scene();sc.clear();self.playhead_line=None;self.playhead_handle=None;w=max(1100,self.total*self.scale+180);sc.setSceneRect(0,0,w,max(340,48+len(TRACKS)*55+20))
        # The finest ruler division is 0.1 seconds. Keep labels readable
        # independently of tick spacing at every zoom level.
        step=(.1 if self.scale>=350 else .5 if self.scale>=160 else
              1 if self.scale>=75 else 5 if self.scale>=25 else
              10 if self.scale>=12 else 30)
        label_every=max(1,math.ceil(85/(step*self.scale)))
        count=min(2500,int(w/self.scale/step)+2)
        for n in range(count):
            sec=round(n*step,6)
            x=138+sec*self.scale
            major=(n%label_every==0)
            sc.addLine(x,30,x,48+len(TRACKS)*55+10 if major else 43,
                       QPen(QColor('#2b4057' if major else '#284056'),1))
            if major:
                if step<1:
                    label=f'{int(sec//60):02}:{sec%60:04.1f}'
                else:
                    label=f'{int(sec)//3600:02}:{int(sec)//60%60:02}:{int(sec)%60:02}'
                item=sc.addSimpleText(label)
                item.setBrush(QColor('#9eb2c7'))
                item.setPos(x+3,7)
        for n,track in enumerate(TRACKS):
            y=48+n*55
            sc.addRect(0,y,130,51,QPen(QColor('#30445b')),QBrush(QColor('#18263a')))
            lab=sc.addSimpleText(f'{track}  {LABELS[track]}');lab.setBrush(QColor(FG));lab.setPos(7,y+15)
            sc.addLine(130,y+52,w,y+52,QPen(QColor('#2a3c50')))
        for i,c in enumerate(self.clips):
            y=48+TRACKS.index(c['track'])*55; x=138+c['at']*self.scale; width=max(4,duration(c)*self.scale)
            rect=sc.addRect(x,y+3,width,45,QPen(QColor(CYAN if self.selected==i else '#6388a5'),2 if self.selected==i else 1),QBrush(QColor(COLORS[c['track']])))
            rect.setData(0,i)
            if self.visual_cache:
                if c['kind']=='audio':
                    wave=self.visual_cache.waves.get(c['path'])
                    if wave:
                        # Waveform is cached in 10 ms amplitude buckets.
                        stride=max(1,int(1/self.scale/.01))
                        for px in range(3,max(3,int(width)-3),max(3,int(width/800))):
                            second=c['start']+px/self.scale*float(c.get('speed',1.0))
                            k=int(second*100)
                            if k<len(wave):
                                amplitude=max(wave[k:min(len(wave),k+stride)] or [0])
                                height=max(1,amplitude*29)
                                sc.addLine(x+px,y+25-height/2,x+px,y+25+height/2,QPen(QColor('#9cf2d0'),2))
                else:
                    frames=self.visual_cache.frames.get(c['path'],[])
                    if frames and width>=38:
                        # Pick cached source frames according to clip trim and zoom.
                        for px in range(0,int(width),max(38,int(2*self.scale),int(width/32))):
                            second=c['start']+px/self.scale*float(c.get('speed',1.0))
                            frame=min(frames,key=lambda pair:abs(pair[0]-second))
                            image=QImage.fromData(frame[1])
                            if image.isNull():continue
                            thumb=QPixmap.fromImage(image).scaled( min(76,max(1,int(width-px-3))),30,Qt.KeepAspectRatio,Qt.SmoothTransformation)
                            item=sc.addPixmap(thumb);item.setPos(x+px+2,y+13);item.setZValue(1)
            name=sc.addSimpleText(Path(c['path']).name[:27]);name.setBrush(QColor('white'));name.setPos(x+5,y+4);name.setZValue(2)
            time=sc.addSimpleText(tc(duration(c)));time.setBrush(QColor('#d5e4ef'));time.setPos(x+5,y+34);time.setZValue(2)
        x=138+self.playhead*self.scale
        self.playhead_line=sc.addLine(x,25,x,48+len(TRACKS)*55+10,QPen(QColor(CYAN),2.5))
        self.playhead_handle=sc.addRect(x-4,23,8,8,QPen(QColor(CYAN)),QBrush(QColor(CYAN)))
    def move_playhead(self,seconds):
        self.playhead=seconds
        x=138+seconds*self.scale
        if self.playhead_line is not None:self.playhead_line.setLine(x,25,x,48+len(TRACKS)*55+10)
        if self.playhead_handle is not None:self.playhead_handle.setRect(x-4,23,8,8)
    def location(self,p):
        t=max(0,(p.x()-138)/self.scale)
        row=int((p.y()-48)//55)
        track=TRACKS[row] if 0<=row<len(TRACKS) else None
        return t,track
    def hit_clip(self,t,track):
        if track is None:return -1
        for i,c in reversed(list(enumerate(self.clips))):
            if c['track']==track and c['at']<=t<c['at']+duration(c):return i
        return -1
    def snapped(self,t,index=-1):
        t=max(0,t)
        if not self.snap_enabled:return round(t*30)/30
        edges=[0.,self.playhead]
        for i,c in enumerate(self.clips):
            if i!=index:edges.extend((c['at'],c['at']+duration(c)))
        closest=min(edges,key=lambda x:abs(x-t))
        if abs(closest-t)<=10/self.scale:return max(0,closest)
        return round(t*30)/30
    def mousePressEvent(self,e):
        p=self.mapToScene(e.position().toPoint());t,track=self.location(p)
        idx=self.hit_clip(t,track)
        if e.button()==Qt.LeftButton and idx>=0:
            self.drag_index=idx;self.drag_origin=t;self.drag_start_at=self.clips[idx]['at'];self.drag_start_track=track
        self.picked.emit(idx,t,track or 'V1')
        super().mousePressEvent(e)
    def mouseMoveEvent(self,e):
        if self.drag_index is not None and e.buttons() & Qt.LeftButton:
            p=self.mapToScene(e.position().toPoint());t,track=self.location(p)
            c=self.clips[self.drag_index]
            if track and (track.startswith('V')==(c['kind'] in ('video','effect'))):
                new_at=self.snapped(self.drag_start_at+t-self.drag_origin,self.drag_index)
                if abs(new_at-c['at'])>0.0001 or track!=c['track']:
                    c['at']=new_at;c['track']=track;self.refresh()
            e.accept();return
        super().mouseMoveEvent(e)
    def mouseReleaseEvent(self,e):
        if self.drag_index is not None:
            idx=self.drag_index;self.drag_index=None
            c=self.clips[idx]
            self.moved.emit(idx,c['at'],c['track'])
            e.accept();return
        super().mouseReleaseEvent(e)
    def dragEnterEvent(self,e):
        if e.mimeData().hasFormat('application/x-fragforge-media-index'):e.acceptProposedAction()
        else:super().dragEnterEvent(e)
    def dragMoveEvent(self,e):
        if e.mimeData().hasFormat('application/x-fragforge-media-index'):e.acceptProposedAction()
        else:super().dragMoveEvent(e)
    def dropEvent(self,e):
        if e.mimeData().hasFormat('application/x-fragforge-media-index'):
            try:idx=int(bytes(e.mimeData().data('application/x-fragforge-media-index')).decode('ascii'))
            except ValueError:return
            t,track=self.location(self.mapToScene(e.position().toPoint()))
            if track is not None:self.dropped.emit(idx,self.snapped(t),track)
            e.acceptProposedAction();return
        super().dropEvent(e)

class ExportWorker(QThread):
    success=Signal(str);failed=Signal(str);progress=Signal(int)
    def __init__(self,clips,path,encoder,quality,width=1280,height=720,fps=30):super().__init__();self.clips=copy.deepcopy(clips);self.path=path;self.encoder=encoder;self.quality=quality;self.width=width;self.height=height;self.fps=fps
    def run(self):
        try:export_layers(self.clips,self.path,self.encoder,self.quality,self.progress.emit,self.width,self.height,self.fps);self.success.emit(self.path)
        except Exception as exc:self.failed.emit(str(exc))

class PreviewWindow(QWidget):
    def __init__(self,restore):
        super().__init__(None,Qt.Window)
        self.restore_callback=restore
        self.allow_close=False
    def closeEvent(self,event):
        if not self.allow_close:
            event.ignore()
            self.restore_callback()
        else:
            super().closeEvent(event)

class LocalDirectorWorker(QThread):
    ready=Signal(object,str)
    failed=Signal(str)
    def __init__(self,request,model,history=None,chat_mode=False):
        super().__init__()
        self.request_text=request
        self.model=model
        self.history=history or []
        self.chat_mode=chat_mode
    def run(self):
        try:
            from local_director import make_plan,chat_reply
            if self.chat_mode:
                reply=chat_reply(self.request_text,self.model,self.history)
                plan=None
            else:
                plan,reply=make_plan(self.request_text,self.model,self.history)
            self.ready.emit(plan,reply)
        except Exception as exc:
            self.failed.emit(str(exc))

class AutoAnalysisWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)
    progress=Signal(int)
    stage=Signal(str)
    def __init__(self,path,start,end,sensitivity,long_form=False):
        super().__init__();self.path=path;self.source_start=start;self.end=end;self.sensitivity=sensitivity;self.long_form=long_form;self.cancel_event=threading.Event()
    def cancel(self):
        self.cancel_event.set()
    def run(self):
        try:
            if self.long_form:
                result=analyze_motion_profile(self.path,self.source_start,self.end,self.progress.emit,self.stage.emit,self.cancel_event)
            else:
                result=find_scene_changes(self.path,self.source_start,self.end,self.sensitivity,self.progress.emit,self.stage.emit,self.cancel_event)
            self.ready.emit(result)
        except Exception as exc:self.failed.emit(str(exc))

class VisionScanWorker(QThread):
    ready=Signal(object)
    failed=Signal(str)
    progress=Signal(int)
    def __init__(self,path,end,model,audio_enabled=True):
        super().__init__();self.path=path;self.end=end;self.model=model;self.audio_enabled=audio_enabled;self.cancel_event=threading.Event()
    def cancel(self):self.cancel_event.set()
    def run(self):
        try:
            result=vision_scan(self.path,self.end,self.model,lambda done,total:self.progress.emit(int(done*75/total)),self.cancel_event,profile=getattr(self,'profile','Balanced'))
            if self.audio_enabled:
                try:
                    audio=scan_audio(self.path,self.end,lambda pct:self.progress.emit(75+int(pct*.25)),self.cancel_event)
                    result['audio']=audio
                    result['samples']=corroborate_vision(result['samples'],audio['events'])
                except Exception as exc:
                    result['audio']={'events':[],'status':'Audio analysis unavailable: '+str(exc)}
            self.ready.emit(result)
        except Exception as exc:self.failed.emit(str(exc))

class Editor(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle(DISPLAY_NAME);self.resize(1600,940)
        self.project_path=None;self._history=[];self._history_index=-1;self._history_busy=False;self._autosave_dirty=False;self.clips=[];self.media=[];self.selected=None;self.track='V1';self.playhead=0;self.active_path=None;self.preview_start=0;self.preview_at=0;self.worker=None;self.pending_seek_ms=None;self.play_when_ready=False
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.8);self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.on_position);self.player.errorOccurred.connect(self.player_error)
        self.player.mediaStatusChanged.connect(self.on_media_status);self.player.playbackStateChanged.connect(self.on_playback_state)
        self.fullscreen_window=None
        # Each overlapping audio clip needs its own player; the video player alone
        # cannot render the soundtrack and sound-effect tracks.
        self.timeline_audio_players={}
        self.audio_sync_timer=QTimer(self)
        self.audio_sync_timer.setInterval(100)
        self.audio_sync_timer.timeout.connect(self.sync_timeline_audio)
        self.audio_sync_timer.start()
        self.sfx_preview=QSoundEffect(self);self.sfx_preview.setVolume(.65)
        self.last_preview_ui_ms=-1000
        self.build_ui();self.update_all();self.capture_history()
        self.autosave_timer=QTimer(self);self.autosave_timer.setInterval(120000)
        self.autosave_timer.timeout.connect(self.autosave_project);self.autosave_timer.start()
        self.audio_devices=QMediaDevices(self)
        self.audio_devices.audioOutputsChanged.connect(self.refresh_audio_devices)
        self.refresh_audio_devices()
        for key,fn in [('Ctrl+O',self.open_project),('Ctrl+S',lambda:self.save_project()),('Ctrl+B',self.split),('Ctrl+E',self.export_video),('Delete',self.delete),('Space',self.toggle),('Ctrl+D',self.duplicate),('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),('Ctrl+Shift+Z',self.redo),('F11',self.fullscreen_preview)]:
            shortcut=QShortcut(QKeySequence(key),self);shortcut.activated.connect(fn)
    def button(self,label,fn,accent=False):
        b=QPushButton(label);b.clicked.connect(fn)
        if accent:b.setObjectName('accent')
        return b
    def build_ui(self):
        self.setStyleSheet(f'''QMainWindow,QWidget{{background:{BG};color:{FG};font:10pt 'Segoe UI';}}
            QPushButton{{background:{CARD};border:1px solid {BORDER};border-radius:7px;padding:9px 11px;}}
            QPushButton:hover{{border:1px solid {CYAN};background:#25465a;}}
            QPushButton#accent{{background:#075b65;color:#ffffff;border:1px solid {CYAN};font-weight:700;}}
            QListWidget,QComboBox{{background:{PANEL};border:1px solid {BORDER};border-radius:7px;padding:5px;}}
            QSlider::groove:horizontal{{background:#30475d;height:5px;}}
            QSlider::handle:horizontal{{background:{CYAN};width:13px;margin:-5px 0;border-radius:6px;}}
            QSplitter::handle{{background:#28445a;}}''')
        root=QWidget();self.setCentralWidget(root);main=QVBoxLayout(root);main.setContentsMargins(8,8,8,8);main.setSpacing(8)
        header=QHBoxLayout();main.addLayout(header)
        logo=QLabel('◈  ELI STUDIO');logo.setStyleSheet(f'font-size:21px;font-weight:800;color:{CYAN};');header.addWidget(logo)
        header.addWidget(QLabel('VIDEO EDITOR · v1.0.0 · Eli'));header.addStretch()
        for name in ['Project','Edit','Effects','Sounds','Transitions','Titles','AI Tools']:
            b=self.button(name,lambda checked=False, n=name:self.open_feature(n));header.addWidget(b)
        header.addWidget(self.button('↶ Undo',lambda checked=False:self.undo()))
        header.addWidget(self.button('↷ Redo',lambda checked=False:self.redo()))
        header.addWidget(self.button('📂 Open',self.open_project));header.addWidget(self.button('↥ Export',self.export_video,True))
        top=QSplitter(Qt.Horizontal);main.addWidget(top,7)
        left=QFrame();ll=QVBoxLayout(left);ll.setContentsMargins(4,4,4,4)
        lhead=QHBoxLayout();ll.addLayout(lhead);lhead.addWidget(QLabel('📁  MEDIA LIBRARY'));lhead.addStretch();lhead.addWidget(self.button('+ Import',self.import_media,True))
        self.library=MediaLibrary();self.library.setDragEnabled(True);self.library.setDragDropMode(QAbstractItemView.DragOnly);self.library.itemDoubleClicked.connect(self.preview_library);ll.addWidget(self.library)
        ll.addWidget(self.button('− Remove Selected Media',lambda checked=False:self.remove_library_media()))
        ll.addWidget(QLabel('Drag media onto a timeline track, or double-click to preview.'))
        top.addWidget(left)
        middle=QFrame();ml=QVBoxLayout(middle);ml.setContentsMargins(3,3,3,3)
        ml.addWidget(QLabel('PROGRAM MONITOR'),alignment=Qt.AlignHCenter)
        # Decode into QVideoSink and paint the frame + all overlays in ONE
        # widget. QVideoWidget's native surface occluded transparent overlays
        # on Windows even with QStackedLayout(StackAll).
        self.monitor_host=QWidget()
        self.monitor_host.setMinimumSize(400,240)
        host_layout=QVBoxLayout(self.monitor_host)
        host_layout.setContentsMargins(0,0,0,0)
        self.live_overlay=LiveOverlay(self,self.monitor_host)
        host_layout.addWidget(self.live_overlay)
        self.video_sink=QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self.live_overlay.receive_frame)
        self.player.setVideoOutput(self.video_sink)
        ml.addWidget(self.monitor_host,1)
        self.monitor_layout=ml
        self.scrub=QSlider(Qt.Horizontal);self.scrub.setRange(0,10000);self.scrub.sliderMoved.connect(lambda n:self.seek(n/10000*max(self.total(),.001)));ml.addWidget(self.scrub)
        ctr=QHBoxLayout();ml.addLayout(ctr)
        self.time_label=QLabel('00:00:00:00 / 00:00:00:00');self.time_label.setStyleSheet(f'color:{CYAN};font-weight:700;')
        ctr.addWidget(self.time_label);ctr.addStretch()
        for label,fn in [('◀|',lambda:self.seek(self.playhead-1/30)),('◀◀',lambda:self.seek(self.playhead-1)),('▶ / ❚❚',self.toggle),('▶▶',lambda:self.seek(self.playhead+1)),('|▶',lambda:self.seek(self.playhead+1/30))]:ctr.addWidget(self.button(label,fn))
        ctr.addStretch()
        ctr.addWidget(QLabel('Audio'))
        self.volume=QSlider(Qt.Horizontal);self.volume.setFixedWidth(78);self.volume.setRange(0,100);self.volume.setValue(80)
        self.volume.valueChanged.connect(lambda v:self.sync_timeline_audio())
        ctr.addWidget(self.volume)
        self.output_choice=QComboBox();self.output_choice.setMinimumWidth(100);self.output_choice.setMaximumWidth(180)
        self.output_choice.setToolTip('Audio output device');self.output_choice.currentIndexChanged.connect(self.select_audio_device)
        ctr.addWidget(self.output_choice)
        ctr.addWidget(self.button('⛶',self.fullscreen_preview))
        tools=QHBoxLayout();ml.addLayout(tools)
        for name,fn in [('✂ Snip',self.split),('Trim',self.trim),('Clip Extract',self.extract),('Duplicate',self.duplicate),('Delete',self.delete),('Set In',self.set_in),('Set Out',self.set_out),('＋ Insert Clip',self.insert)]:
            tools.addWidget(self.button(name,fn,name in ('✂ Snip','＋ Insert Clip')))
        top.addWidget(middle)
        right=QFrame();right.setObjectName('propertiesPanel')
        right.setMinimumWidth(300)
        right.setStyleSheet(f"""
            QFrame#propertiesPanel QLabel {{font-family:'Segoe UI';font-size:14px;}}
            QFrame#propertiesPanel QComboBox,QFrame#propertiesPanel QDoubleSpinBox {{
                font-family:'Segoe UI';font-size:14px;min-height:26px;
                background:{PANEL};color:{FG};border:1px solid {BORDER};
                border-radius:6px;padding:3px 7px;
            }}
            QFrame#propertiesPanel QPushButton {{font-family:'Segoe UI';font-size:13px;min-height:24px;padding:5px 7px;}}
        """)
        panel_scroll=QScrollArea(right)
        self.properties_scroll=panel_scroll
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        panel_scroll.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Expanding)
        panel_scroll.setStyleSheet('QScrollArea {border:0;background:transparent;}')
        panel_content=QWidget()
        panel_content.setObjectName('propertiesContent')
        panel_content.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Minimum)
        panel_scroll.setWidget(panel_content)
        right_layout=QVBoxLayout(right)
        right_layout.setContentsMargins(0,0,0,0)
        right_layout.addWidget(panel_scroll)
        rl=QVBoxLayout(panel_content)
        rl.setContentsMargins(12,12,12,12)
        rl.setSpacing(12)
        rl.setSizeConstraint(QLayout.SetMinimumSize)
        def field_label(value):
            label=QLabel(value)
            label.setMinimumHeight(22)
            label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            return label

        panel_title=QLabel('PROPERTIES  /  EFFECTS  /  COLOR')
        panel_title.setStyleSheet(f'font-size:14px;font-weight:700;color:{CYAN};')
        rl.addWidget(panel_title)
        self.clip_name=QLabel('No clip selected');self.clip_name.setWordWrap(True);rl.addWidget(self.clip_name)
        rl.addSpacing(7);rl.addWidget(field_label('Target Track'))
        self.track_choice=QComboBox();self.track_choice.addItems([f'{t} — {LABELS[t]}' for t in TRACKS]);self.track_choice.setCurrentIndex(2)
        self.track_choice.currentIndexChanged.connect(lambda i:setattr(self,'track',TRACKS[i]));rl.addWidget(self.track_choice)
        rl.addSpacing(7);rl.addWidget(field_label('Clip position (seconds)'))
        self.position=QDoubleSpinBox();self.position.setRange(0,86400);self.position.setDecimals(3);self.position.valueChanged.connect(self.change_position);rl.addWidget(self.position)
        rl.addWidget(self.button('Move selected clip to target track',self.change_track))
        rl.addSpacing(7);rl.addWidget(field_label('Clip speed / time remapping'))
        self.speed_control=QDoubleSpinBox()
        self.speed_control.setRange(.1,4.0)
        self.speed_control.setDecimals(2)
        self.speed_control.setSingleStep(.1)
        self.speed_control.setSuffix(' ×')
        self.speed_control.setValue(1.0)
        self.speed_control.valueChanged.connect(self.change_speed)
        rl.addWidget(self.speed_control)
        rl.addWidget(self.button('½× Slow',lambda:self.adjust_speed(.5)))
        rl.addWidget(self.button('2× Fast',lambda:self.set_speed(2)))
        rl.addWidget(self.button('4× Fast',lambda:self.set_speed(4)))
        rl.addWidget(self.button('1× Normal',lambda:self.set_speed(1)))
        rl.addSpacing(8)
        rl.addWidget(field_label('Selected clip volume (export mix)'))
        self.clip_volume=QSlider(Qt.Horizontal)
        self.clip_volume.setRange(0,200)
        self.clip_volume.setValue(100)
        self.clip_volume.setTickInterval(25)
        self.clip_volume.setTickPosition(QSlider.TicksBelow)
        self.clip_volume.setToolTip('0% mute, 100% original volume, 200% boost')
        self.clip_volume.valueChanged.connect(self.change_clip_volume)
        rl.addWidget(self.clip_volume)
        self.clip_volume_label=QLabel('100% — Original')
        rl.addWidget(self.clip_volume_label)
        rl.addWidget(self.button('Mute clip',lambda:self.set_clip_volume(0)))
        rl.addWidget(self.button('Reset to 100%',lambda:self.set_clip_volume(100)))

        for name in ['Transform','Audio','Crop','Chroma Key']:
            rl.addWidget(self.button(name+'  ▸',lambda checked=False, n=name:self.info(n)))
        rl.addSpacing(8)
        rl.addWidget(field_label('Selected clip effects'))
        self.effect_choice=QComboBox();self.effect_choice.addItems(['None','Grayscale','Warm','Cool','High Contrast'])
        self.effect_choice.currentIndexChanged.connect(self.change_effect)
        rl.addWidget(self.effect_choice)
        rl.addWidget(field_label('Fade transition duration (seconds)'))
        self.fade_control=QDoubleSpinBox();self.fade_control.setRange(0,5);self.fade_control.setSingleStep(.25);self.fade_control.setDecimals(2)
        self.fade_control.valueChanged.connect(self.change_fade)
        rl.addWidget(self.fade_control)
        rl.addWidget(self.button('Fade In + Out',lambda:self.apply_fade(0.5)))
        rl.addWidget(self.button('Remove Fades',lambda:self.apply_fade(0)))
        rl.addSpacing(8)
        rl.addWidget(field_label('Overlay visibility / opacity (V3 effects)'))
        self.overlay_opacity=QSlider(Qt.Horizontal)
        self.overlay_opacity.setRange(0,100);self.overlay_opacity.setValue(100)
        self.overlay_opacity.setTickInterval(25);self.overlay_opacity.setTickPosition(QSlider.TicksBelow)
        self.overlay_opacity.setToolTip('0% invisible, 100% fully visible; applied to exported video')
        self.overlay_opacity.valueChanged.connect(self.change_overlay_opacity)
        rl.addWidget(self.overlay_opacity)
        self.overlay_opacity_label=QLabel('100% — Fully visible')
        rl.addWidget(self.overlay_opacity_label)
        rl.addWidget(field_label('Overlay transform — X / Y position (pixels)'))
        self.overlay_x=QDoubleSpinBox();self.overlay_x.setRange(-1280,1280);self.overlay_x.setSingleStep(10)
        self.overlay_y=QDoubleSpinBox();self.overlay_y.setRange(-720,720);self.overlay_y.setSingleStep(10)
        rl.addWidget(self.overlay_x);rl.addWidget(self.overlay_y)
        rl.addWidget(field_label('Overlay size (percent)'))
        self.overlay_scale=QDoubleSpinBox();self.overlay_scale.setRange(10,300);self.overlay_scale.setSuffix(' %');self.overlay_scale.setValue(100)
        rl.addWidget(self.overlay_scale)
        rl.addWidget(field_label('Overlay rotation (degrees)'))
        self.overlay_rotation=QDoubleSpinBox();self.overlay_rotation.setRange(-180,180);self.overlay_rotation.setSuffix(' °')
        rl.addWidget(self.overlay_rotation)
        for field,key,divisor in [(self.overlay_x,'overlay_x',1),(self.overlay_y,'overlay_y',1),(self.overlay_scale,'overlay_scale',100),(self.overlay_rotation,'overlay_rotation',1)]:
            field.valueChanged.connect(lambda v,k=key,d=divisor:self.set_overlay_transform(k,v/d))
        rl.addWidget(self.button('Reset overlay transform',lambda checked=False:self.reset_overlay_transform()))
        rl.addWidget(field_label('Music ducking (reduce music beneath gameplay)'))
        self.music_duck=QCheckBox('Duck this music clip by 50%')
        self.music_duck.toggled.connect(self.change_music_duck);rl.addWidget(self.music_duck)
        rl.addStretch()
        # Wheel movement over an inactive Properties control scrolls the panel,
        # rather than accidentally modifying clip speed, volume, opacity, etc.
        # Clicking a control arms its wheel adjustment until it loses focus.
        for control_type in (QSlider,QDoubleSpinBox,QComboBox):
            for control in panel_content.findChildren(control_type):
                control.setProperty('fragforge_wheel_armed',False)
                control.installEventFilter(self)
        panel_content.adjustSize()
        top.addWidget(right);top.setSizes([250,950,330])
        timeline_top=QHBoxLayout();main.addLayout(timeline_top)
        timeline_top.addWidget(self.button('＋ Add Sound Track',self.add_track));timeline_top.addWidget(QLabel('Drag clips to move • drop media to insert'))
        self.snap_checkbox=QCheckBox('Snap');self.snap_checkbox.setChecked(True);timeline_top.addWidget(self.snap_checkbox)
        timeline_top.addStretch();self.timeline_time=QLabel('00:00:00:00 / 00:00:00:00');self.timeline_time.setStyleSheet(f'color:{CYAN};font-size:15px;font-weight:700;');timeline_top.addWidget(self.timeline_time);timeline_top.addStretch()
        timeline_top.addWidget(self.button('− Zoom',lambda:self.zoom(.75)));timeline_top.addWidget(self.button('＋ Zoom',lambda:self.zoom(1.33)))
        timeline_top.addWidget(self.button('🔎 Frame Zoom',self.frame_zoom))
        timeline_top.addWidget(self.button('Fit',self.fit_timeline))
        self.visual_cache=VisualCache()
        self.timeline=Timeline();self.timeline.visual_cache=self.visual_cache
        self.visual_cache.ready.connect(self.on_visual_ready)
        self.timeline.picked.connect(self.timeline_clicked);self.timeline.dropped.connect(self.timeline_dropped);self.timeline.moved.connect(self.timeline_moved);self.snap_checkbox.toggled.connect(self.set_snap);main.addWidget(self.timeline,5)
        self.note=QLabel('Ready  •  Drag media from the library to the timeline; drag clips to reposition');main.addWidget(self.note)
    def eventFilter(self,obj,event):
        if isinstance(obj,(QSlider,QDoubleSpinBox,QComboBox)) and hasattr(self,'properties_scroll'):
            if event.type()==QEvent.MouseButtonPress:
                obj.setProperty('fragforge_wheel_armed',True)
            elif event.type()==QEvent.FocusOut:
                obj.setProperty('fragforge_wheel_armed',False)
            elif event.type()==QEvent.Wheel and not obj.property('fragforge_wheel_armed'):
                # Explicitly scroll the parent panel so behavior is consistent
                # across Qt/Windows versions and different control types.
                bar=self.properties_scroll.verticalScrollBar()
                delta=event.angleDelta().y()
                if delta:
                    bar.setValue(bar.value()-round(delta/120)*max(20,bar.singleStep()*3))
                elif event.pixelDelta().y():
                    bar.setValue(bar.value()-event.pixelDelta().y())
                event.accept()
                return True
        return super().eventFilter(obj,event)

    def add_text_overlay(self):
        value,ok=QInputDialog.getText(self,'Add Text Overlay','Text to show on video:')
        if not ok or not value.strip():return
        value=value.strip()[:160]
        folder=Path.home()/'FragForge'/'titles';folder.mkdir(parents=True,exist_ok=True)
        import uuid
        path=folder/('title-'+uuid.uuid4().hex[:12]+'.png')
        img=QImage(1280,720,QImage.Format_ARGB32);img.fill(Qt.transparent)
        painter=QPainter(img);painter.setRenderHint(QPainter.Antialiasing)
        font=QFont('Arial',72,QFont.Bold);painter.setFont(font)
        painter.setPen(QPen(QColor('#101010'),9,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        from PySide6.QtGui import QPainterPath
        lines=value.splitlines()[:3]
        for j,line in enumerate(lines):
            metrics=painter.fontMetrics();line=line[:60]
            x=(1280-metrics.horizontalAdvance(line))/2;y=360+(j-(len(lines)-1)/2)*90
            pathtext=QPainterPath();pathtext.addText(x,y,font,line)
            painter.drawPath(pathtext)
            painter.fillPath(pathtext,QColor('white'))
        painter.end();img.save(str(path),'PNG')
        clip=dict(path=str(path),start=0.,end=3.,at=self.playhead,track='V3',audio=False,kind='effect',speed=1.,effect='None',fade=.15,opacity=1.,label=value)
        self.clips.append(clip);self.selected=len(self.clips)-1;self.update_all()
        self.note.setText('Text overlay added to V3 — visible in preview and export')

    def open_feature(self,feature):
        if feature=='Project':
            options=['Save Project','Save Project As','Open Project','Recover Autosave','New Project']
            value,ok=QInputDialog.getItem(self,'Project', 'Choose an action:',options,0,False)
            if ok:
                {'Save Project':lambda:self.save_project(),'Save Project As':lambda:self.save_project(True),
                 'Open Project':self.open_project,'Recover Autosave':self.recover_autosave,'New Project':self.new_project}[value]()
        elif feature=='Effects':
            try:
                self.open_effect_library()
            except Exception as exc:
                import traceback
                QMessageBox.critical(self,'Effects Library Error',
                    f'Could not open the effects library:\\n{exc}\\n\\n'+traceback.format_exc()[-1800:])
        elif feature=='Sounds':
            self.open_sound_library()
        elif feature=='Titles':
            self.add_text_overlay()
        elif feature=='Transitions':
            self.open_transitions()
        elif feature=='AI Tools':
            self.open_ai_assistant()
        else:self.info(feature)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._position_director_peek()

    def _position_director_peek(self):
        peek=getattr(self,'_director_peek',None)
        if peek is not None:
            # The edge tab is on the MAIN EDITOR, not inside the director dialog.
            peek.move(max(0,self.width()-peek.width()),max(85,self.height()//2-peek.height()//2))
            peek.raise_()

    def open_ai_assistant(self):
        """Show the entire Eli chat window; hiding leaves only a half-head tab."""
        from assistant_engine import interpret_request,describe_plan,task_queue,task_report
        from local_director import available_models,DEFAULT_MODEL

        old=getattr(self,'_director_dialog',None)
        if old is not None:
            old.show()
            old.raise_()
            old.activateWindow()
            if getattr(self,'_director_peek',None):
                self._director_peek.hide()
            return

        dlg=QDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose,False)
        self._director_dialog=dlg
        dlg.setWindowTitle('Eli — '+DISPLAY_NAME)
        dlg.resize(980,680)
        dlg.setMinimumSize(760,540)
        dlg.setStyleSheet('QDialog {background:#0b1420; color:#e7f2fb;} QLabel {color:#dceaf6;} QPlainTextEdit {background:#111e2d; border:1px solid #294157; border-radius:9px; padding:9px; color:#f1f7fb;}')
        outer=QHBoxLayout(dlg)
        outer.setContentsMargins(18,18,18,18)
        outer.setSpacing(18)
        left=QVBoxLayout()
        outer.addLayout(left,2)
        avatar=QPushButton()
        avatar.setToolTip('Click Eli to hide this window')
        avatar.setStyleSheet('QPushButton {border:0; background:transparent; padding:0;}')
        avatar_path=os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(__file__)),'assets','mr_director.png')
        character=QPixmap(avatar_path)
        if not character.isNull():
            avatar.setIcon(QIcon(character))
            avatar.setIconSize(character.size().scaled(300,375,Qt.KeepAspectRatio))
        else:
            avatar.setText('Eli')
        avatar.setFixedHeight(380)
        left.addWidget(avatar)
        reply_label=QLabel('Hey! I’m Eli. What are we creating today?')
        reply_label.setWordWrap(True)
        reply_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        reply_label.setStyleSheet('QLabel {background:#132838; border-left:3px solid #25e2df; border-radius:8px; padding:14px; font-size:14px;}')
        reply_label.setMinimumHeight(85)
        # Keep one readable chat history instead of duplicate speech bubbles.
        reply_label.hide()
        left.addStretch(1)

        # Independent edge tab: remains visible even after the entire chat window hides.
        peek=QPushButton(self)
        self._director_peek=peek
        peek.setToolTip('Eli is hiding — click his head to reopen the chat')
        peek.setFixedSize(82,150)
        peek.setStyleSheet('QPushButton {background:#10252c; border:2px solid #00d6dc; border-top-left-radius:16px; border-bottom-left-radius:16px; padding:0;}')
        head_path=os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(__file__)),'assets','mr_director_head.png')
        head=QPixmap(head_path)
        if not head.isNull():
            # Show only the left half of his face, as if he is peeking from the right edge.
            half=head.copy(0,0,max(1,head.width()//2),head.height())
            peek.setIcon(QIcon(half))
            peek.setIconSize(half.size().scaled(77,135,Qt.KeepAspectRatio))
        else:
            peek.setText('👀')
        peek.hide()
        self._position_director_peek()

        def hide_director():
            # Hide only on an explicit avatar click, never on Send/Prepare Edit.
            if not dlg.isVisible():
                return
            dlg.hide()
            self._position_director_peek()
            peek.show()
            peek.raise_()

        def show_director():
            peek.hide()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

        avatar.clicked.connect(hide_director)
        peek.clicked.connect(show_director)

        assistant_area=QVBoxLayout()
        outer.addLayout(assistant_area,3)
        assistant_tabs=QTabWidget(dlg)
        assistant_tabs.setStyleSheet("QTabBar::tab { background: #352529; color: #eadadd; padding: 8px 14px; } QTabBar::tab:selected { background: #74404a; color: white; } QTabBar::tab:hover { background: #59323a; }")
        assistant_area.addWidget(assistant_tabs)
        director_page=QWidget();right=QVBoxLayout(director_page);right.setSpacing(9)
        assistant_tabs.addTab(director_page,'Eli')
        preview_page=QWidget();preview_layout=QVBoxLayout(preview_page)
        preview_layout.addWidget(QLabel('Review proposed edits before applying changes.'))
        preview_open=self.button('Open Edit Preview',lambda checked=False:self.open_auto_editor(from_assistant=True))
        preview_layout.addWidget(preview_open)
        preview_layout.addStretch(1)
        assistant_tabs.addTab(preview_page,'Preview Edit')
        ai_mode_page=QWidget();mode_layout=QVBoxLayout(ai_mode_page)
        mode_layout.addWidget(QLabel('AI performance — memory budgets are targets, not hard caps.'))
        performance_mode=QComboBox();performance_mode.addItems(['Eco','Balanced','Accelerated'])
        performance_mode.setCurrentText(getattr(self,'_ai_performance_mode','Accelerated'))
        mode_layout.addWidget(performance_mode)
        profile_description=QLabel();profile_description.setWordWrap(True)
        mode_layout.addWidget(profile_description)
        def update_profile():
            name=performance_mode.currentText()
            self._ai_performance_mode=name
            profile=PROFILES[name]
            profile_description.setText(f'{name}: target {profile["budget_gb"]} GB Ollama RAM, {profile["max_frames"]} sampled frames, context {profile["num_ctx"]}. Actual RAM may exceed this target.')
        performance_mode.currentTextChanged.connect(lambda _value:update_profile())
        update_profile()
        refresh_status=QLabel('Refresh AI unloads Eli models; they reload on the next request.')
        refresh_status.setWordWrap(True);mode_layout.addWidget(refresh_status)
        refresh_button=self.button('Refresh AI',lambda:None)
        mode_layout.addWidget(refresh_button)
        def refresh_ai():
            if ai_job_busy() or any(w is not None and w.isRunning() for w in (getattr(self,'_auto_analysis_worker',None),getattr(self,'_vision_scan_worker',None))):
                QMessageBox.warning(dlg,'AI busy','Cancel the current analysis and wait for it to finish before refreshing AI.')
                return
            refresh_button.setEnabled(False);refresh_status.setText('Releasing models…')
            from ollama_memory import refresh_models
            class RefreshWorker(QThread):
                ready=Signal(object)
                def run(self):
                    try:self.ready.emit(refresh_models(['qwen3-vl:2b','qwen3:4b']))
                    except Exception as exc:self.ready.emit(str(exc))
            worker=RefreshWorker(dlg);self._refresh_ai_worker=worker
            def finished(result):
                refresh_button.setEnabled(True)
                if not isinstance(result,str):
                    state['history'].clear()
                    state['requests'].clear()
                    state['plan']=None
                    state['plan_text']=''
                    state['worker']=None
                    chat.setPlainText('Eli: Fresh conversation. Your video and timeline edits are preserved.')
                    request.clear()
                    preview.clear()
                    reply_label.setText('Ready to work on the current V1 edit.')
                if isinstance(result,str):refresh_status.setText('Refresh failed: '+result)
                else:
                    requested,loaded=result
                    refresh_status.setText('AI refreshed. Models still loaded: '+(', '.join(loaded) if loaded else 'none')+'. Models reload on next request.')
                worker.deleteLater()
            worker.ready.connect(finished);worker.start()
        refresh_button.clicked.connect(lambda checked=False:refresh_ai())
        mode_layout.addStretch(1)
        assistant_tabs.addTab(ai_mode_page,'AI Mode')
        heading=QLabel('ELI  •  YOUR AI EDITING PARTNER')
        heading.setStyleSheet('font-size:17px; font-weight:600; color:#25e2df;')
        right.addWidget(heading)
        row=QHBoxLayout();right.addLayout(row)
        model=QComboBox();model.addItem(DEFAULT_MODEL);row.addWidget(model,1)
        check=self.button('Connect',lambda checked=False:connect());row.addWidget(check)
        install=self.button('Install Free AI',lambda checked=False:install_local_ai());row.addWidget(install)
        status=QLabel('Checking local Ollama…');status.setWordWrap(True);right.addWidget(status)
        chat=QPlainTextEdit();chat.setReadOnly(True)
        chat.setPlainText('Eli: Welcome to FragForge!')
        right.addWidget(chat,4)
        request=QPlainTextEdit()
        request.setPlaceholderText('Ask me a question, or describe the video edit you want…')
        request.setPlainText(getattr(self,'_assistant_request',''))
        request.setMaximumHeight(95)
        right.addWidget(request)
        buttons=QHBoxLayout();right.addLayout(buttons)
        send=self.button('Send Message',lambda checked=False:send_request(),True)
        launch=self.button('Prepare Edit',lambda checked=False:run_edit())
        buttons.addWidget(send,2);buttons.addWidget(launch,1)
        details_toggle=self.button('Show editing details',lambda checked=False:toggle_details())
        right.addWidget(details_toggle)
        preview=QPlainTextEdit();preview.setReadOnly(True);preview.setMaximumHeight(160)
        preview.hide();right.addWidget(preview)
        def toggle_details():
            preview.setVisible(not preview.isVisible())
            details_toggle.setText('Hide editing details' if preview.isVisible() else 'Show editing details')
        state={'plan':None,'worker':None,'models':[],'requests':[],'history':[],'plan_text':''}
        def install_local_ai():
            answer=QMessageBox.question(dlg,'Install Free Local AI',
                'Install Ollama and download the Qwen3 4B model?\n\n'
                'This requires internet access, several GB of disk space and may take several minutes. '
                'The installer uses Windows Package Manager (winget). No paid API is required.\n\n'
                'Proceed?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:return
            setup=os.path.join(os.path.dirname(__file__),'Install-FragForge-LocalAI.ps1')
            if not os.path.isfile(setup):
                setup=os.path.join(os.path.dirname(sys.executable),'Install-FragForge-LocalAI.ps1')
            if not os.path.isfile(setup):
                QMessageBox.warning(dlg,'Setup not found','Install-FragForge-LocalAI.ps1 is missing from the application folder.')
                return
            try:
                subprocess.Popen(['powershell.exe','-NoProfile','-NoExit','-ExecutionPolicy','Bypass',
                                  '-File',setup],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
                status.setText('Free AI setup launched in PowerShell. Click Connect when it finishes.')
                reply_label.setText('Installer opened. Connect when setup finishes.')
            except Exception as exc:
                QMessageBox.warning(dlg,'Setup launch failed',str(exc))

        def connect():
            try:
                names=available_models()
                state['models']=names
                model.clear()
                model.addItems(names or [DEFAULT_MODEL])
                if names:
                    status.setText('● Ollama connected — '+str(len(names))+' installed model(s)')
                    reply_label.setText("I’m connected! What are we creating today?")
                else:
                    status.setText('Ollama connected, but no models installed. Run: ollama pull qwen3:4b')
            except Exception:
                status.setText('Ollama unavailable — offline planner available. Install Ollama and pull qwen3:4b.')
        def show_plan(plan,reply):
            state['plan']=plan
            state['plan_text']=self._assistant_request
            preview.setPlainText(describe_plan(plan))
            chat.appendPlainText('Eli: '+reply+'\n')
            reply_label.setText(reply)
            launch.setEnabled(True)
            send.setEnabled(True)
        def send_request():
            value=request.toPlainText().strip()
            if not value:
                QMessageBox.information(dlg,'Eli','Tell me what you want edited first.');return
            self._assistant_request=value
            chat.appendPlainText('You: '+value)
            # Send Message is conversation-only. Never start analysis here.
            # Remember edit instructions so Prepare Edit can act on them later.
            edit_intent=bool(re.search(r'\b(edit|montage|highlight|clip|cut|trim|fade|transition|music|rock|combat|kill|video|gameplay)\b',value,re.I))
            if edit_intent:
                state['plan']=interpret_request(value)
                state['plan_text']=value
                preview.setPlainText(describe_plan(state['plan']))
                launch.setEnabled(True)
            chat_mode=True
            # Preserve the last valid edit plan while processing follow-up chat.
            # A failed AI response must not disable Prepare Edit.
            send.setEnabled(False)
            if not state['models']:
                if chat_mode:
                    chat.appendPlainText('Eli: My local AI is offline. Your edit instructions are saved; click Prepare Edit to start, or Connect to chat.\n')
                    reply_label.setText('Connect my local AI so we can chat!')
                    send.setEnabled(True)
                else:
                    show_plan(interpret_request(value),'My AI is offline; I prepared a basic edit plan.')
                return
            if not acquire_ai_job('chat'):
                chat.appendPlainText('Eli: Another AI job is running. Wait for it to finish.\n')
                send.setEnabled(True)
                return
            worker=LocalDirectorWorker(value,DEFAULT_MODEL,state['history'][-6:],chat_mode)
            state['worker']=worker
            self._local_director_worker=worker
            status.setText('● Eli is thinking… Please wait.')
            def ready(plan,reply):
                release_ai_job('chat')
                status.setText('● Local AI ready')
                if plan is None:
                    chat.appendPlainText('Eli: '+reply+'\n')
                    reply_label.setText(reply)
                    send.setEnabled(True)
                else:
                    show_plan(plan,reply)
                state['history'].extend(['You: '+value,'Eli: '+reply])
            def failed(error):
                release_ai_job('chat')
                status.setText('Local AI request failed — error shown in chat. You can retry.')
                if chat_mode:
                    chat.appendPlainText('Eli: I could not generate a reply. Your instructions are saved; Prepare Edit is still available.\n')
                    reply_label.setText('I hit a connection issue. Please try again.')
                    send.setEnabled(True)
                else:
                    show_plan(interpret_request(value),'Local AI failed. This is an OFFLINE suggestion only; no edit has been applied.')
                chat.appendPlainText('Local model error: '+error[:1200])
            worker.ready.connect(ready)
            worker.failed.connect(failed)
            worker.finished.connect(worker.deleteLater)
            worker.start()
        def reset():
            state['plan']=None
            preview.clear()
            launch.setEnabled(False)
            request.setFocus()
        # Keep Prepare Edit available for the last confirmed request, even if the
        # user types a follow-up such as 'let's do it'.
        def run_edit():
            # Prepare Edit must work without waiting for Ollama or a valid JSON reply.
            # Re-parse the current request if it contains new edit instructions.
            value=request.toPlainText().strip()
            edit_words=r'\b(edit|cut|trim|montage|highlight|fade|transition|speed|slow|intro|caption|subtitle|sound|music|effect|remove|clip|render|export|loot|kill|zombie|walking|driving|short|video)\b'
            if value and re.search(edit_words,value,re.I):
                self._assistant_request=value
                state['plan']=interpret_request(value)
                state['plan_text']=value
            if not state['plan']:
                QMessageBox.information(dlg,'Prepare Edit','Describe the edit first, then click Prepare Edit.')
                return
            self._assistant_pending_plan=state['plan']
            self._assistant_pending_tasks=list(state['requests'])
            # Keep the assistant window open while the preview is created.
            # Keep it alive and visible; the edit preview is a separate modal dialog.
            chat.appendPlainText('Eli: Preparing your edit now. Your chat remains available.\n')
            status.setText('● Preparing edit preview…')
            send.setEnabled(False)
            launch.setEnabled(False)
            def open_requested_preview():
                try:
                    self.open_auto_editor(auto_analyze=True,from_assistant=True)
                    assistant_tabs.setCurrentWidget(preview_page)
                except Exception as exc:
                    chat.appendPlainText('Eli: Unable to open edit preview: '+str(exc)+'\n')
                    QMessageBox.warning(dlg,'Edit preview failed',str(exc))
                finally:
                    send.setEnabled(True)
                    launch.setEnabled(True)
                    status.setText('● Ready')
                    if dlg.isVisible():
                        dlg.raise_()
                        dlg.activateWindow()
            QTimer.singleShot(0,open_requested_preview)
        QTimer.singleShot(100,connect)
        dlg.show()

    def open_auto_editor(self, auto_analyze=False, from_assistant=False):
        """Non-destructive, user-approved offline highlight suggestions."""
        videos=[c for c in self.clips if c.get('kind')=='video' and c.get('track')=='V1']
        if not videos:
            QMessageBox.information(self,'Auto Edit','Place a gameplay video on V1 first.');return
        source=videos[0]
        # Parent the assistant's working window to its chat, not to the main editor.
        # A modeless child avoids a nested event loop that previously blocked the chat.
        parent_dialog=getattr(self,'_director_dialog',None) if from_assistant else None
        dlg=QDialog(parent_dialog if parent_dialog is not None else self)
        dlg.setWindowTitle('Eli Studio — Eli is Working');dlg.resize(760,530)
        if from_assistant:
            dlg.setWindowModality(Qt.NonModal)
            dlg.setAttribute(Qt.WA_DeleteOnClose,True)
            self._director_working_dialog=dlg
        original_reject=dlg.reject
        def safe_reject():
            if any(w is not None and w.isRunning() for w in (getattr(self,'_auto_analysis_worker',None),getattr(self,'_vision_scan_worker',None))):
                QMessageBox.information(dlg,'Analysis running','Cancel analysis and wait for the worker to finish before closing this preview.')
                return
            original_reject()
        dlg.reject=safe_reject
        dlg.setMinimumSize(610,420)
        screen=QApplication.primaryScreen()
        if screen:
            area=screen.availableGeometry()
            dlg.resize(min(760,max(610,area.width()-100)),min(530,max(420,area.height()-120)))
        layout=QVBoxLayout(dlg)
        layout.setContentsMargins(12,10,12,10)
        layout.setSpacing(6)
        scroll=QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        form=QWidget()
        form_layout=QVBoxLayout(form)
        form_layout.setSpacing(4)
        form_layout.setContentsMargins(4,4,4,4)
        editor_tabs=QTabWidget(dlg)
        editor_tabs.setStyleSheet("QTabBar::tab { background: #352529; color: #eadadd; padding: 8px 14px; } QTabBar::tab:selected { background: #74404a; color: white; }")
        work_page=QWidget(dlg)
        work_layout=QVBoxLayout(work_page)
        work_layout.setAlignment(Qt.AlignCenter)
        # Native Qt animated GIF: lightweight and independent of Ollama workers.
        working_art=QLabel('ELI')
        working_art.setAlignment(Qt.AlignCenter)
        working_art.setStyleSheet('font-size:20px; color:#25e2df; font-weight:700; background:transparent;')
        work_layout.addWidget(working_art)
        avatar_picture=QLabel()
        avatar_picture.setAlignment(Qt.AlignCenter)
        avatar_picture.setStyleSheet('background:transparent; border:none;')
        avatar_picture.setMinimumHeight(250)
        avatar_file=Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))/'assets'/'editor_x_working.gif'
        if avatar_file.is_file():
            editor_movie=QMovie(str(avatar_file), parent=dlg)
            editor_movie.setCacheMode(QMovie.CacheAll)
            editor_movie.setScaledSize(QSize(330,327))
            avatar_picture.setMovie(editor_movie)
            editor_movie.start()
            dlg._editor_x_movie=editor_movie
        else:
            avatar_file=Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))/'assets'/'mr_director.png'
            if avatar_file.is_file():
                avatar_picture.setPixmap(QPixmap(str(avatar_file)).scaled(300,300,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        work_layout.addWidget(avatar_picture, 0, Qt.AlignHCenter)
        work_message=QLabel('Please wait, I am busy working on your video!')
        work_message.setAlignment(Qt.AlignCenter)
        work_message.setWordWrap(True)
        work_message.setStyleSheet('font-size:17px; color:#e5f5ff;')
        work_layout.addWidget(work_message)
        work_stage=QLabel('Preparing analysis…')
        work_stage.setAlignment(Qt.AlignCenter)
        work_layout.addWidget(work_stage)
        work_bar=QProgressBar()
        work_bar.setRange(0,100)
        work_bar.setValue(0)
        work_bar.setFormat('%p%')
        work_layout.addWidget(work_bar)
        work_layout.addStretch(1)
        editor_tabs.addTab(work_page,'Eli Working')
        editor_tabs.addTab(scroll,'Edit Details')
        layout.addWidget(editor_tabs,1)
        scroll.setWidget(form)
        # All settings/results live inside the scroll pane; buttons stay pinned.
        settings_layout=form_layout
        def collapsible_section(title, expanded=False):
            header=QToolButton(form)
            header.setText(title)
            header.setCheckable(True)
            header.setChecked(expanded)
            header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            header.setStyleSheet('QToolButton { text-align:left; padding:10px; font-weight:600; background:#17283a; border:1px solid #30485c; border-radius:5px; }')
            content=QWidget(form)
            body=QVBoxLayout(content)
            body.setContentsMargins(10,8,10,10)
            body.setSpacing(5)
            content.setVisible(expanded)
            def toggle(opened):
                content.setVisible(opened)
                header.setArrowType(Qt.DownArrow if opened else Qt.RightArrow)
            header.toggled.connect(toggle)
            form_layout.addWidget(header)
            form_layout.addWidget(content)
            return body
        settings_layout=collapsible_section('01  Edit length & playback', True)
        settings_layout.addWidget(QLabel('Analyze scene changes and suggest a gaming montage or full-length edit.\n'
                                'Offline visual activity detection: no reliable kill, looting, or walking recognition yet.'))
        settings_layout.addWidget(QLabel('Source: '+Path(source['path']).name))
        mode=QComboBox();mode.addItems(['15-second highlight','Custom highlight montage','Full-length edit (up to 1 hour)'])
        settings_layout.addWidget(QLabel('Edit duration preset'));settings_layout.addWidget(mode)
        count=QComboBox();count.addItems(['3','5','8','12']);count.setCurrentText('5')
        length=QDoubleSpinBox();length.setRange(1.,15.);length.setValue(4.);length.setSuffix(' sec per highlight')
        sensitivity=QDoubleSpinBox();sensitivity.setRange(.1,.65);sensitivity.setSingleStep(.05);sensitivity.setValue(.24)
        effects=QCheckBox('Insert visual effects on V3 at candidate cuts');effects.setChecked(True)
        sounds=QCheckBox('Insert automatic sound cues (disabled: no verified audio events)');sounds.setChecked(False);sounds.setEnabled(False)
        speedup=QCheckBox('Speed up low-activity sections (2×, minimum 12 seconds)');speedup.setChecked(True)
        replace=QCheckBox('Replace current timeline with suggested montage (Undo available)')
        replace.setChecked(False)
        target_duration=QDoubleSpinBox();target_duration.setRange(0,10800);target_duration.setDecimals(0);target_duration.setSuffix(' seconds (0 = automatic)');target_duration.setValue(0)
        intro_duration=QDoubleSpinBox();intro_duration.setRange(0,20);intro_duration.setDecimals(0);intro_duration.setSuffix(' seconds');intro_duration.setValue(0)
        settings_layout.addWidget(QLabel('Target total output duration'));settings_layout.addWidget(target_duration)
        playback_speed=QDoubleSpinBox();playback_speed.setRange(.25,8.);playback_speed.setSingleStep(.25);playback_speed.setDecimals(2);playback_speed.setValue(1.5);playback_speed.setSuffix('×')
        settings_layout.addWidget(QLabel('Montage playback speed'));settings_layout.addWidget(playback_speed)
        settings_layout=collapsible_section('02  Music & sound')
        music_path=QLineEdit();music_path.setReadOnly(True);music_button=self.button('Choose music file…',lambda:None)
        music_row=QHBoxLayout();music_row.addWidget(music_path,1);music_row.addWidget(music_button);settings_layout.addLayout(music_row)
        def choose_music():
            path,_=QFileDialog.getOpenFileName(dlg,'Choose background music',str(Path.home()),'Audio (*.mp3 *.wav *.flac *.m4a *.ogg *.aac)')
            if path:music_path.setText(path)
        music_button.clicked.connect(lambda checked=False:choose_music())
        # User-supplied, locally stored music; no unlicensed tracks bundled.
        library_button=self.button('Change music library folder…',lambda:None)
        settings_layout.addWidget(library_button)
        music_library_status=QLabel('Music library: loading included tracks…')
        settings_layout.addWidget(music_library_status)
        music_library_tracks=[]
        # Bundled music is discovered relative to source or PyInstaller _MEIPASS.
        import sys
        _roots=[Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent)),Path(__file__).resolve().parent]
        _included=next((r/'music_library' for r in _roots if (r/'music_library').is_dir()),None)
        if _included:
            music_library_tracks.extend(x['path'] for x in scan_library(_included,limit=100))
            music_library_status.setText(f'Included music library: {len(music_library_tracks)} versions (50 songs)')
        music_request=QLineEdit();music_request.setPlaceholderText('Song title or genre + track number + full/loop (e.g. dark survival track 4 loop)')
        settings_layout.addWidget(music_request)
        music_selection=QLabel('Eli: no track selected')
        settings_layout.addWidget(music_selection)
        def select_requested_music():
            if not music_library_tracks:
                QMessageBox.information(dlg,'Music library','Choose a music library folder first.');return
            choice=choose_track(music_library_tracks,music_request.text() or str((pending or {}).get('original','')))
            if choice:
                music_path.setText(str(choice['path']))
                music_selection.setText(f'Eli selected: {choice["title"]} · {choice["genre"]} · {choice["reason"]}')
            else:
                QMessageBox.information(dlg,'Music not found','No matching song/version. Choose an available title or genre + track number.')
        settings_layout.addWidget(self.button('Eli — Select requested track',lambda checked=False:select_requested_music()))
        def choose_music_library():
            folder=QFileDialog.getExistingDirectory(dlg,'Choose licensed music folder',str(Path.home()))
            if not folder:return
            extensions={'.mp3','.wav','.flac','.m4a','.ogg','.aac'}
            tracks=[item['path'] for item in scan_library(folder,limit=100)]
            music_library_tracks.clear();music_library_tracks.extend(tracks)
            music_library_status.setText(f'Music library: {len(tracks)} tracks found (maximum 100)')
            if tracks and not music_path.text().strip():
                choice=choose_track(tracks,music_request.text() or str((pending or {}).get('music','')))
                if choice:
                    music_path.setText(str(choice['path']))
                    music_selection.setText(f'Eli selected: {choice["title"]} · {choice["genre"]}')
        library_button.clicked.connect(lambda checked=False:choose_music_library())

        settings_layout=collapsible_section('03  Combat detection & review', True)
        settings_layout.addWidget(QLabel('Confirmed combat moments (source timestamps, comma-separated)'))
        combat_markers=QLineEdit()
        combat_markers.setPlaceholderText('Example: 00:04:32, 00:12:08, 00:23:15')
        combat_markers.setToolTip('Enter source video timestamps where you saw actual combat. These are user-confirmed, not AI detected.')
        settings_layout.addWidget(combat_markers)
        allow_unverified=QCheckBox('Allow unverified action montage if no combat timestamps are supplied')
        allow_unverified.setChecked(False)
        settings_layout.addWidget(allow_unverified)
        vision_enabled=QCheckBox('Automatically scan gameplay with local vision AI (optional; slower)')
        vision_enabled.setChecked(False)
        settings_layout.addWidget(vision_enabled)
        vision_model=QComboBox();vision_model.setEditable(True)
        vision_model.addItems([x for x in installed_models() if any(k in x.lower() for k in ('vl','vision','llava','moondream','minicpm'))])
        if vision_model.count()==0:vision_model.addItems(['llava:7b','qwen3-vl:2b'])
        settings_layout.addWidget(QLabel('Vision model (install separately using Ollama)'))
        settings_layout.addWidget(vision_model)
        vision_help=QLabel('Requires a vision-capable model. Try llava:7b if qwen3-vl:2b returns reasoning only.\n'
                           'Image estimates are NOT confirmed kills. Scan may take several minutes.')
        vision_help.setWordWrap(True);settings_layout.addWidget(vision_help)
        install_vision=self.button('Install / update vision AI (Ollama)',lambda:None)
        settings_layout.addWidget(install_vision)
        def install_model():
            import shutil as _shutil
            import subprocess as _subprocess
            model=vision_model.currentText().strip()
            if not model or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-' for c in model):
                QMessageBox.warning(dlg,'Vision AI','Invalid model name.');return
            exe=_shutil.which('ollama')
            if not exe:
                QMessageBox.warning(dlg,'Vision AI','Ollama is not installed. Install Ollama first using the Eli setup button.');return
            try:
                # Open an interactive terminal so the user sees download size, progress and errors.
                # Start PowerShell directly. `cmd /c start` mis-parses the title
                # containing spaces and may try to execute "Vision" as a program.
                # Both executable path and model are safely quoted for PowerShell.
                quoted_exe = exe.replace("'", "''")
                quoted_model = model.replace("'", "''")
                command = f"& '{quoted_exe}' pull '{quoted_model}'"
                _subprocess.Popen(['powershell.exe', '-NoProfile', '-NoExit', '-Command', command],
                                  creationflags=getattr(_subprocess, 'CREATE_NEW_CONSOLE', 0))
                QMessageBox.information(dlg,'Vision AI','The model download terminal has opened. Wait for a successful completion message, then click Analyze video.')
            except Exception as exc:QMessageBox.warning(dlg,'Vision AI',str(exc))
        install_vision.clicked.connect(lambda checked=False:install_model())
        def release_ai_memory():
            from ollama_memory import release_models
            models=[vision_model.currentText().strip(), 'qwen3:4b']
            results=release_models(models)
            details='\n'.join(f'{name}: {"unload requested" if ok else msg}' for name,(ok,msg) in results.items())
            QMessageBox.information(dlg,'Release AI Memory',details or 'No models selected')
        release_button=self.button('Release AI Memory (Ollama)',lambda:None)
        release_button.setToolTip('Unload the selected vision model and the FragForge planning model. Do not use during active analysis.')
        release_button.clicked.connect(lambda checked=False:release_ai_memory())
        settings_layout.addWidget(release_button)

        audio_enabled=QCheckBox('Analyze game audio for impacts and sudden loud events (local, no extra model)')
        audio_enabled.setChecked(True)
        settings_layout.addWidget(audio_enabled)
        settings_layout.addWidget(QLabel('Audio transients help rank combat candidates; they cannot prove kills or identify specific sounds.'))

        settings_layout=collapsible_section('04  Highlights & visual effects')
        settings_layout.addWidget(QLabel('Action-candidate intro (NOT verified kills)'));settings_layout.addWidget(intro_duration)
        for title,widget in [('Number of highlight clips',count),('Highlight duration',length),('Scene sensitivity (lower = more cuts)',sensitivity)]:
            settings_layout.addWidget(QLabel(title));settings_layout.addWidget(widget)
        settings_layout.addWidget(effects);settings_layout.addWidget(sounds);settings_layout.addWidget(speedup)
        settings_layout=collapsible_section('05  Apply & review', True)
        replace.setChecked(True);replace.hide()
        status=QLabel('Click Analyze to find potential edit points.');settings_layout.addWidget(status)
        # QLabel has no textChanged signal. Mirror status updates through a safe setter.
        _status_set_text = status.setText
        def update_status(message):
            message = str(message)
            _status_set_text(message)
            work_stage.setText(message[:180])
        status.setText = update_status
        analysis_bar=work_bar
        def preset_changed(index):
            custom=(index==1)
            count.setEnabled(custom);length.setEnabled(custom)
            sensitivity.setEnabled(index!=2)
            speedup.setEnabled(index==2)
            effects.setEnabled(True)
            sounds.setEnabled(False)
        mode.currentIndexChanged.connect(preset_changed)
        preset_changed(0)
        pending=getattr(self,'_assistant_pending_plan',None)
        self._assistant_pending_plan=None
        if pending:
            vision_enabled.setChecked(bool(pending.get('focus_kills')))
            tasks=getattr(self,'_assistant_pending_tasks',[])
            if tasks:
                report=QPlainTextEdit()
                report.setReadOnly(True)
                report.setMaximumHeight(145)
                report.setPlainText('REQUESTS FROM ELI\n'+'\n'.join(
                    ('READY: ' if t['supported'] else 'NOT IMPLEMENTED: ')+t['label'] for t in tasks))
                settings_layout.addWidget(report)
            mode.setCurrentIndex(1 if 0 < float(pending.get('target_seconds',0)) <= 300 else (2 if pending['mode']=='longform' else 1))
            target_duration.setValue(float(pending.get('target_seconds',pending.get('target_minutes',0)*60)))
            playback_speed.setValue(float(pending.get('requested_speed') or 1.0))
            if pending.get('music'):
                music_request.setText(str(pending.get('original','')))
                select_requested_music()
            intro_duration.setValue(float(pending.get('intro_seconds',0)))
            speedup.setChecked(pending['speedup'])
            effects.setChecked(pending['effects'])
            sounds.setChecked(False)  # Automatic cues require verified event recognition
            replace.setChecked(True)  # Requested edit selected; timeline replacement still asks approval
            preset_changed(mode.currentIndex())
        results=QListWidget();results.setMinimumHeight(115);settings_layout.addWidget(results)
        controls=QHBoxLayout();layout.addLayout(controls)
        analyze=self.button('Analyze video',lambda:None,True)
        apply=self.button('Apply selected edit',lambda:None);apply.setEnabled(False)
        markers_button=self.button('Review AI markers',lambda:None);markers_button.setEnabled(False)
        cancel_button=self.button('Cancel analysis',lambda:None);cancel_button.setEnabled(False)
        back_button=self.button('← Back to Assistant',lambda checked=False:None) if from_assistant else None
        if back_button:controls.addWidget(back_button)
        controls.addWidget(analyze);controls.addWidget(cancel_button);controls.addWidget(markers_button);controls.addWidget(apply)
        state={'cuts':None,'windows':[],'segments':[],'intro':[],'cues':[],'vision':None,'markers':[]}
        start=float(source.get('start',0));end=float(source.get('end',0))
        full_duration,_=probe(source['path'])
        full_end=min(float(full_duration),3600.)
        def parse_combat_markers():
            import re as _re
            stamps=[]
            for token in _re.split(r'[,;\n]+',combat_markers.text()):
                token=token.strip()
                if not token:continue
                try:
                    parts=[float(x.strip()) for x in token.split(':')]
                    if len(parts)>3 or not parts:raise ValueError()
                    seconds=0.
                    for part in parts:seconds=seconds*60+part
                    if not (0<=seconds<full_end):raise ValueError()
                    stamps.append(seconds)
                except ValueError:
                    raise ValueError(f'Invalid combat timestamp: {token}. Use MM:SS or HH:MM:SS.')
            return sorted(set(stamps))

        def analyzed(cuts):
            heartbeat.stop();cancel_button.setEnabled(False)
            analysis_bar.setRange(0,100)
            state['cuts']=cuts
            if mode.currentIndex()==0:
                windows=choose_highlights(cuts,start,end,3,5.)
            elif mode.currentIndex()==2:
                stagnant=cuts['stagnant'];quiet=cuts['quiet'] if speedup.isChecked() else []
                segments=smart_pacing_segments(0.,full_end,stagnant,quiet)
                if not segments:segments=[(0.,full_end,1.)]
                intro=intro_from_activity(segments,cuts.get('activity_peaks',[]),intro_duration.value()) if intro_duration.value() else []
                state['intro']=intro
                target=target_duration.value()
                if target:
                    segments=select_runtime(segments,target,cuts.get('quiet',[]),runtime(intro))
                state['segments']=segments
                windows=[(a,b) for a,b,_ in segments]
            else:
                if target_duration.value()>0:
                    # Short-form: explicit target and speed override fixed clip-count presets.
                    stagnant=cuts.get('stagnant',[])
                    quiet=cuts.get('quiet',[])
                    base=smart_pacing_segments(0.,full_end,stagnant,[])
                    intro_len=intro_duration.value()
                    intro=intro_from_activity(base,cuts.get('activity_peaks',[]),intro_len) if intro_len else []
                    try:confirmed=parse_combat_markers()
                    except ValueError as exc:
                        status.setText(str(exc));analyze.setEnabled(True);apply.setEnabled(False)
                        return
                    focus=bool(pending and pending.get('focus_kills'))
                    automatic=combat_windows((state['vision'] or {}).get('samples',[]),full_end) if focus else []
                    if focus and automatic and not confirmed:
                        confirmed=[(a+b)/2 for a,b,_ in automatic]
                    if focus and confirmed:
                        # Each confirmed moment gets a 12-second source window; do not
                        # invent extra unrelated clips to fill a 60-second request.
                        marked=[]
                        for t in confirmed:
                            for a,b,_ in base:
                                if a<=t<b:
                                    x=max(a,t-6*playback_speed.value())
                                    y=min(b,t+6*playback_speed.value())
                                    if y-x>.5:marked.append((x,y,1.))
                                    break
                        marked.sort()
                        merged=[]
                        for a,b,_ in marked:
                            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]),1.)
                            else:merged.append((a,b,1.))
                        base=merged
                    # Duration means FINAL playback runtime, not source footage seconds.
                    # Use full-source activity candidates when combat-only windows cannot fill the target.
                    peaks=[(t,1000.) for t in confirmed] if (focus and confirmed) else cuts.get('activity_peaks',[])
                    _,segments=precision_montage(base,peaks,target_duration.value(),playback_speed.value(),runtime(intro))
                    if runtime(segments)+runtime(intro)<target_duration.value()-.15 and focus and confirmed:
                        full_base=smart_pacing_segments(0.,full_end,cuts.get('stagnant',[]),[])
                        _,segments=precision_montage(full_base,peaks+cuts.get('activity_peaks',[]),target_duration.value(),playback_speed.value(),runtime(intro))
                    state['intro']=intro;state['segments']=segments
                    windows=[(a,b) for a,b,_ in segments]
                else:
                    windows=choose_highlights(cuts,start,end,int(count.currentText()),length.value())
            state['windows']=windows;results.clear()
            planned=[('intro',a,b,s) for a,b,s in state['intro']]
            planned += [('main',a,b,state['segments'][i][2] if state['segments'] else 1.) for i,(a,b) in enumerate(windows)]
            state['cues']=ranked_activity_cues(cuts.get('activity_peaks',[]),planned)

            for i,(a,b) in enumerate(windows):
                rate=state['segments'][i][2] if state['segments'] else 1.
                results.addItem(f'{tc(a)}  →  {tc(b)}  ({b-a:.1f}s at {rate:g}×)')
            if state['segments']:
                status.setText(f'Candidate output: {runtime(state["segments"])+runtime(state["intro"]):.1f}s; {len(cuts.get("stagnant",[]))} stagnant ranges; {len(combat_windows((state["vision"] or {}).get("samples",[]),full_end))} AI combat candidates (NOT verified kills).')
            else:
                status.setText(f'Found {len(cuts)} scene changes. Review {len(windows)} suggested highlights.')
            analysis_bar.setValue(100);work_message.setText('Your edit is prepared. Review it before applying changes.')
            editor_tabs.setCurrentWidget(scroll);activity.update(last_update=time.monotonic(),stage='Analysis complete — review selected clips');analyze.setEnabled(True);apply.setEnabled(bool(windows))
            release_ai_job('analysis');cancel_button.setEnabled(False);heartbeat.stop()
            if not windows:
                status.setText('Analysis finished but no valid clips were selected. Try allowing unverified footage, disabling combat-only focus, or changing the target duration; then reanalyze.')
        def failed(message):
            release_ai_job('analysis')
            heartbeat.stop();cancel_button.setEnabled(False)
            analysis_bar.setRange(0,100)
            status.setText('Analysis failed — see error details');work_message.setText('Analysis stopped. Please review the error.');analyze.setEnabled(True);apply.setEnabled(False)
            QMessageBox.warning(dlg,'Auto Edit Analysis',message)
        # A UI heartbeat keeps the dialog visibly responsive even when FFmpeg
        # cannot provide timestamps (slow seeking, codec initialization, etc.).
        heartbeat=QTimer(dlg)
        heartbeat.setInterval(1000)
        activity={'started':0.0,'last_update':0.0,'last_pct':0,'stage':'Starting analysis'}
        def tick_analysis():
            elapsed=int(time.monotonic()-activity['started'])
            if analysis_bar.maximum()!=0 and elapsed>=4 and time.monotonic()-activity['last_update']>=4:
                analysis_bar.setRange(0,100)  # hold real completed percentage; never animate fictitious progress
            if analyze.isEnabled():
                heartbeat.stop();return
            if time.monotonic()-activity['last_update']>=180:
                status.setText(f"{activity['stage']} · {elapsed}s elapsed · no update for 3 minutes; request may be stalled. Use Cancel analysis.")
                return
            status.setText(f"{activity['stage']} · {elapsed}s elapsed" +
                           (' · waiting for processing update' if time.monotonic()-activity['last_update']>=10 else ''))
        heartbeat.timeout.connect(tick_analysis)
        def invalidate_analysis(*args):
            if state['cuts'] is not None:
                apply.setEnabled(False)
                status.setText('Editing settings changed — click Analyze video again before applying.')
        for control in (mode, target_duration, playback_speed, intro_duration, speedup, sensitivity, count, length, vision_model):
            if isinstance(control,QComboBox):control.currentIndexChanged.connect(invalidate_analysis)
            elif isinstance(control,QCheckBox):control.toggled.connect(invalidate_analysis)
            else:control.valueChanged.connect(invalidate_analysis)
        combat_markers.textChanged.connect(invalidate_analysis)
        allow_unverified.toggled.connect(invalidate_analysis)
        vision_enabled.toggled.connect(invalidate_analysis)
        audio_enabled.toggled.connect(invalidate_analysis)
        def review_recognition_markers():
            markers=state.get('markers',[])
            if not markers:
                QMessageBox.information(dlg,'Eli — Recognition','No recognition markers yet. Enable vision or audio scanning and analyze the video first.')
                return
            report=director_report(markers)
            review=QDialog(dlg);review.setWindowTitle('Eli — Recognition markers');review.resize(740,520)
            review_layout=QVBoxLayout(review)
            review_text=QPlainTextEdit();review_text.setReadOnly(True);review_text.setPlainText(report)
            review_layout.addWidget(review_text)
            save_button=self.button('Export marker JSON for review',lambda:None)
            def save_markers():
                dest,_=QFileDialog.getSaveFileName(review,'Export AI recognition markers','FragForge_recognition_markers.json','JSON files (*.json)')
                if dest:
                    try:
                        export_report(dest,source['path'],vision_model.currentText(),markers)
                        QMessageBox.information(review,'Markers exported','Recognition markers saved. These are unverified labels; no AI model has been trained.')
                    except Exception as exc:
                        QMessageBox.warning(review,'Export failed',str(exc))
            save_button.clicked.connect(save_markers)
            review_layout.addWidget(save_button)
            review.exec()
        markers_button.clicked.connect(review_recognition_markers)
        def after_visual_scan(cuts):
            if not vision_enabled.isChecked():
                state['vision']=None;analyzed(cuts);return
            model=vision_model.currentText().strip()
            if model not in installed_models():
                failed('Vision model '+model+' is not installed. Run: ollama pull '+model+'\n'
                       'Or uncheck automatic vision scan and explicitly allow unverified footage.')
                return
            status.setText('Vision AI scanning sampled gameplay frames…')
            analysis_bar.setRange(0,100);analysis_bar.setValue(0)
            worker=VisionScanWorker(source['path'],full_end,model,audio_enabled.isChecked())
            worker.profile=getattr(self,'_ai_performance_mode','Accelerated')
            self._vision_scan_worker=worker
            worker.progress.connect(lambda pct:(analysis_bar.setValue(min(99, max(0, pct))),activity.update(last_update=time.monotonic(),stage='Analyzing gameplay visuals')))
            def done(result):
                state['vision']=result
                state['markers']=build_markers(result.get('samples',[]),result.get('audio',{}).get('events',[]))
                markers_button.setEnabled(bool(state['markers']))
                analyzed(cuts)
                hits=combat_windows(result['samples'],full_end)
                if result.get('audio'):status.setToolTip(result['audio'].get('status',''))
                if result.get('failed_frames'):status.setToolTip((status.toolTip()+'\n' if status.toolTip() else '')+f'{result["failed_frames"]} vision frames failed classification')
                if pending and pending.get('focus_kills') and not hits and not allow_unverified.isChecked() and not combat_markers.text().strip():
                    apply.setEnabled(False)
                    status.setText('Vision scan complete, but no credible combat candidates found. To create a general highlight montage, check Allow unverified footage and click Analyze video again; or enter known combat timestamps.')
                elif hits:
                    status.setText(status.text()+f' AI flagged {len(hits)} candidate combat frames; audio transients: {len(result.get("audio",{}).get("events",[]))}. Review before export.')
            worker.ready.connect(done)
            worker.failed.connect(failed)
            activity.update(last_update=time.monotonic(),stage='Vision scan running')
            worker.start()

        def run_analysis():
            if any(w is not None and w.isRunning() for w in (getattr(self,'_auto_analysis_worker',None),getattr(self,'_vision_scan_worker',None))):
                QMessageBox.warning(dlg,'Analysis already running','Only one analysis may run at a time. Cancel and wait before starting another.')
                return
            if not acquire_ai_job('analysis'):
                QMessageBox.warning(dlg,'AI busy','An AI job is already active. Wait for it to finish or cancel it first.')
                return
            editor_tabs.setCurrentWidget(work_page);work_message.setText('Please wait, I am busy working on your video!')
            analyze.setEnabled(False);apply.setEnabled(False);markers_button.setEnabled(False);state['markers']=[];cancel_button.setEnabled(True);analysis_bar.setRange(0,100);analysis_bar.setValue(0)
            activity.update(started=time.monotonic(),last_update=time.monotonic(),last_pct=0,stage='Starting analysis')
            status.setText('Launching FFmpeg scene analysis…')
            heartbeat.start()
            worker=AutoAnalysisWorker(source['path'],0. if (mode.currentIndex()==2 or target_duration.value()>0) else start,
                                      full_end if (mode.currentIndex()==2 or target_duration.value()>0) else end,
                                      sensitivity.value(),mode.currentIndex()==2 or target_duration.value()>0)
            self._auto_analysis_worker=worker
            worker.ready.connect(after_visual_scan);worker.failed.connect(failed)
            def update_stage(message):
                activity['stage']=message.rstrip('…')
                activity['last_update']=time.monotonic()
                if message.startswith('Detecting scene changes'):
                    analysis_bar.setRange(0,100)
                elif message.startswith('Scanning'):
                    analysis_bar.setRange(0,100)
                elif message.startswith('Analysis complete'):
                    analysis_bar.setRange(0,100)
                    analysis_bar.setValue(95 if vision_enabled.isChecked() else 99)
                tick_analysis()
            def update_progress(percent):
                activity['last_update']=time.monotonic()
                activity['last_pct']=percent
                if percent<100 and not activity['stage'].startswith('Detecting'):
                    analysis_bar.setRange(0,100)
                    analysis_bar.setValue(min(95, percent) if vision_enabled.isChecked() else min(99, percent))
                tick_analysis()
            worker.stage.connect(update_stage)
            worker.progress.connect(update_progress)
            worker.start()
        def apply_edit():
            windows=state['windows']
            if not windows:return
            if pending and pending.get('focus_kills') and not combat_markers.text().strip() and not combat_windows((state['vision'] or {}).get('samples',[]),full_end) and not allow_unverified.isChecked():
                QMessageBox.warning(dlg,'Combat review required',
                    'No confirmed or AI-estimated combat moments were found.\n\n'
                    'Enter source timestamps for real combat, or explicitly allow an unverified action montage.\n'
                    'The activity detector cannot reliably identify zombie kills.')
                return
            if pending and pending.get('focus_kills') and combat_markers.text().strip() and not state['segments']:
                QMessageBox.warning(dlg,'No combat footage selected',
                    'The supplied timestamps did not produce usable clips. Check the timestamps and analyze again.')
                return
            if pending and pending.get('music') and not music_path.text().strip():
                select_requested_music()
            if pending and pending.get('music') and not music_path.text().strip():
                QMessageBox.warning(dlg,'Music required','The requested music was not found in the bundled library. No edit was applied. Check the installed music assets.')
                return
            if music_path.text().strip():
                try:
                    if not Path(music_path.text().strip()).is_file():raise FileNotFoundError(music_path.text().strip())
                    music_duration,_=probe(music_path.text().strip())
                    if music_duration<=0:raise ValueError('Invalid music duration')
                except Exception as exc:
                    QMessageBox.warning(dlg,'Music unavailable','Cannot apply requested soundtrack: '+str(exc));return
            previous_clips=copy.deepcopy(self.clips)
            if replace.isChecked():
                confirmation=QMessageBox.question(dlg,'Replace Timeline',
                    'Replace the current timeline with the proposed Director edit?\n'
                    'Save your project first. You can also Undo this operation.')
                if confirmation!=QMessageBox.Yes:return
                self.clips=[]
            elif self.clips:
                QMessageBox.information(dlg,'Choose Montage',
                    'To build a sequential highlight reel, enable Replace current timeline.\n'
                    'Your existing clips have not been changed.');return
            position=0.
            fx_ids=['fx_001','fx_053','fx_061','fx_065','fx_043']
            sfx_ids=['board_001','board_003','board_024','board_021','board_043']
            intro=state['intro'] if state['intro'] else []
            timeline=[('intro',a,b,s) for a,b,s in intro]
            timeline += [('main',a,b,state['segments'][i][2] if state['segments'] else 1.)
                         for i,(a,b) in enumerate(windows)]
            added_fx=added_sfx=0
            errors=[]
            for i,(part,a,b,rate) in enumerate(timeline):
                clip=copy.deepcopy(source)
                clip.update(start=a,end=b,at=position,track='V1',speed=rate)
                # Short, bounded fades soften automatic montage boundaries without
                # altering the requested final playback duration.
                clip['fade']=min(.18, max(0., length_hint / 5.0)) if (length_hint := (b-a)/max(rate,.1)) > .35 else 0.
                # Only AI-generated V1 clips receive automatic mix balancing.
                # Manual timeline clips retain their user-selected levels.
                if clip.get('audio'):
                    clip['volume']=.42
                clip['label']=('INTRO — action candidate (unverified)' if part=='intro' else 'Director edit — AI candidate, not verified kill')
                self.clips.append(clip)
                length=(b-a)/max(.1,rate)
                # Eli Audio Intelligence: cuts and merges are NEVER sound events.
                # Do not insert bell/board cues at clip boundaries.
                position+=length
            if music_path.text().strip():
                try:
                    chosen_music=music_path.text().strip()
                    music_length,_=probe(chosen_music)
                    if music_length<=0:raise ValueError('Music file has no valid duration')
                    if not Path(chosen_music).is_file():raise FileNotFoundError(chosen_music)
                    at=0.
                    while at<position-.05:
                        take=min(music_length,position-at)
                        self.clips.append(dict(path=chosen_music,start=0.,end=take,at=at,
                                               track='A2',audio=True,kind='audio',speed=1.,
                                               effect='None',fade=min(.75,take/4),volume=.24,
                                               label='Eli background music — selected from requested genre'))
                        at+=take
                except Exception as exc:errors.append('Background music: '+str(exc))
            # Add restrained accents only at measured activity peaks. These are
            # visual-change candidates, NOT recognized kills or multikills.
            cues=state.get('cues',[])
            for output_time,contrast,reason in cues:
                if effects.isChecked():
                    try:
                        path=effect_path('fx_001')
                        self.clips.append(dict(path=path,start=0.,end=.65,at=output_time,
                                               track='V3',audio=False,kind='effect',speed=1.,
                                               effect='None',fade=.12,opacity=.4,overlay_scale=.45,
                                               label=f'Director visual — {reason} (contrast {contrast:g}, unverified)'))
                        added_fx+=1
                    except Exception as exc:errors.append('Activity visual: '+str(exc))
                # Visual contrast peaks are not verified gunshots or impacts.
                # Automatic event SFX remain disabled until audio/video recognition
                # provides reliable, timestamped evidence and explicit user consent.
            # Validate the actual V1 timeline, not the analysis estimate. A failed
            # edit must restore the original clips rather than claim success.
            requested=float(target_duration.value())
            actual_v1=max((c['at']+duration(c) for c in self.clips
                           if c.get('track')=='V1' and c.get('kind')=='video'),default=0.)
            actual_total=self.total()
            tolerance=max(.15, min(1.0, requested*.005))
            failures=[]
            if not timeline or actual_v1<=0:
                failures.append('No video clips were placed on V1')
            # Never silently accept a shorter export than explicitly requested.
            if requested and abs(actual_v1-requested)>tolerance:
                failures.append(f'Final video is {actual_v1:.2f}s; requested {requested:.2f}s. Re-analyze with more source footage.')
            if failures:
                self.clips=previous_clips
                self.selected=None
                self.update_all()
                QMessageBox.critical(dlg,'Director edit NOT applied',
                    'The timeline did not match your request. Original timeline restored.\n\n'
                    + '\n'.join(failures))
                return
            summary=(f'Applied {len(timeline)} video clips, {added_fx} visual effects and '
                     f'{added_sfx} sound cues; verified timeline {actual_total:.2f}s ({actual_total/60:.2f} min). '
                     f'Intro: {runtime(intro):.1f}s of UNVERIFIED action candidates. '
                     'Activity candidates are NOT verified kills. Review before exporting.')
            if music_path.text().strip():
                summary+='\nMusic: '+Path(music_path.text().strip()).stem
            if pending and pending.get('focus_kills'):
                summary+=('\nCOMBAT: user-confirmed timestamps used (not automatic kill recognition).' if combat_markers.text().strip() else '\nKILLS NOT VERIFIED: unverified action montage.')
            if errors and any(e.startswith('Background music:') for e in errors):
                self.clips=previous_clips
                self.selected=None
                self.update_all()
                QMessageBox.critical(dlg,'Music edit failed','The requested music could not be inserted. Original timeline restored.\n'+'; '.join(errors[:4]))
                return
            if errors:summary+='\nSkipped items: '+'; '.join(errors[:4])
            self.player.pause();self.selected=None;self.playhead=0.
            self.update_all();self.preview_at=0
            self.capture_history()
            self.note.setText(summary)
            QMessageBox.information(self,'Director edit applied',summary)
            dlg.accept()
        def cancel_analysis():
            workers=[getattr(self,'_auto_analysis_worker',None),getattr(self,'_vision_scan_worker',None)]
            running=[w for w in workers if w is not None and w.isRunning()]
            for worker in running:worker.cancel()
            if running:
                status.setText('Cancelling analysis… waiting for active request to stop.')
                cancel_button.setEnabled(False)
        if back_button:
            def go_back():
                worker=getattr(self,'_auto_analysis_worker',None)
                if worker and worker.isRunning():
                    QMessageBox.information(dlg,'Analysis running','Cancel the analysis and wait for it to finish before going back.')
                    return
                dlg.reject()
                QTimer.singleShot(0,self.open_ai_assistant)
            back_button.clicked.connect(lambda checked=False:go_back())
        cancel_button.clicked.connect(lambda checked=False:cancel_analysis())
        analyze.clicked.connect(lambda checked=False:run_analysis())
        apply.clicked.connect(lambda checked=False:apply_edit())
        if auto_analyze:
            QTimer.singleShot(150,run_analysis)
        def cleanup_preview():
            if getattr(self,'_director_working_dialog',None) is dlg:
                self._director_working_dialog=None
            for worker in (getattr(self,'_auto_analysis_worker',None),getattr(self,'_vision_scan_worker',None)):
                if worker is not None and worker.isRunning():
                    worker.cancel()
            if from_assistant and parent_dialog is not None and parent_dialog.isVisible():
                parent_dialog.raise_()
        if from_assistant:
            dlg.finished.connect(lambda _result:cleanup_preview())
            dlg.show()
            dlg.raise_()
        else:
            dlg.exec()
            cleanup_preview()

    def open_effect_library(self):
        # Build the library without copying or loading 100 images on the UI thread.
        dlg=QDialog(self)
        dlg.setWindowTitle('Eli Studio Gaming Effects — 100 Presets')
        dlg.setMinimumSize(660,540)
        layout=QVBoxLayout(dlg)
        layout.addWidget(QLabel('Choose an effect, then add it to the V3 overlay track.'))
        search=QLineEdit()
        search.setPlaceholderText('Search: BOOM, KAPOW, HEADSHOT, LOL...')
        layout.addWidget(search)
        category=QComboBox()
        category.addItems(['All categories']+sorted({group for _,_,group in EFFECTS}))
        layout.addWidget(category)
        results=QListWidget()
        results.setAlternatingRowColors(True)
        layout.addWidget(results)
        status=QLabel('100 presets available')
        layout.addWidget(status)
        def refresh():
            q=search.text().strip().lower()
            cat=category.currentText()
            results.clear()
            for slug,name,group in EFFECTS:
                if q and q not in name.lower() and q not in group.lower():continue
                if cat!='All categories' and group!=cat:continue
                item=QListWidgetItem(f'{name}   ·   {group}')
                item.setData(Qt.UserRole,slug)
                results.addItem(item)
            status.setText(f'{results.count()} effects shown')
            if results.count():results.setCurrentRow(0)
        search.textChanged.connect(refresh)
        category.currentIndexChanged.connect(refresh)
        row=QHBoxLayout()
        layout.addLayout(row)
        seconds=QDoubleSpinBox()
        seconds.setRange(.1,30)
        seconds.setValue(1.5)
        seconds.setSingleStep(.25)
        seconds.setSuffix(' seconds')
        row.addWidget(QLabel('Duration:'))
        row.addWidget(seconds)
        insert=self.button('＋ Add Effect to V3',lambda:None,True)
        row.addWidget(insert)
        def add():
            item=results.currentItem()
            if item is None:
                QMessageBox.information(dlg,'Choose Effect','Select an effect first.')
                return
            slug=item.data(Qt.UserRole)
            name=next(name for key,name,_ in EFFECTS if key==slug)
            try:
                path=effect_path(slug)
                if not Path(path).is_file():
                    raise FileNotFoundError(path)
                clip=dict(path=path,start=0.,end=seconds.value(),at=self.playhead,
                          track='V3',audio=False,kind='effect',speed=1.,
                          effect='None',fade=.12,opacity=1.0,label=name)
                self.clips.append(clip)
                self.selected=len(self.clips)-1
                self.visual_cache.frames[path]=[(0.,Path(path).read_bytes())]
                self.update_all()
                self.note.setText(f'Added {name} to V3 at {tc(self.playhead)}. Visible in preview and export.')
                dlg.accept()
            except Exception as exc:
                QMessageBox.critical(dlg,'Cannot Insert Effect',
                                     f'{exc}\\n\\nPlease verify effects_assets are bundled.')
        insert.clicked.connect(add)
        results.itemDoubleClicked.connect(lambda _:add())
        refresh()
        dlg.exec()
    def open_sound_library(self):
        dlg=QDialog(self);dlg.setWindowTitle('Eli Studio — Curated Soundboard & Audio Library');dlg.setMinimumSize(640,520)
        layout=QVBoxLayout(dlg)
        layout.addWidget(QLabel('42 newly produced soundboard and editing sounds; original audio (not extracted meme recordings). Import your own licensed clips.'))
        search=QLineEdit();search.setPlaceholderText('Search sounds: boom, metal pipe, airhorn, record scratch, music loop...');layout.addWidget(search)
        category=QComboBox();category.addItems(['All categories']+sorted({c for _,_,c in SOUNDS} | {'My Audio'}));layout.addWidget(category)
        results=QListWidget();layout.addWidget(results)
        status=QLabel();layout.addWidget(status)
        def refresh():
            q=search.text().strip().lower();cat=category.currentText();results.clear()
            for slug,name,group in SOUNDS + user_sounds():
                if q and q not in name.lower() and q not in group.lower():continue
                if cat!='All categories' and group!=cat:continue
                item=QListWidgetItem(f'{name}   ·   {group}');item.setData(Qt.UserRole,slug);results.addItem(item)
            status.setText(f'{results.count()} sounds shown')
            if results.count():results.setCurrentRow(0)
        search.textChanged.connect(refresh);category.currentIndexChanged.connect(refresh)
        row=QHBoxLayout();layout.addLayout(row)
        track=QComboBox();track.addItems([t for t in TRACKS if t.startswith('A')]);row.addWidget(track)
        def selected_path():
            item=results.currentItem()
            if item is None:raise ValueError('Select a sound first')
            return resolve_sound(item.data(Qt.UserRole))
        def preview():
            try:
                self.sfx_preview.stop();self.sfx_preview.setSource(QUrl.fromLocalFile(selected_path()));self.sfx_preview.play()
            except Exception as exc:QMessageBox.warning(dlg,'Sound Preview',str(exc))
        def insert_sound():
            try:
                path=selected_path();length,_=probe(path)
                c=dict(path=path,start=0.,end=length,at=self.playhead,track=track.currentText(),
                       audio=True,kind='audio',speed=1.,effect='None',fade=0.)
                self.clips.append(c);self.selected=len(self.clips)-1
                self.visual_cache.request(path,'audio');self.update_all()
                self.note.setText(f'Added {Path(path).stem} to {c["track"]} at {tc(self.playhead)}')
                dlg.accept()
            except Exception as exc:QMessageBox.critical(dlg,'Insert Sound',str(exc))
        def import_memes():
            files,_=QFileDialog.getOpenFileNames(
                dlg, 'Import Audio (use recordings you have permission to use)', '',
                'Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)')
            if not files:return
            added=[];errors=[]
            for filename in files:
                try:
                    length,has_audio=probe(filename)
                    if length<=0 or not has_audio:raise ValueError('No readable audio stream')
                    import_user_sound(filename)
                    added.append(Path(filename).stem)
                except Exception as exc:
                    errors.append(f'{Path(filename).name}: {exc}')
            if added:
                category.setCurrentText('My Audio')
                search.clear()
                refresh()
                self.note.setText(f'Imported {len(added)} audio file(s). Select one to preview or insert.')
            if errors:QMessageBox.warning(dlg,'Some sounds could not be imported','\n'.join(errors[:12]))
        row.addWidget(self.button('＋ Import Audio',import_memes))
        row.addWidget(self.button('▶ Preview Sound',preview))
        row.addWidget(self.button('＋ Add to Audio Track',insert_sound,True))
        results.itemDoubleClicked.connect(lambda _:preview())
        refresh();dlg.exec()
        self.sfx_preview.stop()
    def refresh_tracks(self):
        self.track_choice.blockSignals(True)
        self.track_choice.clear()
        self.track_choice.addItems([f'{t} — {LABELS[t]}' for t in TRACKS])
        self.track_choice.setCurrentIndex(TRACKS.index(self.track) if self.track in TRACKS else 0)
        self.track_choice.blockSignals(False)
    def new_project(self):
        if self.clips and QMessageBox.question(self,'New Project','Discard the current unsaved timeline?')!=QMessageBox.Yes:return
        self.player.stop();self.clips=[];self.media=[];self.library.clear();self.selected=None;self.playhead=0;self.project_path=None;self.update_all()
    def capture_history(self):
        if self._history_busy:return
        snapshot=copy.deepcopy((self.clips,self.media,TRACKS,LABELS,COLORS))
        if self._history_index>=0 and self._history[self._history_index]==snapshot:return
        self._history=self._history[:self._history_index+1]
        self._history.append(snapshot)
        if len(self._history)>70:self._history.pop(0)
        self._history_index=len(self._history)-1
        self._autosave_dirty=True

    def restore_history(self,index):
        if not 0<=index<len(self._history):return
        self._history_busy=True
        try:
            self.player.pause()
            self.clips,self.media,tracks,labels,colors=copy.deepcopy(self._history[index])
            TRACKS[:]=tracks;LABELS.clear();LABELS.update(labels);COLORS.clear();COLORS.update(colors)
            self._history_index=index;self.selected=None
            self.refresh_tracks();self.library.clear()
            for item in self.media:self.library.addItem(Path(item['path']).name)
            self.update_all();self.note.setText('Undo / Redo applied')
        finally:self._history_busy=False

    def undo(self):self.restore_history(self._history_index-1)
    def redo(self):self.restore_history(self._history_index+1)

    def project_payload(self):
        root=Path(self.project_path).resolve().parent if self.project_path else Path.home()
        def pack(item):
            data=copy.deepcopy(item)
            data['path']=os.path.relpath(str(Path(data['path']).resolve()),str(root))
            return data
        return {'format':'fragforge-project','version':1,'media':[pack(m) for m in self.media],
                'clips':[pack(c) for c in self.clips],'playhead':self.playhead,
                'tracks':[{'id':t,'label':LABELS[t]} for t in TRACKS]}

    def autosave_project(self):
        if not self.clips or not self._autosave_dirty:return
        try:
            target=Path.home()/'FragForge'/'recovery';target.mkdir(parents=True,exist_ok=True)
            path=target/'autosave.fragforge'
            # Recovery uses absolute media paths to remain portable across project locations.
            payload=self.project_payload()
            root=Path(self.project_path).resolve().parent if self.project_path else Path.home()
            for entry in payload['clips']+payload['media']:
                entry['path']=str((root/entry['path']).resolve())
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,indent=2),encoding='utf-8');os.replace(tmp,path)
            self._autosave_dirty=False
            self.note.setText('Recovery autosave created')
        except Exception as exc:self.note.setText('Autosave warning: '+str(exc))

    def recover_autosave(self):
        path=Path.home()/'FragForge'/'recovery'/'autosave.fragforge'
        if not path.exists():QMessageBox.information(self,'Recovery','No recovery autosave found.');return
        self.load_project(str(path))

    def set_overlay_transform(self,key,value):
        c=self.selected_clip()
        if not c or c.get('kind')!='effect':return
        c[key]=value;self.live_overlay.update();self.capture_history()

    def reset_overlay_transform(self):
        c=self.selected_clip()
        if not c or c.get('kind')!='effect':return
        c.update(overlay_x=0.,overlay_y=0.,overlay_scale=1.,overlay_rotation=0.)
        self.update_all();self.live_overlay.update()

    def change_music_duck(self,checked):
        c=self.selected_clip()
        if c and c.get('kind')=='audio':
            c['duck_music']=bool(checked);self.capture_history();self.sync_timeline_audio()

    def open_transitions(self):
        c=self.selected_clip()
        if not c:QMessageBox.information(self,'Transitions','Select a timeline clip first.');return
        choices=['None','Fade In + Out','Fade to Black','Zoom In','Glitch Cut']
        value,ok=QInputDialog.getItem(self,'Clip Transitions','Transition style:',choices,0,False)
        if ok:
            c['transition']=value
            if value!='None':c['fade']=max(.4,float(c.get('fade',0)))
            self.update_all();self.note.setText('Transition: '+value+' (preview/export support varies by style)')

    def save_project(self,save_as=False):
        path=self.project_path if not save_as else None
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'Save FragForge Project','Untitled.fragforge','FragForge Projects (*.fragforge)')
        if not path:return
        if not path.lower().endswith('.fragforge'):path+='.fragforge'
        import json
        try:
            root=Path(path).resolve().parent
            def pack(item):
                data=copy.deepcopy(item)
                media_path=Path(data['path']).resolve()
                data['path']=os.path.relpath(str(media_path),str(root))
                return data
            payload={'format':'fragforge-project','version':1,'media':[pack(m) for m in self.media],
                     'clips':[pack(c) for c in self.clips],'playhead':self.playhead,'tracks':[{'id':t,'label':LABELS[t]} for t in TRACKS]}
            target=Path(path);temporary=target.with_suffix('.fragforge.tmp')
            temporary.write_text(json.dumps(payload,indent=2),encoding='utf-8')
            os.replace(temporary,target)
            self.project_path=str(target);self.note.setText('Saved project: '+target.name)
        except Exception as exc:QMessageBox.critical(self,'Save Project',str(exc))
    def open_project(self):
        path,_=QFileDialog.getOpenFileName(self,'Open FragForge Project','','FragForge Projects (*.fragforge)')
        if not path:return
        self.load_project(path)
    def load_project(self,path):
        import json
        try:
            payload=json.loads(Path(path).read_text(encoding='utf-8'))
            if payload.get('format')!='fragforge-project' or payload.get('version')!=1:raise ValueError('Unsupported project format')
            root=Path(path).resolve().parent
            def unpack(item):
                data=dict(item)
                data['path']=str((root/data['path']).resolve())
                return data
            media=[unpack(m) for m in payload['media']]
            clips=[unpack(c) for c in payload['clips']]
            missing=sorted({c['path'] for c in media+clips if not Path(c['path']).is_file()})
            if missing:raise FileNotFoundError('Media missing; keep source files in their original locations:\\n'+'\\n'.join(missing[:8]))
            self.player.stop();self.media=media;self.clips=clips;self.selected=None;self.playhead=float(payload.get('playhead',0))
            # Restore custom tracks before drawing the timeline.
            saved=payload.get('tracks',[])
            restored_order=[]
            for entry in saved:
                tid=entry['id']
                if not re.fullmatch(r'[VA][1-9][0-9]*',tid):continue
                if tid not in TRACKS:
                    TRACKS.append(tid);COLORS[tid]='#6656a6' if tid.startswith('V') else '#258a79'
                LABELS[tid]=entry.get('label',tid)
                restored_order.append(tid)
            if restored_order:
                TRACKS[:]=restored_order+[t for t in TRACKS if t not in restored_order]
            self.refresh_tracks()
            self.library.clear()
            for item in media:
                self.library.addItem(Path(item['path']).name)
                self.visual_cache.request(item['path'],item['kind'])
            for clip in clips:
                if clip.get('kind')=='effect' and Path(clip['path']).exists():
                    self.visual_cache.frames[clip['path']]=[(0.,Path(clip['path']).read_bytes())]
            self.project_path=path;self.update_all();self.note.setText('Opened project: '+Path(path).name)
        except Exception as exc:QMessageBox.critical(self,'Open Project',str(exc))
    def change_effect(self,index):
        c=self.selected_clip()
        if c:c['effect']=self.effect_choice.currentText();self.note.setText('Effect set; visible in exported MP4')
    def change_fade(self,value):
        c=self.selected_clip()
        if c:c['fade']=float(value);self.note.setText('Fade duration updated for preview and export');self.live_overlay.update()
    def change_overlay_opacity(self,percent):
        c=self.selected_clip()
        if c is None or c.get('kind')!='effect':return
        c['opacity']=percent/100.0
        self.overlay_opacity_label.setText(f'{percent}% — ' + ('Invisible' if percent==0 else 'Fully visible' if percent==100 else 'Semi-transparent'))
        self.note.setText('Overlay visibility updated for preview and export');self.live_overlay.update()
    def apply_fade(self,value):
        c=self.selected_clip()
        if c:
            c['fade']=float(value);self.fade_control.blockSignals(True);self.fade_control.setValue(value);self.fade_control.blockSignals(False)
    def info(self,feature):QMessageBox.information(self,feature,f'{feature} panel is planned. This build focuses on the timeline, clip editing, and playback.')
    def add_track(self):
        """Select an MP3 and create a dedicated audio/sound-effects track."""
        path,_=QFileDialog.getOpenFileName(
            self,'Add Sound Track — Select MP3','','MP3 audio files (*.mp3)')
        if not path:return
        path=os.path.abspath(path)
        if Path(path).suffix.lower()!='.mp3':
            QMessageBox.warning(self,'Unsupported File','Please select an MP3 audio file.')
            return
        try:
            length,has_audio=probe(path)
            if length<=0 or not has_audio:
                raise ValueError('The MP3 has no readable audio stream or duration.')
        except Exception as exc:
            QMessageBox.warning(self,'Cannot Add Sound Track',f'Could not read the MP3:\n{exc}')
            return
        next_id=max([int(t[1:]) for t in TRACKS if t.startswith('A') and t[1:].isdigit()]+[0])+1
        name=f'A{next_id}'
        TRACKS.append(name)
        LABELS[name]='Audio / Sound FX'
        COLORS[name]='#258a79'
        source=dict(path=path,start=0.,end=length,audio=True,kind='audio')
        self.media.append(source)
        self.library.addItem(f'{Path(path).name}   •   {tc(length)}')
        self.track=name
        self.refresh_tracks()
        self.insert_source(source,name,self.playhead)
        self.note.setText(f'Added MP3 {Path(path).name} on sound track {name}.')
    def total(self):return max((c['at']+duration(c) for c in self.clips),default=0)
    def update_all(self):
        self.capture_history()
        total=self.total();self.timeline.clips=self.clips;self.timeline.selected=self.selected;self.timeline.playhead=self.playhead;self.timeline.total=max(30,total);self.timeline.refresh()
        self.time_label.setText(f'{tc(self.playhead)} / {tc(total)}');self.timeline_time.setText(f'{tc(self.playhead)} / {tc(total)}')
        self.scrub.blockSignals(True);self.scrub.setValue(round(10000*self.playhead/max(total,.001)));self.scrub.blockSignals(False)
        if self.selected is not None and self.selected<len(self.clips):
            c=self.clips[self.selected];self.clip_name.setText(Path(c['path']).name+f'\\n{c["track"]}  •  {tc(duration(c))}  •  {c.get("speed",1.):g}×')
            self.speed_control.blockSignals(True);self.speed_control.setValue(c.get('speed',1.));self.speed_control.blockSignals(False)
            self.position.blockSignals(True);self.position.setValue(c['at']);self.position.blockSignals(False)
            self.effect_choice.blockSignals(True);self.effect_choice.setCurrentText(c.get('effect','None'));self.effect_choice.blockSignals(False)
            self.fade_control.blockSignals(True);self.fade_control.setValue(c.get('fade',0));self.fade_control.blockSignals(False)
            is_overlay=c.get('kind')=='effect'
            self.overlay_opacity.setEnabled(is_overlay)
            self.overlay_opacity.blockSignals(True);self.overlay_opacity.setValue(round(100*float(c.get('opacity',1.0))));self.overlay_opacity.blockSignals(False)
            pct=self.overlay_opacity.value()
            self.overlay_opacity_label.setText(f'{pct}% — ' + ('Invisible' if pct==0 else 'Fully visible' if pct==100 else 'Semi-transparent') if is_overlay else 'Select a V3 effect to adjust visibility')
            for field,key,mul in [(self.overlay_x,'overlay_x',1),(self.overlay_y,'overlay_y',1),(self.overlay_scale,'overlay_scale',100),(self.overlay_rotation,'overlay_rotation',1)]:
                field.blockSignals(True);field.setEnabled(is_overlay);field.setValue(float(c.get(key,1. if key=='overlay_scale' else 0.))*mul);field.blockSignals(False)
            self.music_duck.blockSignals(True);self.music_duck.setChecked(bool(c.get('duck_music',False)));self.music_duck.setEnabled(c.get('kind')=='audio');self.music_duck.blockSignals(False)
            self.clip_volume.blockSignals(True)
            self.clip_volume.setValue(round(100*float(c.get('volume',1.0))))
            self.clip_volume.blockSignals(False)
            self.clip_volume_label.setText(f'{self.clip_volume.value()}% — ' + ('Muted' if self.clip_volume.value()==0 else 'Original' if self.clip_volume.value()==100 else 'Adjusted'))

        else:
            self.clip_name.setText('No clip selected')
            self.overlay_opacity.setEnabled(False)
            self.overlay_opacity_label.setText('Select a V3 effect to adjust visibility')
    def on_visual_ready(self,path):
        # Only refresh when cached visuals are available; never on every video frame.
        if any(c['path']==path for c in self.clips):self.timeline.refresh()
    def import_media(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Import media','','Media (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mp3 *.wav *.m4a *.aac);;All files (*)')
        for p in paths:
            try:
                length,has_audio=probe(p);kind='audio' if Path(p).suffix.lower() in ('.mp3','.wav','.m4a','.aac') else 'video'
                self.media.append(dict(path=p,start=0.,end=length,audio=has_audio,kind=kind));self.visual_cache.request(p,kind);self.library.addItem(f'{Path(p).name}   •   {tc(length)}')
                if not self.clips and kind=='video':self.insert_source(self.media[-1],'V1',0)
            except Exception as e:QMessageBox.warning(self,'Import failed',str(e))
        self.capture_history()
        self.update_all()
    def remove_library_media(self):
        row=self.library.currentRow()
        if not 0<=row<len(self.media):
            QMessageBox.information(self,'Remove Media','Select a file in the Media Library first.')
            return
        item=self.media[row]
        path=item['path']
        used=sum(1 for c in self.clips if c.get('path')==path)
        message=f'Remove {Path(path).name} from the media library?'
        if used:
            message+=f'\\n\\nThis file is used by {used} timeline clip(s). Those clips will remain on the timeline.'
        message+='\\n\\nThe original file on disk will NOT be deleted.'
        if QMessageBox.question(self,'Remove Media',message,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:
            return
        self.media.pop(row)
        self.library.takeItem(row)
        if self.active_path and os.path.normcase(os.path.abspath(self.active_path))==os.path.normcase(os.path.abspath(path)) and not used:
            self.player.stop()
            self.active_path=None
        self.capture_history()
        self.update_all()
        self.note.setText(f'Removed {Path(path).name} from library (original file preserved).')

    def preview_library(self,item):
        idx=self.library.row(item)
        if idx>=0:self.player.setPlaybackRate(1.0);self.preview_source(self.media[idx]['path'],0,0)
    def preview_source(self,path,source_sec,timeline_sec,autoplay=False):
        path=os.path.abspath(path)
        self.preview_start=source_sec;self.preview_at=timeline_sec
        self.pending_seek_ms=max(0,round(source_sec*1000))
        self.play_when_ready=autoplay
        if self.active_path!=path or self.player.source().isEmpty():
            self.player.pause()
            self.active_path=path
            self.note.setText('Loading video: '+Path(path).name)
            self.player.setSource(QUrl.fromLocalFile(path))
        else:
            # Seeking to the current frame on every Play click can flush audio/video buffers.
            if abs(self.player.position()-self.pending_seek_ms)>180:
                self.apply_pending_seek()
            else:
                self.pending_seek_ms=None
            if autoplay:self.player.play()
    def apply_pending_seek(self):
        if self.pending_seek_ms is None:return
        if self.player.mediaStatus() in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia,QMediaPlayer.BufferingMedia):
            ms=self.pending_seek_ms;self.pending_seek_ms=None
            self.player.setPosition(ms)
    def on_media_status(self,status):
        if status in (QMediaPlayer.LoadedMedia,QMediaPlayer.BufferedMedia,QMediaPlayer.BufferingMedia):
            self.apply_pending_seek()
            if self.play_when_ready:
                self.play_when_ready=False
                self.player.play()
            else:self.note.setText('Video loaded — press Play to preview')
        elif status==QMediaPlayer.InvalidMedia:
            self.note.setText('Cannot decode video: '+self.player.errorString()+' — try H.264/AAC MP4')
        elif status==QMediaPlayer.LoadingMedia:
            self.note.setText('Loading video...')
    def on_playback_state(self,state):
        if state!=QMediaPlayer.PlayingState:
            self.stop_timeline_audio()
        else:
            self.sync_timeline_audio()
        if state==QMediaPlayer.PlayingState:self.note.setText('Playing video')
        elif state==QMediaPlayer.PausedState:self.note.setText('Paused')
    def insert_source(self,src,track,at):
        c=copy.deepcopy(src);c.update(track=track,at=max(0,at));self.clips.append(c);self.visual_cache.request(c['path'],c['kind']);self.selected=len(self.clips)-1
        self.playhead=c['at'];
        if c['kind']=='video':
            self.player.setPlaybackRate(c.get('speed',1.));self.preview_source(c['path'],c['start'],c['at'])
        self.update_all()
    def insert(self):
        row=self.library.currentRow()
        if row<0:QMessageBox.information(self,'Insert Clip','Select a media item in the library first.');return
        src=self.media[row];track=self.track
        if src['kind']=='audio' and track.startswith('V'):track='A2'
        if src['kind']=='video' and track.startswith('A'):QMessageBox.information(self,'Insert Clip','Select a video track for video footage.');return
        self.insert_source(src,track,self.playhead)
    def set_snap(self,enabled):
        self.timeline.snap_enabled=enabled
        self.note.setText('Timeline snapping '+('enabled' if enabled else 'disabled'))
    def timeline_dropped(self,index,t,track):
        if index<0 or index>=len(self.media):return
        src=self.media[index]
        if (src['kind'] in ('video','effect')) != track.startswith('V'):
            self.note.setText('Drop video onto V tracks and audio onto A tracks.');return
        self.insert_source(src,track,t)
        self.note.setText(f'Inserted {Path(src["path"]).name} on {track} at {tc(t)}')
    def timeline_moved(self,index,t,track):
        self.selected=index;self.track=track
        self.track_choice.blockSignals(True);self.track_choice.setCurrentIndex(TRACKS.index(track));self.track_choice.blockSignals(False)
        self.update_all()
        self.note.setText(f'Moved clip to {track} at {tc(t)}')
    def timeline_clicked(self,index,t,track):
        self.selected=index if index>=0 else None;self.track=track;self.track_choice.setCurrentIndex(TRACKS.index(track));
        if index<0:self.seek(t)
        else:
            c=self.selected_clip()
            if c and c['kind']=='video':
                self.playhead=max(c['at'],min(t,c['at']+duration(c)-.001))
                self.player.setPlaybackRate(c.get('speed',1.))
                source=c['start']+(self.playhead-c['at'])*c.get('speed',1.)
                self.preview_source(c['path'],source,self.playhead)
            self.update_all()
    def clip_at(self,t):
        candidates=[(i,c) for i,c in enumerate(self.clips) if c.get('kind')=='video' and c['track'].startswith('V') and c['at']<=t<c['at']+duration(c)]
        return max(candidates,key=lambda p:TRACKS.index(p[1]['track'])*-1) if candidates else (None,None)
    def seek(self,t):
        was_playing=self.player.playbackState()==QMediaPlayer.PlayingState
        self.playhead=max(0,min(self.total(),t));i,c=self.clip_at(self.playhead)
        if c:
            sec=c['start']+(self.playhead-c['at'])*c.get('speed',1.)
            self.player.setPlaybackRate(c.get('speed',1.));self.preview_source(c['path'],sec,self.playhead,autoplay=was_playing)
        else:self.player.pause()
        self.update_all()
        self.sync_timeline_audio()
    def on_position(self,ms):
        if self.player.playbackState()!=QMediaPlayer.PlayingState:return
        t=self.preview_at+(ms/1000-self.preview_start)/max(.01,self.player.playbackRate())
        if t<0:return
        self.playhead=min(self.total(),t)
        i,c=self.clip_at(self.playhead)
        if c is None or c['path']!=self.active_path:
            if c:
                self.player.setPlaybackRate(c.get('speed',1.));self.preview_source(c['path'],c['start']+(self.playhead-c['at'])*c.get('speed',1.),self.playhead,autoplay=True)
            else:self.player.pause()
        # Avoid rebuilding hundreds of timeline graphics items on every decoded frame.
        # Qt can emit positionChanged many times per second; limit UI refreshes.
        if ms-self.last_preview_ui_ms>=80 or ms<self.last_preview_ui_ms:
            self.last_preview_ui_ms=ms
            self.update_playback_ui()
            self.sync_timeline_audio()
    def update_playback_ui(self):
        total=self.total()
        self.timeline.move_playhead(self.playhead)
        stamp=f'{tc(self.playhead)} / {tc(total)}'
        self.time_label.setText(stamp);self.timeline_time.setText(stamp)
        self.scrub.blockSignals(True)
        self.scrub.setValue(round(10000*self.playhead/max(total,.001)))
        self.scrub.blockSignals(False)
        self.live_overlay.update()
    def stop_timeline_audio(self):
        for player, output in self.timeline_audio_players.values():
            if player.playbackState()==QMediaPlayer.PlayingState:
                player.pause()

    def sync_timeline_audio(self):
        """Play overlapping timeline audio while keeping the video as master clock.

        Audio tracks are independent of the video source. Video V1 audio is
        played by the main video player and must not be duplicated here.
        """
        playing=self.player.playbackState()==QMediaPlayer.PlayingState
        t=self.playhead
        active=set()
        for index,clip in enumerate(self.clips):
            if clip.get('kind')!='audio' or not clip.get('audio'):
                continue
            if not (clip['at']<=t<clip['at']+duration(clip)):
                continue
            key=id(clip)
            active.add(key)
            if key not in self.timeline_audio_players:
                player=QMediaPlayer(self)
                output=QAudioOutput(self)
                player.setAudioOutput(output)
                player.setSource(QUrl.fromLocalFile(os.path.abspath(clip['path'])))
                self.timeline_audio_players[key]=(player,output)
            player,output=self.timeline_audio_players[key]
            output.setVolume(min(1.0,max(0.0,float(clip.get('volume',1.0)))*(0.5 if clip.get('duck_music') else 1.0)*self.volume.value()/100.0))
            player.setPlaybackRate(float(clip.get('speed',1.0)))
            expected=int(1000*(clip['start']+(t-clip['at'])*float(clip.get('speed',1.0))))
            if abs(player.position()-expected)>250:
                player.setPosition(expected)
            if playing and player.playbackState()!=QMediaPlayer.PlayingState:
                player.play()
            elif not playing and player.playbackState()==QMediaPlayer.PlayingState:
                player.pause()
        for index,(player,output) in list(self.timeline_audio_players.items()):
            if index not in active:
                player.stop()
                player.deleteLater()
                output.deleteLater()
                del self.timeline_audio_players[index]
        # Video-source audio is scaled by its clip's own volume too.
        video_index,video=self.clip_at(t)
        gain=float(video.get('volume',1.0)) if video and video.get('audio') and video.get('track')=='V1' else 0.0
        self.audio.setVolume(min(1.0,max(0.0,gain)*self.volume.value()/100.0))

    def player_error(self,*_):self.note.setText('Playback error: '+self.player.errorString()+' • Try an H.264/AAC MP4.')
    def toggle(self):
        if self.player.playbackState()==QMediaPlayer.PlayingState:
            self.player.pause();return
        if not self.clips:
            self.note.setText('Import a video first');return
        if self.playhead>=self.total():self.seek(0)
        i,c=self.clip_at(self.playhead)
        if not c:
            self.note.setText('No video at playhead. Select a video clip.');return
        sec=c['start']+(self.playhead-c['at'])*c.get('speed',1.)
        self.player.setPlaybackRate(c.get('speed',1.));self.preview_source(c['path'],sec,self.playhead,autoplay=True)
    def change_clip_volume(self,percent):
        c=self.selected_clip()
        if c is None:return
        c['volume']=percent/100.0
        self.clip_volume_label.setText(f'{percent}% — ' + ('Muted' if percent==0 else 'Original' if percent==100 else 'Adjusted'))
        self.note.setText(f'Clip audio set to {percent}% for preview and export.')
        self.sync_timeline_audio()
    def set_clip_volume(self,percent):
        if self.selected_clip() is not None:self.clip_volume.setValue(percent)
    def selected_clip(self):return self.clips[self.selected] if self.selected is not None and self.selected<len(self.clips) else None
    def split(self):
        c=self.selected_clip()
        if not c: self.note.setText('Select a clip before splitting.');return
        offset=self.playhead-c['at']
        if offset<=.04 or offset>=duration(c)-.04:self.note.setText('Place playhead inside selected clip.');return
        other=copy.deepcopy(c);other['start']=c['start']+offset*c.get('speed',1.);other['at']=self.playhead;c['end']=other['start'];self.clips.insert(self.selected+1,other);self.selected+=1;self.update_all()
    def trim(self):
        c=self.selected_clip()
        if not c:return
        s,ok=QInputDialog.getDouble(self,'Trim clip','Source in (seconds)',c['start'],0,c['end']-.05,3)
        if not ok:return
        e,ok=QInputDialog.getDouble(self,'Trim clip','Source out (seconds)',c['end'],s+.05,86400,3)
        if ok:c['start']=s;c['end']=e;self.update_all()
    def set_in(self):
        c=self.selected_clip()
        if c and c['at']<=self.playhead<c['at']+duration(c)-.04:
            diff=self.playhead-c['at'];c['start']+=diff*c.get('speed',1.);c['at']=self.playhead;self.update_all()
    def set_out(self):
        c=self.selected_clip()
        if c and c['at']+.04<self.playhead<=c['at']+duration(c):c['end']=c['start']+(self.playhead-c['at'])*c.get('speed',1.);self.update_all()
    def extract(self):
        c=self.selected_clip()
        if c:self.library.setCurrentRow(next((i for i,m in enumerate(self.media) if m['path']==c['path']),-1));self.note.setText('Selected source clip in media library.')
    def duplicate(self):
        c=self.selected_clip()
        if c:
            d=copy.deepcopy(c);d['at']+=duration(c);self.clips.append(d);self.selected=len(self.clips)-1;self.update_all()
    def delete(self):
        if self.selected is not None and 0<=self.selected<len(self.clips):
            self.clips.pop(self.selected)
            self.selected=None
            self.player.pause()
            self.capture_history()
            self.update_all()
        elif self.library.hasFocus() and self.library.currentRow()>=0:
            self.remove_library_media()

    def change_track(self):
        c=self.selected_clip()
        if c:
            if c['kind']=='audio' and self.track.startswith('V'):return
            if c['kind']=='video' and self.track.startswith('A'):return
            c['track']=self.track;self.update_all()
    def set_speed(self,n):
        c=self.selected_clip()
        if not c:return
        n=max(.1,min(4.,float(n)))
        old=max(.1,float(c.get('speed',1.)))
        if abs(old-n)<.0001:return
        # Preserve the source frame under the playhead when changing rate.
        old_source=c['start']+(self.playhead-c['at'])*old
        was_playing=self.player.playbackState()==QMediaPlayer.PlayingState
        c['speed']=n
        # The clip duration changes with speed; keep the playhead inside it.
        new_end=c['at']+duration(c)
        self.playhead=max(c['at'],min(new_end, c['at']+(old_source-c['start'])/n))
        self.update_all()
        # Re-anchor source/timeline clocks: simply setting playbackRate while
        # playing leaves preview_start/preview_at tied to the old speed.
        if c['kind']=='video' and os.path.abspath(c['path'])==self.active_path:
            self.player.pause()
            self.player.setPlaybackRate(n)
            self.preview_source(c['path'],old_source,self.playhead,autoplay=was_playing)
        self.note.setText(f'Clip speed: {n:g}× • preview and export retimed')
    def adjust_speed(self,factor):
        c=self.selected_clip()
        if c:self.set_speed(max(.1,min(4.,c.get('speed',1.)*factor)))
    def change_speed(self,n):
        c=self.selected_clip()
        if c and abs(c.get('speed',1.)-n)>.001:self.set_speed(n)
    def change_position(self,n):
        c=self.selected_clip()
        if c:c['at']=n;self.update_all()
    def frame_zoom(self):
        self.timeline.scale=600
        self.update_all()
        self.timeline.centerOn(138+self.playhead*self.timeline.scale,170)
    def fit_timeline(self):
        usable=max(250,self.timeline.viewport().width()-160)
        self.timeline.scale=max(5,min(600,usable/max(1,self.total())))
        self.update_all()
    def zoom(self,n):self.timeline.scale=max(5,min(600,self.timeline.scale*n));self.update_all()
    def refresh_audio_devices(self):
        previous=self.audio.device().id() if not self.audio.device().isNull() else None
        self.output_choice.blockSignals(True)
        self.output_choice.clear()
        devices=QMediaDevices.audioOutputs()
        for device in devices:
            self.output_choice.addItem(device.description(),device)
        preferred=next((i for i,d in enumerate(devices) if d.id()==previous),-1)
        if preferred<0:
            default=QMediaDevices.defaultAudioOutput()
            preferred=next((i for i,d in enumerate(devices) if d.id()==default.id()),0)
        if devices:
            self.output_choice.setCurrentIndex(preferred)
            self.audio.setDevice(devices[preferred])
        else:
            self.note.setText('No audio output device found. Check Windows sound settings.')
        self.output_choice.blockSignals(False)

    def select_audio_device(self,index):
        device=self.output_choice.itemData(index) if index>=0 else None
        if device is not None:
            self.audio.setDevice(device)
            self.audio.setMuted(False)
            self.note.setText('Audio output: '+device.description())

    def fullscreen_preview(self):
        if self.fullscreen_window is not None:
            self.restore_preview()
            return
        # Move the SAME video widget into a separate fullscreen window so the
        # editor stays intact and Windows can minimize the preview independently.
        window=PreviewWindow(self.restore_preview)
        window.setWindowTitle('Eli Studio — Fullscreen Preview')
        window.setStyleSheet(f'background:{BG};color:{FG};')
        layout=QVBoxLayout(window);layout.setContentsMargins(4,4,4,4);layout.setSpacing(3)
        controls=QHBoxLayout()
        controls.addStretch()
        controls.addWidget(self.button('Minimize  —',window.showMinimized))
        controls.addWidget(self.button('Exit Fullscreen  Esc',self.restore_preview,True))
        layout.addLayout(controls)
        self.monitor_layout.removeWidget(self.monitor_host)
        self.monitor_host.setParent(window)
        layout.addWidget(self.monitor_host,1)
        self.player.setVideoOutput(self.video_sink)
        self.live_overlay.update()
        self.fullscreen_window=window
        for key in ('Escape','F11'):
            shortcut=QShortcut(QKeySequence(key),window)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(self.restore_preview)
        window.showFullScreen()
        window.raise_()

    def restore_preview(self):
        window=self.fullscreen_window
        if window is None:return
        self.fullscreen_window=None
        self.sfx_preview=QSoundEffect(self);self.sfx_preview.setVolume(.65)
        window.layout().removeWidget(self.monitor_host)
        self.monitor_host.setParent(self.centralWidget())
        self.monitor_layout.insertWidget(1,self.monitor_host,1)
        self.monitor_host.show()
        self.player.setVideoOutput(self.video_sink)
        self.live_overlay.update()
        window.allow_close=True
        window.close()
        self.activateWindow()

    def closeEvent(self,event):
        self.autosave_project()
        if self.fullscreen_window is not None:self.restore_preview()
        super().closeEvent(event)
    def export_video(self):
        if not self.clips:QMessageBox.information(self,'Export','Import and insert a video first.');return
        path,_=QFileDialog.getSaveFileName(self,'Export MP4','FragForge-export.mp4','MP4 (*.mp4)')
        if not path:return
        modes=['Auto (NVIDIA NVENC when available)', 'NVIDIA NVENC (GPU)', 'CPU x264']
        mode,ok=QInputDialog.getItem(self,'Export encoder','Video encoder:',modes,0,False)
        if not ok:return
        qualities=['Balanced', 'Fast', 'High quality']
        selected,ok=QInputDialog.getItem(self,'Export quality','Encoding quality:',qualities,0,False)
        if not ok:return
        encoder=['auto','nvenc','cpu'][modes.index(mode)]
        quality=['balanced','fast','quality'][qualities.index(selected)]
        resolutions=['720p (1280×720)','1080p (1920×1080)','1440p (2560×1440)','4K (3840×2160)']
        resolution,ok=QInputDialog.getItem(self,'Export resolution','Output resolution:',resolutions,1,False)
        if not ok:return
        fps_label,ok=QInputDialog.getItem(self,'Export frame rate','Frames per second:',['30','60'],1,False)
        if not ok:return
        width,height=[(1280,720),(1920,1080),(2560,1440),(3840,2160)][resolutions.index(resolution)]
        fps=int(fps_label)
        if encoder=='nvenc' and not nvenc_available():
            QMessageBox.warning(self,'NVENC unavailable','The NVIDIA hardware encoder is not available. Choose Auto or CPU.')
            return
        self.player.pause()
        self.export_started=time.monotonic()
        self.render_dialog=QDialog(self)
        self.render_dialog.setWindowTitle('Eli Studio — Rendering MP4')
        self.render_dialog.setMinimumWidth(420)
        layout=QVBoxLayout(self.render_dialog)
        self.render_status=QLabel('Encoding video and mixing audio...')
        self.render_bar=QProgressBar()
        self.render_bar.setRange(0,100)
        self.render_bar.setValue(0)
        layout.addWidget(self.render_status)
        layout.addWidget(self.render_bar)
        self.render_dialog.show()
        self.note.setText('Rendering with '+mode+'...')
        self.worker=ExportWorker(self.clips,path,encoder,quality,width,height,fps)
        def on_progress(percent):
            elapsed=int(time.monotonic()-self.export_started)
            self.render_bar.setValue(percent)
            self.render_status.setText(f'Rendering {percent}%  •  Elapsed {elapsed//60:02d}:{elapsed%60:02d}')
        def on_success(p):
            self.render_dialog.close()
            self.note.setText('Export complete and verified')
            QMessageBox.information(self,'Export complete','Verified MP4 saved to:\n'+p)
        def on_failure(msg):
            self.render_dialog.close()
            self.note.setText('Export failed')
            QMessageBox.critical(self,'Export error',msg)
        self.worker.progress.connect(on_progress)
        self.worker.success.connect(on_success)
        self.worker.failed.connect(on_failure)
        self.worker.start()

def main():
    app=QApplication([]);app.setStyle('Fusion');win=Editor();win.show();app.exec()
