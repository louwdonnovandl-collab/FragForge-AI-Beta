"""Eli Studio regression checks for combat priority and accurate runtime parsing."""
from assistant_engine import extract_output_duration, interpret_request
from editor_x_brain import parse_instruction, describe_intent
from director_executor import precision_montage, runtime

prompt = ("Create an exactly 60-second gaming highlight montage. "
          "Keep 2-3 seconds before combat, and 2 seconds after. "
          "Apply 0.5-second crossfades. Fade to black over the last 1-second. "
          "Keep original gameplay sound, do not add background music.")
plan = interpret_request(prompt)
intent = parse_instruction(prompt)
assert plan['target_seconds'] == 60., plan
assert intent.duration_seconds == 60, intent
assert not plan['music'], plan
assert intent.music_policy == 'none', intent
assert '60-second target' in describe_intent(intent)
assert '1-second target' not in describe_intent(intent)
assert extract_output_duration('Apply 0.5-second crossfades and a 1-second fade to black.') == 0
assert extract_output_duration('Create a 60-second video with 1-second end fade') == 60
assert extract_output_duration('Target 120 seconds, add a 2-second fade') == 120
assert extract_output_duration('Make a 1 minute montage with 0.5-second transitions') == 60
assert extract_output_duration('Add a 10-second intro only') == 0

# Recreate the failure described by the user: the first candidate occurs
# at 16m22s, but generic supporting footage exists at source time zero.
segments = [(0., 180., 1.), (300., 600., 1.), (900., 1300., 1.),
            (2300., 2500., 1.)]
combat = [982., 1039., 1099., 1337., 2345.]
# Include a strong visual marker near every estimated fight; still not kills.
peaks = [(v, 1000.) for v in combat]
_,clips = precision_montage(segments, peaks, 60., combat_markers=combat)
assert clips, 'Combat montage returned no scenes'
assert abs(runtime(clips)-60.) < .2, (runtime(clips), clips)
assert clips == sorted(clips, key=lambda x: x[0])
assert clips[0][0] >= 975., clips
assert any(a <= 982. <= b for a,b,_ in clips), clips
print('PASS: 60s combat montage begins near combat, not 29s idle footage')

# No combat markers: preserve general-purpose chronological behavior.
_,general = precision_montage([(0., 300., 1.)], [(50., 15.)], 60.)
assert general and abs(runtime(general)-60.) < .2, general
print('PASS: general montage and duration/chat parsing')

# The old parser was redefined later in the module and silently overrode
# the improved one. The source must contain exactly one definition.
import ast
from pathlib import Path
source_code=Path(__file__).with_name('assistant_engine.py').read_text(encoding='utf-8')
module=ast.parse(source_code)
assert sum(isinstance(n,ast.FunctionDef) and n.name=='interpret_request'
           for n in module.body)==1, 'Duplicate interpret_request overrides new behavior'
assert sum(isinstance(n,ast.FunctionDef) and n.name=='describe_plan'
           for n in module.body)==1, 'Duplicate describe_plan overrides request summary'
assert plan['combat_first'] and plan['focus_kills'], plan
assert plan['crossfade_seconds']==.5 and plan['end_fade_seconds']==1., plan
assert plan['max_noncombat_opening_seconds']==3., plan
assert plan['no_music'] and not plan['music'], plan
print('PASS: unique parser + explicit instruction-to-render parameters')
