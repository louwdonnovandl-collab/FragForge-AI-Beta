"""Evidence-first gameplay recognition markers and Mr Director review communication.

Markers are candidates, not ground truth. Local corrections can be exported as
training labels; no model weights are changed automatically.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

VISUAL_EVENTS = {'combat', 'looting', 'walking', 'driving', 'menu', 'other',
                 'explosion', 'victory', 'defeat', 'quiet', 'unknown'}


def build_markers(vision_samples, audio_events, radius=3.0):
    """Fuse evidence without promoting volume spikes into specific sound claims."""
    markers = []
    for frame in vision_samples or []:
        event = str(frame.get('event', 'unknown')).lower()
        if event not in VISUAL_EVENTS:
            event = 'unknown'
        t = max(0., float(frame.get('time', 0)))
        confidence = max(0., min(1., float(frame.get('confidence', 0))))
        nearby = [a for a in (audio_events or []) if abs(float(a.get('time', -10000))-t) <= radius]
        markers.append({'time': round(t, 2), 'event': event,
                        'confidence': round(confidence, 3), 'source': 'vision',
                        'audio_correlated': bool(nearby), 'verified': False,
                        'note': 'Sampled frame; not proof of a kill or completed action'})
    for event in audio_events or []:
        t = max(0., float(event.get('time', 0)))
        # Audio transient means a sudden amplitude change, NOT a gunshot.
        markers.append({'time': round(t, 2), 'event': 'audio_transient',
                        'confidence': None, 'strength': max(0., min(1., float(event.get('strength', 0)))),
                        'source': 'audio', 'audio_correlated': False, 'verified': False,
                        'note': 'Unclassified audio peak; requires listening or a sound classifier'})
    return sorted(markers, key=lambda item: (item['time'], item['source']))


def timecode(seconds):
    s = max(0, int(float(seconds)))
    return f'{s//3600:02}:{s//60%60:02}:{s%60:02}'


def director_report(markers, max_lines=25):
    visual = [m for m in markers if m['source'] == 'vision']
    audio = [m for m in markers if m['source'] == 'audio']
    combat = [m for m in visual if m['event'] == 'combat' and m['confidence'] >= .65]
    lines = ["MR DIRECTOR — GAMEPLAY RECOGNITION REVIEW",
             f"I sampled {len(visual)} gameplay frames and found {len(audio)} audio peaks.",
             f"I identified {len(combat)} possible combat moments. These are NOT verified kills.",
             "Audio peaks are not yet classified as gunshots, explosions or voices.",
             "Please check the timestamps and tell me which events are correct.", "", "CANDIDATE MARKERS"]
    for marker in markers[:max_lines]:
        confidence = f" ({marker['confidence']:.0%} model estimate)" if marker['confidence'] is not None else ''
        support = ' + nearby audio peak' if marker['source'] == 'vision' and marker['audio_correlated'] else ''
        lines.append(f"{timecode(marker['time'])}  {marker['event']}{confidence}{support}")
    if len(markers) > max_lines:
        lines.append(f"... {len(markers)-max_lines} more markers in the JSON report")
    return '\n'.join(lines)


def export_report(path, source_video, model, markers):
    """Save a reviewable, versioned report, never an automatically trained model."""
    payload = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
               'source_video': str(source_video), 'vision_model': str(model),
               'marker_count': len(markers), 'markers': markers,
               'review_status': 'unreviewed', 'training_applied': False}
    dest = Path(path)
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    return dest
