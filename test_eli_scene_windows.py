"""Eli Studio: scene-boundary estimates and doubled vision budgets."""
from ai_runtime import PROFILES
from vision_director import scene_windows, combat_windows
from director_executor import precision_montage, runtime

assert PROFILES['Eco']['max_frames']==24
assert PROFILES['Balanced']['max_frames']==48
assert PROFILES['Accelerated']['max_frames']==96

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
