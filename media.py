import json
import os
import subprocess
import os
import tempfile
import json
import tempfile
import functools
from pathlib import Path


def binary(name):
    import sys
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    local = root / (name + ('.exe' if os.name == 'nt' else ''))
    return str(local) if local.exists() else name


def probe(path):
    cmd = [binary('ffprobe'), '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', path]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    info = json.loads(p.stdout)
    return float(info['format']['duration']), any(s.get('codec_type') == 'audio' for s in info.get('streams', []))


def export(clips, destination, progress=None):
    if not clips:
        raise ValueError('Timeline is empty')
    with tempfile.TemporaryDirectory(prefix='fragforge_') as temp:
        parts = []
        for i, clip in enumerate(clips):
            out = str(Path(temp) / f'part_{i:04d}.mp4')
            length = clip['end'] - clip['start']
            if length <= 0.01:
                raise ValueError('A clip has no duration')
            args = [binary('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(clip['start']), '-i', clip['path']]
            if not clip['audio']:
                args += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
            args += ['-t', str(length), '-map', '0:v:0', '-map', '0:a:0' if clip['audio'] else '1:a:0',
                     '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p',
                     '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                     '-shortest', '-movflags', '+faststart', out]
            subprocess.run(args, check=True, capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            parts.append(out)
            if progress:
                progress(i + 1, len(clips) + 1)
        concat_file = Path(temp) / 'list.txt'
        concat_file.write_text(''.join("file '" + p.replace("'", "'\\''") + "'\n" for p in parts), encoding='utf-8')
        subprocess.run([binary('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file),
                        '-c', 'copy', '-movflags', '+faststart', destination], check=True, capture_output=True, text=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if progress:
            progress(len(clips) + 1, len(clips) + 1)


@functools.lru_cache(maxsize=1)
def nvenc_available():
    """Run an actual 1-frame hardware encode, not just an encoder-name check."""
    cmd = [binary('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
           '-i', 'color=c=black:s=128x72:r=30', '-frames:v', '1',
           '-c:v', 'h264_nvenc', '-f', 'null', '-']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def export_layers(clips, destination, encoder='auto', quality='balanced', progress=None, width=1280, height=720, fps=30):
    """Composite V1/V2/V3 and mix A1/A2 using FFmpeg; 1280x720/30fps."""
    if width not in (1280,1920,2560,3840) or height not in (720,1080,1440,2160) or fps not in (30,60):raise ValueError('Unsupported export settings')
    videos = [c for c in clips if c['track'].startswith('V')]
    if not videos:
        raise ValueError('Add a video clip to V1, V2 or V3 before exporting.')
    total = max(c['at'] + (c['end'] - c['start']) / max(.01,float(c.get('speed',1.0))) for c in clips)
    if total <= 0:
        raise ValueError('Timeline has no duration')
    cmd = [binary('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y']
    for c in clips:
        if c.get('kind')=='effect':cmd += ['-loop','1','-framerate',str(fps),'-t',str((c['end']-c['start'])/max(.01,float(c.get('speed',1.)))),'-i',c['path']]
        else:cmd += ['-i', c['path']]
    parts = [f'color=c=black:s={width}x{height}:r={fps}:d={total:.3f},format=yuv420p[base]']
    current = 'base'
    ordered = sorted(enumerate(clips), key=lambda p: (int(p[1]['track'][1:]) if p[1]['track'].startswith('V') else 999))
    audio_labels = []
    for i,c in ordered:
        length=(c['end']-c['start'])/max(.01,float(c.get('speed',1.0)))
        if length <= .01:raise ValueError('A clip has an invalid trim range')
        if c['track'].startswith('V'):
            effects={'None':'','Grayscale':'hue=s=0,','Warm':'eq=saturation=1.12:gamma_r=1.08:gamma_b=0.94,',
                     'Cool':'eq=saturation=1.06:gamma_b=1.1:gamma_r=0.94,',
                     'High Contrast':'eq=contrast=1.3:saturation=1.1,'}
            effect=effects.get(c.get('effect','None'),'')
            fade=max(0,min(float(c.get('fade',0)),length/2))
            fades=(f'fade=t=in:st=0:d={fade:.3f}:alpha=1,'
                   f'fade=t=out:st={max(0,length-fade):.3f}:d={fade:.3f}:alpha=1,') if fade>.001 else ''
            if c.get('kind')=='effect':
                opacity=max(0.0,min(1.0,float(c.get('opacity',1.0))))
                alpha=f'colorchannelmixer=aa={opacity:.4f},'
                factor=max(.1,min(3.,float(c.get('overlay_scale',1.0))))
                angle=float(c.get('overlay_rotation',0.))*3.141592653589793/180
                x=float(c.get('overlay_x',0.))*width/1280
                y=float(c.get('overlay_y',0.))*height/720
                transform=f'scale=iw*{factor:.5f}:ih*{factor:.5f},rotate={angle:.6f}:ow=rotw({angle:.6f}):oh=roth({angle:.6f}):c=none,'
                parts.append(f'[{i}:v]trim=duration={length:.4f},setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1,fps={fps},format=yuva420p,{transform}{alpha}{fades}setpts=PTS+{c["at"]:.4f}/TB[v{i}]')
            else:
                parts.append(f'[{i}:v]trim=start={c["start"]:.4f}:duration={length*c.get("speed",1.):.4f},setpts=(PTS-STARTPTS)/{c.get("speed",1.):.5f},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},{effect}format=yuva420p,{fades}setpts=PTS+{c["at"]:.4f}/TB[v{i}]')
            out=f'm{i}'
            parts.append(f'[{current}][v{i}]overlay=x=(W-w)/2+{x:.4f}:y=(H-h)/2+{y:.4f}:eof_action=pass:shortest=0:enable=\'between(t,{c["at"]:.4f},{c["at"]+length:.4f})\'[{out}]' if c.get('kind')=='effect' else f'[{current}][v{i}]overlay=eof_action=pass:shortest=0:enable=\'between(t,{c["at"]:.4f},{c["at"]+length:.4f})\'[{out}]')
            current=out
        if c.get('audio') and (c['track'].startswith('A') or c['track']=='V1'):
            delay=int(c['at']*1000)
            rate=float(c.get('speed',1.))
            factors=[]
            while rate>2.0:factors.append(2.0);rate/=2.0
            while rate<.5:factors.append(.5);rate/=.5
            factors.append(rate)
            tempo=','.join(f'atempo={factor:.5f}' for factor in factors)
            fade=max(0,min(float(c.get('fade',0)),length/2))
            afades=(f',afade=t=in:st=0:d={fade:.3f},afade=t=out:st={max(0,length-fade):.3f}:d={fade:.3f}') if fade>.001 else ''
            gain=max(0.,min(2.,float(c.get('volume',1.0))))*(0.5 if c.get('duck_music') else 1.0)
            parts.append(f'[{i}:a]atrim=start={c["start"]:.4f}:duration={length*c.get("speed",1.):.4f},asetpts=PTS-STARTPTS,aresample=48000,{tempo}{afades},volume={gain:.4f},adelay={delay}|{delay}[a{i}]')
            audio_labels.append(f'[a{i}]')
    parts.append(f'[{current}]format=yuv420p[vout]')
    if audio_labels:
        parts.append(''.join(audio_labels)+f'amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.95,atrim=duration={total:.4f}[aout]')
    cmd += ['-filter_complex',';'.join(parts),'-map','[vout]']
    if audio_labels:cmd += ['-map','[aout]','-c:a','aac','-b:a','192k']
    else:cmd += ['-an']
    cmd += ['-t', f'{total:.4f}']
    # Hardware encoding reduces CPU load during export. It does not control Qt preview decoding.
    use_nvenc = encoder != 'cpu' and nvenc_available()
    if encoder == 'nvenc' and not use_nvenc:
        raise RuntimeError('NVIDIA NVENC unavailable. Update the NVIDIA driver or choose Auto / CPU.')
    if use_nvenc:
        # Constant quality (CQ), variable bitrate; GPU encode, CPU-side layered filters.
        cq = {'fast': 26, 'balanced': 21, 'quality': 18}.get(quality, 21)
        video_args = ['-c:v', 'h264_nvenc', '-preset', 'p4' if quality == 'fast' else 'p5',
                      '-rc', 'vbr', '-cq', str(cq), '-b:v', '0']
    else:
        crf = {'fast': 24, 'balanced': 20, 'quality': 18}.get(quality, 20)
        video_args = ['-c:v', 'libx264', '-preset', 'veryfast' if quality == 'fast' else 'medium',
                      '-crf', str(crf)]
    # Never write directly to the final destination. Only publish a verified MP4.
    dest_abs = os.path.abspath(destination)
    out_dir = os.path.dirname(dest_abs)
    fd, temporary = tempfile.mkstemp(prefix='.fragforge-render-', suffix='.mp4', dir=out_dir)
    os.close(fd)
    def execute(arguments):
        command = arguments + ['-progress', 'pipe:1', '-nostats', temporary]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        errors = []
        import threading
        def collect_errors():
            errors.append(proc.stderr.read())
        reader = threading.Thread(target=collect_errors, daemon=True)
        reader.start()
        for line in proc.stdout:
            line = line.strip()
            if line.startswith('out_time_us=') or line.startswith('out_time_ms='):
                try:
                    microseconds = int(line.split('=', 1)[1])
                    if progress: progress(min(99, max(0, round(microseconds / (total * 10000)))))
                except (ValueError, ZeroDivisionError):
                    pass
        rc = proc.wait()
        reader.join(timeout=3)
        return rc, ''.join(errors)
    try:
        final = cmd + video_args + ['-pix_fmt', 'yuv420p', '-movflags', '+faststart']
        rc, err = execute(final)
        if rc and use_nvenc and encoder == 'auto':
            if progress: progress(0)
            crf = {'fast': 24, 'balanced': 20, 'quality': 18}.get(quality, 20)
            fallback = cmd + ['-c:v', 'libx264', '-preset', 'veryfast' if quality == 'fast' else 'medium',
                              '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
            rc, err = execute(fallback)
        if rc:
            raise RuntimeError(err[-3000:] or 'FFmpeg export failed')
        if not os.path.isfile(temporary) or os.path.getsize(temporary) < 1024:
            raise RuntimeError('Export produced an empty or incomplete MP4.')
        check = subprocess.run([binary('ffprobe'), '-v', 'error', '-show_entries',
                                'format=duration:stream=codec_type,codec_name',
                                '-of', 'json', temporary], capture_output=True, text=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if check.returncode:
            raise RuntimeError('Export validation failed: ' + check.stderr[-1000:])
        details = json.loads(check.stdout)
        streams = details.get('streams', [])
        duration = float(details.get('format', {}).get('duration', 0))
        if not any(st.get('codec_type') == 'video' and st.get('codec_name') == 'h264' for st in streams) or duration < 0.1:
            raise RuntimeError('Export validation failed: missing H.264 video or duration.')
        os.replace(temporary, dest_abs)
        if progress: progress(100)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
