"""FragForge v0.4: cross-platform FFmpeg editing engine (stdlib only)."""
import json
import math
import os
import sys
import shutil
import subprocess
from pathlib import Path


def binary(name):
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle:
        candidate = Path(bundle) / (name + '.exe' if os.name == 'nt' else name)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f'{name} not found. Install FFmpeg and ensure {name} is on PATH.')
    return found


def probe(path):
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    cmd = [binary('ffprobe'), '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(p)]
    info = json.loads(subprocess.check_output(cmd, text=True))
    duration = float(info.get('format', {}).get('duration', 0))
    streams = {s['codec_type'] for s in info.get('streams', [])}
    if duration <= 0 or 'video' not in streams:
        raise ValueError(f'Invalid video or duration: {p}')
    return {'duration': duration, 'audio': 'audio' in streams}


def build_command(clips, output, transition=0.35, fps=60, width=1920, height=1080, crf=20, preset='medium'):
    """Return ffmpeg argv; clips are {path,start,end}. Crossfade all adjacent clips."""
    if not clips:
        raise ValueError('At least one clip required')
    if not (0 <= transition <= 5):
        raise ValueError('Transition must be between 0 and 5 seconds')
    if fps not in (30, 60, 120):
        raise ValueError('FPS must be 30, 60, or 120')
    if (width, height) not in ((1280,720),(1920,1080),(2560,1440),(3840,2160)):
        raise ValueError('Unsupported resolution')
    if not (0 <= crf <= 51):
        raise ValueError('CRF must be 0..51')
    if preset not in ('ultrafast','veryfast','fast','medium','slow'):
        raise ValueError('Unsupported preset')
    argv = [binary('ffmpeg'), '-hide_banner', '-y']
    filters = []
    lengths = []
    for i, clip in enumerate(clips):
        start, end = float(clip['start']), float(clip['end'])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError(f'Invalid time range in clip {i}')
        length = end-start
        if transition and len(clips)>1 and length <= transition:
            raise ValueError(f'Clip {i} must be longer than transition')
        lengths.append(length)
        argv += ['-ss', str(start), '-t', str(length), '-i', str(clip['path'])]
        filters.append(f'[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS,fps={fps}[v{i}]')
        if clip.get('audio', True):
            filters.append(f'[{i}:a]aresample=48000:async=1:first_pts=0,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length},asetpts=PTS-STARTPTS[a{i}]')
    if len(clips)==1:
        vout,aout='v0','a0'
    elif transition == 0:
        joined=''.join(f'[v{i}][a{i}]' for i in range(len(clips)))
        filters.append(f'{joined}concat=n={len(clips)}:v=1:a=1[vout][aout]')
        vout,aout='vout','aout'
    else:
        vout,aout='v0','a0'
        cumulative=lengths[0]
        for i in range(1,len(clips)):
            nv,na=f'vx{i}',f'ax{i}'
            offset=max(0,cumulative-transition)
            filters.append(f'[{vout}][v{i}]xfade=transition=fade:duration={transition}:offset={offset:.6f}[{nv}]')
            filters.append(f'[{aout}][a{i}]acrossfade=d={transition}:c1=tri:c2=tri[{na}]')
            vout,aout=nv,na
            cumulative += lengths[i]-transition
    argv += ['-filter_complex',';'.join(filters),'-map',f'[{vout}]','-map',f'[{aout}]',
             '-c:v','libx264','-preset',preset,'-crf',str(crf),'-pix_fmt','yuv420p',
             '-r',str(fps),'-c:a','aac','-b:a','192k','-movflags','+faststart',str(output)]
    return argv


def render(clips, output, **options):
    out=Path(output)
    out.parent.mkdir(parents=True,exist_ok=True)
    if any(Path(c['path']).resolve()==out.resolve() for c in clips):
        raise ValueError('Output cannot overwrite an input clip')
    for c in clips:
        meta=probe(c['path'])
        if c['end'] > meta['duration'] + .05:
            raise ValueError(f"Clip end exceeds media duration: {c['path']}")
        c['audio']=meta['audio']
    command=build_command(clips,out,**options)
    subprocess.run(command,check=True)
    return probe(out)


def suggest_highlights(path, threshold=0.35, minimum_gap=2.0):
    """Free heuristic scene-change timestamps; not a trained AI model."""
    meta=probe(path)
    cmd=[binary('ffmpeg'),'-hide_banner','-i',str(path),'-vf',f"select='gt(scene,{threshold})',showinfo",'-an','-f','null','-']
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-1500:])
    import re
    times=[]
    for line in result.stderr.splitlines():
        if 'showinfo' not in line or 'pts_time:' not in line:
            continue
        match=re.search(r'pts_time:\s*([0-9.]+)',line)
        if match:
            t=float(match.group(1))
            if 0<t<meta['duration'] and (not times or t-times[-1]>=minimum_gap):
                times.append(round(t,2))
    return times
