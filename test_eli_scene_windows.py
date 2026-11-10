"""Eli Studio: scene-boundary estimates and doubled vision budgets."""
from ai_runtime import PROFILES
from vision_director import scene_windows, combat_windows
from director_executor import precision_montage, runtime

assert PROFILES['Eco']['max_frames']==48
assert PROFILES['Balanced']['max_frames']==96
assert PROFILES['Accelerated']['max_frames']==192

frames=[
    {'time':100.,'event':'walking','confidence':.9},
    {'time':103.,'event':'combat','confidence':.89},
    {'time':106.,'event':'combat','confidence':.93},
    {'time':109.,'event':'combat','confidence':.88},
    {'time':112.,'event':'walking','confidence':.9},
    {'time':150.,'event':'looting','confidence':.86},
    {'time':153.,'event':'looting','confidence':.82},
    {'time':156.,'event':'walking','confidence':.8},
]
fights=combat_windows(frames,200.)
assert len(fights)==1,fights
a,b,confidence=fights[0]
assert 99.<=a<=103. and 109.<=b<=114.,fights
assert confidence>=.9
loot=scene_windows(frames,200.,event='looting')
assert len(loot)==1 and loot[0][0]<=150. and loot[0][1]>=153.,loot
# The selection engine should use the estimated window as a high-priority
# span rather than the old fixed duration around one motion peak.
selected_source=[(0.,200.,1.)]
_,clips=precision_montage(selected_source,[(105.,30.),(162.,5.)],30.,
                          combat_markers=[106.],action_windows=fights)
assert clips and abs(runtime(clips)-30.)<.2,clips
assert any(s<=103. and e>=109. for s,e,_ in clips),clips
print('PASS: doubled frame profiles, combat/loot boundaries and clip selection')

# Motion-rich footage should spend part of the first pass on actual
# activity candidates rather than only evenly spaced timestamps.
from vision_director import initial_sample_times
peaks=[(100.+i*22.,100.-i) for i in range(20)]
coarse=initial_sample_times(2858.,64,peaks)
assert 1<=len(coarse)<=32,coarse
assert any(abs(t-100.)<=.01 for t in coarse),coarse
assert len(initial_sample_times(2858.,192,peaks))<=96
assert len(initial_sample_times(120.,32,()))<=16
gui_file=__import__('pathlib').Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "vision_detail.addItem('Smart — 64 frames (recommended)',64)" in gui_file
assert 'max_frames=int(vision_detail.currentData())' in gui_file
print('PASS: vision detail is adjustable and motion samples receive priority')

# Deep-dive regression: a lone high-confidence combat frame must NOT become
# an 18-second fight, nor should high-motion walking become a combat scene.
isolated=[
    {'time':50.,'event':'walking','confidence':.95},
    {'time':53.,'event':'combat','confidence':.99},
    {'time':56.,'event':'walking','confidence':.92}]
assert combat_windows(isolated,120.)==[],combat_windows(isolated,120.)
walking=[{'time':t,'event':'walking','confidence':.99}
         for t in (20.,21.5,23.,24.5,26.)]
assert combat_windows(walking,120.)==[]
confirmed=[
    {'time':98.,'event':'walking','confidence':.91},
    {'time':100.,'event':'combat','confidence':.81},
    {'time':101.5,'event':'combat','confidence':.90},
    {'time':103.,'event':'combat','confidence':.88},
    {'time':105.,'event':'walking','confidence':.94}]
fight=combat_windows(confirmed,120.)
assert len(fight)==1 and 98.<=fight[0][0]<=100. and 103.<=fight[0][1]<=105.,fight
print('PASS: combat scenes need multiple temporally adjacent frames')

# A user-provided fight is a sampling hint, never a forced recognition label.
from combat_calibration import (parse_reference_timecode,
                                 calibration_sample_times,
                                 calibration_report)
reference=parse_reference_timecode('14:49',2858.)
assert reference==889.
assert parse_reference_timecode('00:14:49',2858.)==889.
assert parse_reference_timecode('',2858.) is None
for invalid in ('14:99','67:88','00:14:99','bogus','50:00'):
    try:parse_reference_timecode(invalid,2858.)
    except ValueError:pass
    else:raise AssertionError('Accepted invalid calibration time: '+invalid)
calibration=calibration_sample_times(889.,2858.,12)
assert 1<=len(calibration)<=12,calibration
assert 889. in calibration
assert any(878.<t<889. for t in calibration)
assert any(889.<t<901. for t in calibration)
unrecognized=calibration_report(
    [{'time':t,'event':'walking','confidence':.95} for t in calibration],889.)
assert unrecognized['combat_frames']==0
assert not unrecognized['has_repeated_combat']
recognized=calibration_report(
    [{'time':888.,'event':'combat','confidence':.81},
     {'time':889.5,'event':'combat','confidence':.88}],889.)
assert recognized['has_repeated_combat']
print('PASS: benchmark timecodes and honest dense-scan diagnostics')


from eli_action_reasoning import (
    parse_sequence_reply,sequence_centers,temporal_action_windows,
    merge_evidence_windows,corroborate_actions)
import json
for label in ('gunfire','punch','kick','weapon_swing','shove','impact'):
    evidence=parse_sequence_reply(
        {'response':json.dumps({
            'action':label,'confidence':.83,'visible_change':True,
            'attacker_target_interaction':True})},
        889.,[888.25,889.,889.75])
    assert evidence['combat_candidate'] and evidence['action']==label,evidence
    assert evidence['frame_times']==[888.25,889.,889.75]
    estimated=temporal_action_windows([evidence],2858.)
    assert len(estimated)==1 and estimated[0][0]<889.<estimated[0][1]
# Walking, stationary poses and non-contact impact never become combat.
for payload in (
    {'action':'walking','confidence':.9,'visible_change':True},
    {'action':'gunfire','confidence':.9,'visible_change':False},
    {'action':'impact','confidence':.95,'visible_change':True,
     'attacker_target_interaction':False}):
    action=parse_sequence_reply(
        {'response':json.dumps(payload)},400.,[399.25,400.,400.75])
    assert not action['combat_candidate'],action
    assert not temporal_action_windows([action],2858.)
# Acoustic transient is corroboration ONLY, never a shooting label.
action=parse_sequence_reply(
    {'response':json.dumps({'action':'punch','confidence':.8,
                            'visible_change':True})},
    250.,[249.25,250.,250.75])
supported=corroborate_actions([action],[{'time':250.5,'strength':.7}])
assert supported[0]['audio_support']
centers=sequence_centers(
    [{'time':889.,'event':'combat','confidence':.85}],
    [(1300.,45.),(230.,35.),(2300.,40.),(30.,50.)],
    2858.,5,889.)
assert len(centers)<=5 and any(abs(t-889.)<1. for t in centers)
joined=merge_evidence_windows([(888.,894.,.75)],[(889.,895.,.87)])
assert len(joined)==1 and joined[0][0]==888. and joined[0][1]==895.
print('PASS: temporal combat actions, sequence budget, audio-only safeguards')
