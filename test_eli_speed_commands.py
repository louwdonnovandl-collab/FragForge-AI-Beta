"""Regression checks for conversational speed / timing requests."""
from assistant_engine import interpret_request

for wording in (
    'make 60 second, edit speed x2, make transitions',
    'make a 60 second edit, speed 2x, make transitions',
    'make a 60 second edit at 2x speed with transitions',
    'make a 60 second edit, speed=2, make transitions',
    'make a 60 second edit, playback at 2 times, transitions',
    'make a 60 second edit, x2 playback, transitions',
):
    plan=interpret_request(wording)
    assert plan['target_seconds']==60.,(wording,plan)
    assert plan['requested_speed']==2.,(wording,plan)
    assert plan['explicit_speed'],(wording,plan)
    assert plan['explicit_crossfade'],(wording,plan)
    assert plan['transition_style']=='fade',(wording,plan)
    assert plan['crossfade_seconds']==.5,(wording,plan)
    assert not plan['music'],(wording,plan)

for wording in ('make 60 second video', 'make 60 second, 0.5 second transitions'):
    plan=interpret_request(wording)
    assert not plan['explicit_speed'],(wording,plan)


# Fades are a scene-editing instruction, not an ignorable decoration.
for wording in (
    'make 60 second montage at 2x speed, add fades',
    'make 60 second montage at 2x speed, smooth fades',
    'make 60 second montage at 2x speed, fade between scenes',
    'make 60 second montage at 2x speed, fades between cuts',
):
    plan=interpret_request(wording)
    assert plan['target_seconds']==60.,(wording,plan)
    assert plan['requested_speed']==2. and plan['explicit_speed'],(wording,plan)
    assert plan['explicit_crossfade'] and plan['transition_style']=='fade',(wording,plan)
    assert plan['crossfade_seconds']==.5,(wording,plan)

# Do not misread a final fade-to-black as a request for scene transitions.
end_only=interpret_request('Make a 60 second clip with a final fade to black')
assert end_only['explicit_end_fade'],end_only
assert not end_only['explicit_crossfade'],end_only
no_fade=interpret_request('Make a 60 second edit with no fades')
assert not no_fade['explicit_crossfade'],no_fade

print('PASS: 60s x2 speed commands preserve timing and transition intent')
