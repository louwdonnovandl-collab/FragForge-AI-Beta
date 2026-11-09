"""Eli Studio rendering regression test, run by the manual Windows build.

Uses generated color/audio samples to prove that scene crossfades are rendered
rather than merely appearing in an AI chat plan. No user footage is required.
"""
import array
import json
import math
import subprocess
import tempfile
from pathlib import Path

from media import binary, export_layers, eli_transition_profile


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError("Command failed: " + " ".join(args) + "\n" + p.stderr[-2000:])
    return p.stdout


def pixel(video, seconds):
    # A single scaled pixel is sufficient for synthetic solid-color inputs.
    p = subprocess.run(
        [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-ss", str(seconds), "-frames:v", "1", "-vf",
         "scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True)
    if p.returncode or len(p.stdout) != 3:
        raise AssertionError("Could not sample pixel at " + str(seconds)
                             + ": " + p.stderr.decode(errors="replace")[-900:])
    return tuple(p.stdout)


def audio_rms(video, seconds, duration=.15):
    p = subprocess.run(
        [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-ss", str(seconds), "-t", str(duration), "-vn", "-ac", "1",
         "-ar", "8000", "-f", "s16le", "-"], capture_output=True)
    if p.returncode or len(p.stdout) < 100:
        raise AssertionError("Could not sample audio: "
                             + p.stderr.decode(errors="replace")[-900:])
    samples = array.array("h")
    samples.frombytes(p.stdout)
    return math.sqrt(sum(int(x)**2 for x in samples) / len(samples))


def check():
    with tempfile.TemporaryDirectory(prefix="eli-xfade-test-") as temp:
        directory = Path(temp)
        clips = []
        for i, (name, hue) in enumerate(
                (("red", "red"), ("blue", "blue"), ("green", "green"))):
            source = directory / (name + ".mp4")
            run([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=" + hue + ":s=1280x720:r=30:d=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                 "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                 str(source)])
            clips.append(dict(
                path=str(source), start=1., end=3., at=2. * i, track="V1",
                kind="video", audio=True, speed=1., volume=1., fade=0.,
                effect="None", transition="fade", crossfade_seconds=.5,
                eli_auto_montage=True, eli_end_fade=(i == 2)))
        dest = directory / "test.mp4"
        export_layers(clips, str(dest), encoder="cpu", quality="fast",
                      width=1280, height=720, fps=30)
        data = json.loads(run([binary("ffprobe"), "-v", "error", "-show_entries",
                               "format=duration", "-of", "json", str(dest)]))
        length = float(data["format"]["duration"])
        if abs(length - 6.) > .08:
            raise AssertionError(f"Duration not six seconds: {length}")
        red = pixel(dest, 1.20)
        fade1 = pixel(dest, 1.75)
        blue = pixel(dest, 2.35)
        fade2 = pixel(dest, 3.75)
        green = pixel(dest, 4.35)
        final = pixel(dest, 5.93)
        print("Samples:", {"red":red, "fade1":fade1, "blue":blue,
                           "fade2":fade2, "green":green, "final":final},
              "duration:", length)
        if red[0] < 130 or red[2] > 90:
            raise AssertionError("First scene is not recognizably red")
        if blue[2] < 130 or blue[0] > 90:
            raise AssertionError("Second scene is not recognizably blue")
        if green[1] < 60 or green[0] > 90:
            raise AssertionError("Third scene is not recognizably green")
        if not (80 < fade1[0] < 190 and 80 < fade1[2] < 190
                and fade1[0] + fade1[2] > 200):
            raise AssertionError(
                "Opacity blend failed: scene A and B must each be ~50% "
                "visible at the crossfade midpoint, with no black flash")
        if not (fade2[1] > 35 and fade2[2] > 75
                and fade2[1] + fade2[2] > 125):
            raise AssertionError(
                "Opacity blend failed: blue and green must overlap without black")
        if max(final) > 40:
            raise AssertionError("Final image did not fade to black")
        decoded = subprocess.run(
            [binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
             "-sseof", "-0.15", "-i", str(dest), "-an",
             "-vf", "scale=8:8:flags=area,format=gray",
             "-f", "rawvideo", "-"], capture_output=True)
        assert decoded.returncode == 0 and len(decoded.stdout) >= 64, decoded.stderr
        assert max(decoded.stdout[-64:]) <= 42, "Last decoded frame is not black"
        earlier = audio_rms(dest, 5.10)
        later = audio_rms(dest, 5.82)
        print("Audio RMS at 5.10 and 5.82:", earlier, later)
        if later >= earlier * .5:
            raise AssertionError("Final audio fade is missing")
        print("ELI TRANSITIONS PASS: direct opacity blends (50/50 midpoint), "
              "black ending, audio fade, exact six-second output")
        adjacent=dict(clips[1], path=clips[0]['path'],start=3.,end=4.)
        joined=eli_transition_profile(clips[0],adjacent)
        assert joined['kind']=='join' and joined['overlap']==0., joined
        distinct=eli_transition_profile(clips[0],clips[1])
        assert distinct['kind']=='blend' and abs(distinct['overlap']-.5)<.001
        tiny=dict(clips[1], end=1.4)
        try:
            eli_transition_profile(clips[0],tiny)
        except ValueError as exc:
            assert 'clips at least' in str(exc), exc
        else:
            raise AssertionError("An undersized clip did not fail clearly")
        # Test the old silent-fallback failure mode explicitly.
        damaged = [dict(c) for c in clips]
        damaged[1].pop("crossfade_seconds")
        try:
            export_layers(damaged, str(directory / "bad.mp4"), encoder="cpu",
                          quality="fast")
        except ValueError as exc:
            if "smooth transitions" not in str(exc):
                raise
        else:
            raise AssertionError("Missing transition metadata was not rejected")


if __name__ == "__main__":
    check()
