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

print('PASS: 60s x2 speed commands preserve timing and transition intent')
