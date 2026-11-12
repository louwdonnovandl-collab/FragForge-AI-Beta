"""Eli v1.0.38: evidence-first combat selection regression suite.

No local Ollama model is required for these synthetic deterministic checks.
Real gameplay visual recognition still needs separate user testing.
"""
from eli_combat_selection import select_combat_montage
from eli_combat_keys import combat_key_markers,build_key_scenes
from eli_action_reasoning import parse_sequence_reply,sequence_centers
from pathlib import Path
import ast

# Small vision models can emit explicit string booleans and percentages.
attack=parse_sequence_reply({'response':'{"action":"swinging_weapon",'
    '"confidence":"84%","visible_change":"true",'
    '"attacker_target_interaction":"yes"}'},
    15.,[14.25,15.,15.75])
assert attack['action']=='weapon_swing' and attack['combat_candidate']
assert abs(attack['confidence']-.84)<.001

# A still blood pool is not enough. Newly appearing splatter across multiple
# frames is a possible action marker, not a verified hit.
blood=parse_sequence_reply({'response':'{"action":"new_blood",'
    '"confidence":82,"visible_change":true,"new_blood_visible":true}'},
    18.,[17.25,18.,18.75])
assert blood['action']=='blood_change' and blood['combat_candidate']
fake=parse_sequence_reply({'response':'{"action":"new_blood",'
    '"confidence":.95,"visible_change":true,"new_blood_visible":false}'},
    20.,[19.25,20.,20.75])
assert fake['action']=='none' and not fake['combat_candidate']

# A follow-up motion sample is scheduled within the additive four-second
# window instead of scattering all checks >=12 seconds apart.
centers=sequence_centers(
    [{'time':22.,'event':'combat','confidence':.95}],
    [(22.,20.),(80.,7.),(145.,8.)],200.,12,None)
assert any(0<t-22.<4. for t in centers),centers

# Simulate one continuous high-importance fight, preserving 34 seconds rather
# than chopping it into uniform 4-second fragments.
actions=[dict(time=5.+i*3.2,kind='weapon_swing',confidence=.9,
              key_marker=True)
         for i in range(9)]
keys=build_key_scenes(actions,500.,target_seconds=60.,speed=1.)
assert len(keys)==1,keys
assert keys[0]['end']-keys[0]['start']>=34.,keys
selected,info=select_combat_montage(
    [(0.,500.,1.)],keys,
    [(t,10.) for t in range(10,490,27)],60.,1.)
assert abs(sum((b-a)/r for a,b,r in selected)-60.)<.08,selected
assert any(b-a>=34. for a,b,_ in selected),selected
assert info['action_seconds']>=34.,info
assert info['supporting_seconds']<30.,info

# Rejected scenes from trimmed V1 cannot be added back.
retained=build_key_scenes(
    [dict(time=41.,kind='punch',confidence=.95,key_marker=True)],
    500.,retained_ranges=[(40.,48.),(100.,200.)])
assert all(40<=item['start']<item['end']<=48. for item in retained),retained

gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
vision=Path(__file__).with_name('vision_director.py').read_text(encoding='utf-8')
ast.parse(gui);ast.parse(vision)
for expected in (
    'select_combat_montage(',
    "state['combat_evidence_plan']=report",
    'if edited_v1:',
    'allowed_ranges=current_ranges',
):
    assert expected in gui,expected
assert 'sequence_limit=min(20,max(2,budget//8))' in vision
print('PASS: temporal parsing, 4s followups, 34s fight preservation, V1 bounds')
