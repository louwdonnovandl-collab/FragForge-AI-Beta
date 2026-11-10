import json
import os
import subprocess
import os
import tempfile
import json
import tempfile
import functools
from pathlib import Path
from eli_transition_palette import TRANSITION_STYLES


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


def eli_transition_profile(previous, following):
    """Plan a direct opacity dissolve, or join truly contiguous source frames.

    No fade through black. Full requested duration is mandatory for separate
    scenes; previously it was silently reduced around very short fragments.
    """
    def seconds(c):
        return (float(c['end'])-float(c['start']))/max(.01,float(c.get('speed',1.)))
    requested=float(following.get('crossfade_seconds',.5))
    same_file=(os.path.normcase(os.path.abspath(str(previous['path'])))
               ==os.path.normcase(os.path.abspath(str(following['path']))))
    continuous=(same_file
                and abs(float(previous['end'])-float(following['start']))<=.05
                and abs(float(previous.get('speed',1.))
                        -float(following.get('speed',1.)))<=.0001)
    if continuous:
        return {'kind':'join','overlap':0.,'preroll':0.,'freeze_pad':0.}
    mode=str(following.get('transition','fade')).lower()
    if mode=='cut':
        return {'kind':'cut','overlap':0.,'preroll':0.,'freeze_pad':0.}
    if mode not in TRANSITION_STYLES:
        raise ValueError('Unsupported Eli transition: '+mode)
    if requested<.05:
        raise ValueError('Separate Eli scenes require an opacity crossfade.')
    # A clip cannot support a full fade at both boundaries if it is
    # shorter than twice the requested transition window.
    if min(seconds(previous),seconds(following)) < requested*2-.005:
        raise ValueError(
            f'Eli needs clips at least {requested*2:g}s long for a full '
            f'{requested:g}s crossfade. Merge or replace a short scene. '
            'No hard-cut export was created.')
    speed=max(.01,float(following.get('speed',1.)))
    preroll=min(requested,max(0.,float(following['start']))/speed)
    return {'kind':'blend','overlap':requested,'preroll':preroll,
            'freeze_pad':max(0.,requested-preroll)}


