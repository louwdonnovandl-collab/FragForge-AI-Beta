"""Prevent fake edits that only change a recording's duration."""
from eli_edit_contract import plan_visible_montage, validate_edit_contract

spans=[(0.,600.,1.),(630.,1200.,1.)]
peaks=[(35.,12.),(160.,22.),(390.,18.),(710.,28.),(900.,16.),(1090.,17.)]
planned,report=plan_visible_montage(spans,peaks,60.,2.)
assert len(planned)>=2,(planned,report)
assert abs(sum((b-a)/s for a,b,s in planned)-60.)<.05
assert all(s==2. for a,b,s in planned)
assert any(y[0]-x[1]>=1. for x,y in zip(planned,planned[1:]))

clips=[]
position=0.
for i,(a,b,speed) in enumerate(planned):
    c=dict(path='recording.mp4',kind='video',track='V1',audio=True,
           start=a,end=b,at=position,speed=speed,
           transition='fade',crossfade_seconds=.5,
           eli_auto_montage=True,eli_force_transition=i>0)
    clips.append(c)
    position+=(b-a)/speed
assert validate_edit_contract(
    clips,60.,requested_speed=2.,transition_style='fade',
    transition_seconds=.5)==[]

# The exact user-reported failure must be rejected.
single=[dict(path='recording.mp4',kind='video',track='V1',start=0.,
             end=60.,at=0.,speed=1.)]
errors=validate_edit_contract(
    single,60.,requested_speed=2.,transition_style='fade',
    transition_seconds=.5)
assert any('only one scene' in e for e in errors),errors
assert any('not at 2' in e for e in errors),errors

# A contiguous source cut needs explicit force metadata: FFmpeg would
# otherwise join the frames instead of performing the chosen crossfade.
broken=[dict(c) for c in clips]
broken[1]['eli_force_transition']=False
assert any('transition' in e for e in validate_edit_contract(
    broken,60.,requested_speed=2.,transition_style='fade'))
# A one-shot recording with too little source footage cannot be invented.
try:
    plan_visible_montage([(0.,70.,1.)],peaks,60.,2.)
    raise AssertionError('Insufficient source was accepted')
except ValueError as exc:
    assert 'usable footage' in str(exc)
print('PASS: 60s 2x edit has separate scenes, real crossfades and strict checks')
