"""Safe V1 ripple deletion for Eli Studio timelines.

Only V1 scene positions are rippled. Independent manual audio, overlays,
and other video tracks retain their positions. Eli-generated background
music is shortened to the new V1 ending to prevent an audio-only tail.
"""


def clip_seconds(clip):
    return max(0.0, (float(clip['end']) - float(clip['start'])) /
               max(.01, float(clip.get('speed', 1.0))))


def _is_v1_scene(clip):
    return clip.get('track') == 'V1' and clip.get('kind', 'video') == 'video'


def _trim_generated_music(clips):
    """Match only Eli's own generated soundtrack, not imported manual audio."""
    end = max((float(c['at']) + clip_seconds(c) for c in clips
               if _is_v1_scene(c)), default=0.0)
    if end <= 0:
        # A music track should not survive deletion of the last gameplay scene.
        clips[:] = [c for c in clips
                    if c.get('label') != 'Eli background music — selected from requested genre']
        return
    retained = []
    for c in clips:
        if c.get('label') != 'Eli background music — selected from requested genre':
            retained.append(c)
            continue
        at = float(c.get('at', 0.0))
        if at >= end - .00001:
            continue
        if at + clip_seconds(c) > end + .00001:
            copy = dict(c)
            copy['end'] = float(copy['start']) + max(0.0, end - at) * max(
                .01, float(copy.get('speed', 1.0)))
            retained.append(copy)
        else:
            retained.append(c)
    clips[:] = retained


def ripple_delete_v1(clips, selected_index):
    """Remove one timeline item; close the join only for V1 video scenes.

    The next V1 scene moves to the previous scene's endpoint (or 0 if
    deleting the first scene). Every later V1 scene receives the same
    shift, preserving downstream pacing, clip trims, speeds, and transition
    metadata. Returns the join position for an accurate preview seek.
    """
    if not 0 <= selected_index < len(clips):
        raise IndexError('Selected timeline clip no longer exists')
    removed = clips[selected_index]
    if not _is_v1_scene(removed):
        clips.pop(selected_index)
        return dict(ripple=False, seam=None, shift_seconds=0.0, moved=0)

    ordered = sorted(
        ((index, clip) for index, clip in enumerate(clips)
         if _is_v1_scene(clip)),
        key=lambda item: (float(item[1].get('at', 0.0)), item[0]))
    rank = next(i for i, (index, _) in enumerate(ordered)
                if index == selected_index)
    previous = ordered[rank - 1][1] if rank else None
    following = ordered[rank + 1][1] if rank + 1 < len(ordered) else None
    seam = (float(previous['at']) + clip_seconds(previous)
            if previous is not None else 0.0)
    shift = (float(following['at']) - seam
             if following is not None else 0.0)
    moved = 0
    if following is not None and abs(shift) > .000001:
        for _, clip in ordered[rank + 1:]:
            clip['at'] = max(0.0, round(float(clip['at']) - shift, 9))
            moved += 1

    # The last scene owns the optional 1-second video/audio final fade.
    if following is None and previous is not None and 'eli_end_fade' in removed:
        previous['eli_end_fade'] = bool(removed['eli_end_fade'])
    clips.pop(selected_index)
    _trim_generated_music(clips)
    return dict(ripple=True, seam=seam,
                shift_seconds=shift, moved=moved)
