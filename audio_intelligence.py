"""Editor-X lightweight, offline audio evidence and safe timeline policies.

Uses FFmpeg + Python standard library; does not claim semantic event recognition.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import array
import math
import shutil
import subprocess
import sys

@dataclass
class AudioWindow:
    start: float
    end: float
    rms_dbfs: float
    peak_dbfs: float
    silent: bool
    transient_candidate: bool


def analyze_audio(path, *, ffmpeg='ffmpeg', sample_rate=8000, window_seconds=.25,
                  silence_dbfs=-42.0, transient_rise_db=13.0, max_seconds=7200):
    """Measure audio loudness/silence/transient candidates; no speech/gunshot labels.

    Samples are decoded to mono 16-bit PCM. Uses a bounded streaming subprocess,
    so long recordings do not need to be loaded into memory.
    """
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    if not shutil.which(ffmpeg) and not Path(ffmpeg).is_file():
        raise FileNotFoundError(f'FFmpeg unavailable: {ffmpeg}')
    command=[ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(path),
             '-vn','-ac','1','-ar',str(sample_rate),'-f','s16le','-t',str(max_seconds),'pipe:1']
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    windows=[]
    block=max(1,int(sample_rate*window_seconds))*2
    prev_db=None
    try:
        while True:
            data=proc.stdout.read(block)
            if not data:break
            if len(data)%2:data=data[:-1]
            samples=array.array('h');samples.frombytes(data)
            if sys.byteorder!='little':samples.byteswap()
            if not samples:break
            rms=math.sqrt(sum(float(x)*x for x in samples)/len(samples))/32768
            peak=max(abs(x) for x in samples)/32768
            db=20*math.log10(max(rms,1e-9));peak_db=20*math.log10(max(peak,1e-9))
            start=windows[-1].end if windows else 0.0
            end=start+len(samples)/sample_rate
            windows.append(AudioWindow(round(start,3),round(end,3),round(db,2),
                                       round(peak_db,2),db<silence_dbfs,
                                       prev_db is not None and db-prev_db>=transient_rise_db and db>silence_dbfs))
            prev_db=db
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    return [asdict(w) for w in windows]


def suggest_audio_policy(clips):
    """Non-destructive diagnostics for Editor-X; never inserts SFX."""
    cues=[c for c in clips if c.get('auto_sfx') or 'transition cue' in str(c.get('label','')).lower() or 'activity cue' in str(c.get('label','')).lower()]
    return {'automatic_sfx_count':len(cues),
            'automatic_sfx_indices':[i for i,c in enumerate(clips) if c in cues],
            'cut_sfx_enabled':False,'event_sfx_enabled':False,
            'guidance':'No sound effects on cuts. Keep music continuous and use short fades on discontinuous gameplay audio.'}