def export_layers(clips, destination, encoder='auto', quality='balanced', progress=None, width=1280, height=720, fps=30):
    """Composite V1/V2/V3 and mix A1/A2 using FFmpeg; 1280x720/30fps."""
    if width not in (1280,1920,2560,3840) or height not in (720,1080,1440,2160) or fps not in (30,60):raise ValueError('Unsupported export settings')
    # Eli AI montages use FFmpeg's explicit xfade filter, not alpha overlays.
    # Each incoming source has a short pre-roll so the completed timeline
    # stays exactly as long as the approved edit (e.g. 60 seconds).
    clips = [dict(c) for c in clips]
    primary_pairs = sorted(
        ((i, c) for i, c in enumerate(clips)
         if c.get('track') == 'V1' and c.get('kind') != 'effect'),
        key=lambda item: float(item[1].get('at', 0)))
    primary = [c for _, c in primary_pairs]
    eli_requested = any('crossfade_seconds' in c or c.get('eli_end_fade')
                        or c.get('eli_auto_montage') for c in primary)
    # Saved Eli montages from v1.0.6+ may omit the explicit final flag.
    # Any Eli-generated montage still gets the standard last-second fade.
    eli_end_fade = bool(primary and (
        primary[-1].get('eli_end_fade') or primary[-1].get('eli_auto_montage')
        or 'crossfade_seconds' in primary[-1]))
    def clip_seconds(c):
        return (float(c['end']) - float(c['start'])) / max(.01, float(c.get('speed', 1.)))
    eli_montage = (
        len(primary) > 1 and eli_end_fade
        and all('crossfade_seconds' in c for c in primary)
        and all(str(c.get('transition', 'fade')).lower() in TRANSITION_STYLES
                or str(c.get('transition', 'fade')).lower()=='cut'
                for c in primary[1:])
        and abs(float(primary[0]['at'])) < .04
        and all(abs(float(b['at']) - float(a['at']) - clip_seconds(a)) < .04
                for a, b in zip(primary, primary[1:]))
        and all(clip_seconds(c) > .1 for c in primary))
    # Never silently render hard cuts when Eli promised crossfades.
    # Prior versions fell back to the legacy overlay path whenever a single
    # AI clip was missing metadata or an existing clip interrupted the sequence.
    if eli_requested and len(primary) > 1 and not eli_montage:
        raise ValueError(
            'Eli smooth transitions cannot be applied to this V1 timeline. '
            'The clips are not one continuous Eli montage, or one or more '
            'transition settings are missing. Reopen Eli, select Prepare Edit, '
            'enable Replace current timeline, approve the montage and export '
            'again. Existing edits were not changed.')
    if eli_montage:
        for previous, following in zip(primary, primary[1:]):
            transition=eli_transition_profile(previous,following)
            following['_eli_transition_kind']=transition['kind']
            following['_eli_overlap']=transition['overlap']
            following['_eli_preroll']=transition['preroll']
            following['_eli_freeze_pad']=transition['freeze_pad']
    else:
        # Preserve legacy/non-AI timeline behavior. Never change manual fades
        # or transitions just to create Eli's automatic montages.
        for c in primary:
            if 'crossfade_seconds' not in c:
                continue
            c['fade_in'] = 0.
            c['fade_out'] = 0.
            c['audio_fade_in'] = 0.
            c['audio_fade_out'] = 0.
        for previous, following in zip(primary, primary[1:]):
            if 'crossfade_seconds' not in following:
                continue
            boundary = float(following['at'])
            prev_end = float(previous['at']) + clip_seconds(previous)
            if (str(following.get('transition', 'fade')).lower() in ('cut', 'hard cut', 'none')
                    or abs(boundary - prev_end) > .04):
                continue
            rate = max(.01, float(following.get('speed', 1.)))
            overlap = min(max(0., float(following.get('crossfade_seconds', .5))),
                          clip_seconds(previous) / 2., clip_seconds(following) / 2.,
                          max(0., float(following['start'])) / rate, boundary)
            if overlap <= .02:
                continue
            following['start'] = float(following['start']) - overlap * rate
            following['at'] = boundary - overlap
            following['fade_in'] = overlap
            following['audio_fade_in'] = overlap
            previous['audio_fade_out'] = overlap
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
    # An Eli montage already consists of a full-frame xfade stream.
    # Avoid compositing it over a second full-frame base video, which can
    # obscure the intended fades or cause unwanted framesync behavior.
    parts = ([] if eli_montage else
             [f'color=c=black:s={width}x{height}:r={fps}:d={total:.6f},format=yuv420p[base]'])
    current = None if eli_montage else 'base'
    # Render AI-generated V1 scenes as one continuous xfade stream. Standard
    # manual V1/V2/V3 clips continue through the existing compositing path.
    if eli_montage:
        for i, c in primary_pairs:
            rate = max(.01, float(c.get('speed', 1.)))
            preroll = float(c.get('_eli_preroll', 0.))
            pad_head = float(c.get('_eli_freeze_pad', 0.))
            source_start = float(c['start']) - preroll * rate
            input_length = clip_seconds(c) + preroll
            effect = {'None': '', 'Grayscale': 'hue=s=0,',
                      'Warm': 'eq=saturation=1.12:gamma_r=1.08:gamma_b=0.94,',
                      'Cool': 'eq=saturation=1.06:gamma_b=1.1:gamma_r=0.94,',
                      'High Contrast': 'eq=contrast=1.3:saturation=1.1,'}.get(
                          c.get('effect', 'None'), '')
            freeze = (f'tpad=start_mode=clone:start_duration={pad_head:.6f},'
                      if pad_head > .001 else '')
            parts.append(
                f'[{i}:v]trim=start={source_start:.6f}:duration={input_length * rate:.6f},'
                f'setpts=(PTS-STARTPTS)/{rate:.6f},'
                f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                f'fps={fps},{effect}format=yuv420p,{freeze}'
                f'settb=AVTB,setpts=PTS-STARTPTS[eli_src_{i}]')
        label = f'eli_src_{primary_pairs[0][0]}'
        elapsed = clip_seconds(primary[0])
        for k, (i, c) in enumerate(primary_pairs[1:], 1):
            overlap = float(c['_eli_overlap'])
            if c.get('_eli_transition_kind') in ('join','cut'):
                # Same-source continuous footage is a join. A cut is allowed
                # ONLY if a user explicitly left that boundary unselected.
                parts.append(
                    f'[{label}][eli_src_{i}]concat=n=2:v=1:a=0[eli_merge_{k}]')
            else:
                parts.append(
                    f'[{label}][eli_src_{i}]'
                    f'xfade=transition={c["transition"]}:duration={overlap:.6f}:'
                    f'offset={max(0., elapsed - overlap):.6f}[eli_merge_{k}]')
            label = f'eli_merge_{k}'
            elapsed += clip_seconds(c)
        # Pad only rounding differences at the last frame. The composed video
        # and all additional layers keep the original approved timeline length.
        parts.append(
            f'[{label}]tpad=stop_mode=clone:stop_duration=0.10,'
            f'trim=duration={total:.6f},setpts=PTS-STARTPTS[eli_montage]')
        # Feed the crossfaded picture directly to the remaining overlay layers
        # and to the final whole-picture fade.
        current = 'eli_montage'
    ordered = sorted(enumerate(clips), key=lambda p: (int(p[1]['track'][1:]) if p[1]['track'].startswith('V') else 999))
    audio_labels = []
    for i,c in ordered:
        length=(c['end']-c['start'])/max(.01,float(c.get('speed',1.0)))
        if length <= .01:raise ValueError('A clip has an invalid trim range')
        if c['track'].startswith('V') and not (eli_montage and c in primary):
            effects={'None':'','Grayscale':'hue=s=0,','Warm':'eq=saturation=1.12:gamma_r=1.08:gamma_b=0.94,',
                     'Cool':'eq=saturation=1.06:gamma_b=1.1:gamma_r=0.94,',
                     'High Contrast':'eq=contrast=1.3:saturation=1.1,'}
            effect=effects.get(c.get('effect','None'),'')
            fade=max(0,min(float(c.get('fade',0.35 if c.get('transition','').lower() not in ('cut','hard cut','none') else 0)),length/2))
            fade_in=max(0.,min(float(c.get('fade_in',fade)),length/2))
            fade_out=max(0.,min(float(c.get('fade_out',fade)),length))
            fades=(f'fade=t=in:st=0:d={fade_in:.3f}:alpha=1,' if fade_in>.001 else '') + (f'fade=t=out:st={max(0,length-fade_out):.3f}:d={fade_out:.3f}:alpha=1,' if fade_out>.001 else '')
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
            # format=auto preserves the incoming RGBA alpha ramp; the default
            # overlay pixel format can flatten alpha and turn dissolves into cuts.
            parts.append(f'[{current}][v{i}]overlay=x=(W-w)/2+{x:.4f}:y=(H-h)/2+{y:.4f}:format=auto:eof_action=pass:shortest=0:enable=\'between(t,{c["at"]:.4f},{c["at"]+length:.4f})\'[{out}]' if c.get('kind')=='effect' else f'[{current}][v{i}]overlay=format=auto:eof_action=pass:shortest=0:enable=\'between(t,{c["at"]:.4f},{c["at"]+length:.4f})\'[{out}]')
            current=out
        if c.get('audio') and (c['track'].startswith('A') or c['track']=='V1'):
            preroll = float(c.get('_eli_preroll', 0.)) if eli_montage and c in primary else 0.
            delay = max(0, round((float(c['at']) - preroll) * 1000))
            audio_start = float(c['start']) - preroll * float(c.get('speed', 1.))
            audio_length = length + preroll
            rate=float(c.get('speed',1.))
            factors=[]
            while rate>2.0:factors.append(2.0);rate/=2.0
            while rate<.5:factors.append(.5);rate/=.5
            factors.append(rate)
            tempo=','.join(f'atempo={factor:.5f}' for factor in factors)
            fade=max(0,min(float(c.get('fade',0.35 if c.get('transition','').lower() not in ('cut','hard cut','none') else 0)),length/2))
            audio_in=max(0.,min(float(c.get('audio_fade_in',fade)),length/2))
            audio_out=max(0.,min(float(c.get('audio_fade_out',fade)),length))
            if eli_montage and c in primary:
                audio_in = preroll
                position = primary.index(c)
                audio_out = (float(primary[position + 1].get('_eli_overlap', 0.))
                             if position + 1 < len(primary) else 0.)
            afades=(f',afade=t=in:st=0:d={audio_in:.3f}' if audio_in>.001 else '') + (f',afade=t=out:st={max(0,length-audio_out):.3f}:d={audio_out:.3f}' if audio_out>.001 else '')
            gain=max(0.,min(2.,float(c.get('volume',1.0))))*(0.5 if c.get('duck_music') else 1.0)
            parts.append(f'[{i}:a]atrim=start={audio_start:.6f}:duration={audio_length*c.get("speed",1.):.6f},asetpts=PTS-STARTPTS,aresample=48000,{tempo}{afades},volume={gain:.4f},adelay={delay}|{delay}[a{i}]')
            audio_labels.append(f'[a{i}]')
    if eli_montage:
        expected_merges=sum(
            following.get('_eli_transition_kind')=='blend'
            for following in primary[1:])
        actual_merges = sum('xfade=transition=' in stage for stage in parts)
        if actual_merges != expected_merges:
            raise RuntimeError(
                f'Eli expected {expected_merges} direct opacity crossfades '
                f'but found {actual_merges} in the render graph; export stopped.')
    # Fade the finished picture, after all V1/V2/V3 layers have been combined.
    # Applies even to one-clip Eli montages; no reliance on a final-clip alpha.
    # Fading only the final clip previously left the full-frame image unchanged.
    end_fade = min(1., total) if eli_end_fade else 0.
    video_out = (f'fade=t=out:st={total-end_fade:.6f}:d={end_fade:.6f},'
                 if end_fade > .001 else '')
    parts.append(f'[{current}]format=yuv420p,{video_out}trim=duration={total:.6f}[vout]')
    if audio_labels:
        # The audio mixer may carry delayed PTS from individual gameplay clips.
        # Normalise the FINAL mixed stream to a zero-based 48 kHz sample clock,
        # then fade by sample index (not inherited timeline timestamps). This
        # guarantees that the last full second fades even when source clips
        # have discontinuous timestamps or different sample rates.
        audio_rate = 48000
        fade_start_sample = max(0, round((total - end_fade) * audio_rate))
        fade_sample_count = max(1, round(end_fade * audio_rate))
        audio_out = (f',afade=t=out:ss={fade_start_sample}:ns={fade_sample_count}'
                     if end_fade > .001 else '')
        parts.append(
            ''.join(audio_labels)
            + f'amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0:normalize=0,'
              f'alimiter=limit=0.95,aresample={audio_rate},'
              f'atrim=duration={total:.6f},asetpts=N/SR/TB{audio_out}[aout]')
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
        if eli_montage and abs(duration-total) > .15:
            raise RuntimeError(
                f'Eli render is {duration:.3f}s, expected {total:.3f}s. '
                'The incorrect export was not published.')
        if eli_end_fade:
            # Verify the final image in the ACTUAL encoded MP4 rather than
            # trusting the filter graph. This catches hidden black-fade failures.
            sample = subprocess.run(
                [binary('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                 '-sseof', '-0.15', '-i', temporary, '-an',
                 '-vf', 'scale=8:8:flags=area,format=gray',
                 '-f', 'rawvideo', '-'],
                capture_output=True, timeout=45,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if sample.returncode or len(sample.stdout)<64:
                raise RuntimeError(
                    'Could not validate Eli fade-to-black. Export not published. '
                    + sample.stderr.decode(errors='replace')[-300:])
            if max(sample.stdout[-64:])>42:
                raise RuntimeError(
                    'Last encoded video frame is not black. '
                    'Eli refused to publish an export without the final fade.')
        os.replace(temporary, dest_abs)
        if progress: progress(100)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
