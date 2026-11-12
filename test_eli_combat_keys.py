"""Regression: every new combat action adds four seconds, NOT 2x."""
from eli_combat_keys import (
    initial_block_seconds, combat_key_markers, build_key_scenes, key_windows
)

assert [initial_block_seconds(t) for t in (60,120,180,240,300)] == [4,8,12,16,20]
def hit(t, kind='weapon_swing'):
    return dict(time=t,kind=kind,confidence=.9,key_marker=True)

# Each successive action arrives while a scene is still active.
events=[hit(1),hit(3,'gunfire'),hit(6,'impact'),hit(10,'kick')]
for count,expected in [(1,4.),(2,8.),(3,12.),(4,16.)]:
    scene=build_key_scenes(events[:count],100,60,1.)[0]
    assert scene['end']-scene['start']==expected,(count,scene)
    assert scene['event_count']==count

# At 2x, still 4, 8, 12 OUTPUT seconds, represented in source seconds.
faster=[hit(2),hit(6,'gunfire'),hit(12,'kick')]
for count,expected_output in [(1,4.),(2,8.),(3,12.)]:
    scene=build_key_scenes(faster[:count],100,60,2.)[0]
    assert (scene['end']-scene['start'])/2==expected_output,scene

# A new action after the active scene ends starts another scene.
separated=build_key_scenes([hit(1),hit(20)],100,60)
assert len(separated)==2,separated
assert len(key_windows(separated))==2

# Retained V1 boundaries stop scenes: no rescanning deleted source spans.
restricted=build_key_scenes([hit(11),hit(20),hit(40)],100,60,
                             retained_ranges=[(10,17),(38,45)])
assert len(restricted)==2,restricted
assert restricted[0]['end']<=17 and restricted[1]['start']>=38,restricted

# A stationary blood stain cannot become a fight marker.
samples=[dict(time=1,event='other',blood_splatter=True,confidence=.95)]
assert not combat_key_markers(samples=samples)
series=[dict(time=3,action='blood_change',confidence=.9,
             frame_times=[2.2,3,3.8],visible_change=True)]
assert not combat_key_markers(sequences=series)
series[0]['new_blood_visible']=True
assert combat_key_markers(sequences=series)[0]['kind']=='blood_change'
print('PASS: additive 4+4+4 combat key scenes, longform increments, 2x output and bounds')
