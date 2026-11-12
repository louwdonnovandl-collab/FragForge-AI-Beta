"""Combat key markers with additive 4-second scene extension.

For a 60-second output, a key action starts a 4-second OUTPUT scene.
Each distinct subsequent action inside that active scene extends it by
another 4 seconds: 4 -> 8 -> 12 -> 16. NEVER exponential doubling.

For longer requested edits, the initial context grows by +4 seconds per
additional complete 60 seconds: 60s=4, 120s=8, 180s=12, 240s=16.
Repeated actions still extend the active scene by exactly +4 seconds.

These are candidate actions; no model output alone verifies a hit or kill.
"""
import math

KEY_ACTIONS = {'gunfire', 'punch', 'kick', 'weapon_swing', 'shove',
               'impact', 'explosion', 'blood_change'}
CONFIDENCE = .65
EXTENSION_SECONDS = 4.


def initial_block_seconds(target_seconds):
    """Add four seconds per 60 seconds of requested output, never double."""
    target = max(0., float(target_seconds or 60.))
    return 4. * max(1, int(math.ceil(target / 60.)))


def combat_key_markers(samples=(), sequences=(), user_times=(), audio_events=()):
    """Ground candidate key markers in temporal motion or repeated frames.

    A lone blood stain, static weapon, and unclassified loud sound do not
    establish a combat event. A newly appearing blood effect must be observed
    across multiple frames.
    """
    items = []
    audio = [float(e.get('time', -10000)) for e in audio_events or ()]

    def add(time, kind, confidence, source):
        t = max(0., float(time))
        items.append({
            'time': round(t, 3), 'kind': kind,
            'confidence': round(float(confidence), 3),
            'source': source, 'key_marker': True, 'verified': source == 'user',
            'audio_support': any(abs(t - s) <= 2. for s in audio)
        })

    for t in user_times or ():
        add(t, 'user_confirmed_combat', 1., 'user')
    for row in sequences or ():
        action = str(row.get('action', 'none')).lower()
        confidence = float(row.get('confidence', 0) or 0)
        if action not in KEY_ACTIONS or confidence < CONFIDENCE:
            continue
        if not row.get('visible_change') or len(row.get('frame_times', ())) < 2:
            continue
        if action == 'impact' and not row.get('attacker_target_interaction'):
            continue
        if action == 'blood_change' and not row.get('new_blood_visible'):
            continue
        add(row['time'], action, confidence, 'temporal_vision')

    positive = sorted(
        (float(row['time']), float(row.get('confidence', 0)))
        for row in samples or ()
        if row.get('event') == 'combat'
        and float(row.get('confidence', 0)) >= CONFIDENCE and 'time' in row
    )
    for i, (t, conf) in enumerate(positive):
        if ((i > 0 and t - positive[i-1][0] <= 5.)
                or (i + 1 < len(positive) and positive[i+1][0] - t <= 5.)):
            add(t, 'paired_combat_frames', conf, 'paired_frames')

    deduped = []
    for row in sorted(items, key=lambda item: (item['time'], -item['confidence'])):
        if deduped and row['time'] - deduped[-1]['time'] < .9:
            if row['confidence'] > deduped[-1]['confidence']:
                deduped[-1] = row
        else:
            deduped.append(row)
    return deduped


def build_key_scenes(markers, source_end, target_seconds=60., speed=1.,
                     retained_ranges=None, preroll_seconds=1.):
    """Build scenes extending by +4 output seconds per additional nearby hit.

    An event must fall in the current open scene to extend it. At 2x playback,
    a 4-second output extension consumes 8 seconds of source footage.
    """
    end = max(0., float(source_end))
    speed = float(speed)
    if not .1 <= speed <= 8.:
        raise ValueError('Invalid playback speed')
    base = initial_block_seconds(target_seconds) * speed
    addition = EXTENSION_SECONDS * speed
    ranges = ([(max(0., float(a)), min(end, float(b)))
               for a, b in retained_ranges]
              if retained_ranges is not None else [(0., end)])
    ranges = sorted((a, b) for a, b in ranges if b - a > .05)
    actions = sorted(
        (row for row in markers or () if row.get('key_marker')
         and math.isfinite(float(row.get('time', -1)))),
        key=lambda row: float(row['time'])
    )
    scenes = []
    for left, right in ranges:
        current = None
        previous_event = None
        for row in actions:
            t = float(row['time'])
            if not left <= t < right:
                continue
            if previous_event is not None and t - previous_event < .9:
                continue
            previous_event = t
            if current is not None and t <= current['end'] + .001:
                current['end'] = round(min(right, current['end'] + addition), 3)
                current['events'].append(str(row['kind']))
                current['event_count'] += 1
                current['confidence'] = max(current['confidence'],
                                            float(row['confidence']))
                continue
            start = max(left, t - max(0., float(preroll_seconds)) * speed)
            if right - left >= base:
                start = min(start, right - base)
            stop = min(right, start + base)
            if current is not None and start < current['end']:
                start = current['end']
                stop = min(right, start + base)
            if stop - start < .05:
                continue
            current = {
                'start': round(start, 3), 'end': round(stop, 3),
                'event_count': 1, 'events': [str(row['kind'])],
                'confidence': float(row['confidence']),
                'verified': False, 'retained_range': (left, right)
            }
            scenes.append(current)
    return scenes


def key_windows(scenes):
    return [(float(s['start']), float(s['end']), float(s['confidence']))
            for s in scenes if s['end'] > s['start']]
