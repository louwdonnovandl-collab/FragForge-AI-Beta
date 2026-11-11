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

# Regression: consecutive selected source segments should stay one shot.
_,joined=precision_montage(
    [(0.,13.,1.),(30.,52.,1.)],
    [(3.,1000.),(35.,1000.)],34.4,
    combat_markers=[3.],action_windows=[(0.,12.,.9),(30.,52.,.9)])
assert joined and abs(runtime(joined)-34.4)<.06,joined
assert len(joined)==2 and abs(joined[0][1]-12.4)<.06,joined
gui_source=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "def rendered_eli_preview(self):" in gui_source
assert "render_in_eli=self.button(" in gui_source
assert "preview_render=self.button(" in gui_source
print('PASS: contiguous fragments merged and Eli rendered preview is accessible')

# Deep-dive regression: strict combat edits must NEVER pad a 60-second edit
# with 52 seconds of moving/walking footage.
_,rejected=precision_montage(
    [(0.,180.,1.)],[(15.,900.),(90.,900.)],60.,
    combat_markers=[15.],action_windows=[(10.,18.,.9)],
    require_action=True)
assert rejected==[],rejected

# An evidence-only montage can reach the requested runtime using only
# separate combat windows, even when many unrelated high-motion peaks exist.
windows=[(10.,30.,.9),(100.,125.,.87),(145.,170.,.86)]
_,strict=precision_montage(
    [(0.,180.,1.)],[(i*3.,800.) for i in range(60)],60.,
    combat_markers=[12.,104.,148.],action_windows=windows,require_action=True)
assert strict and abs(runtime(strict)-60.)<.06,strict
assert all(any(x<=a<b<=y for x,y,_ in windows) for a,b,s in strict),strict
assert strict==sorted(strict,key=lambda row:row[0]),strict
print('PASS: combat-only montage uses only evidence-backed windows')

gui_source=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "require_action=strict_combat" in gui_source
assert "assistant_tabs.addTab(ai_mode_page,'Eli Settings')" in gui_source
assert "self._eli_settings_store=QSettings" in gui_source
assert 'self._eli_edit_vision_control=vision_detail' in gui_source
print('PASS: Eli vision detail is saved in Settings and used in analysis')

# A recognized short montage may be replanned from cached evidence; 120s
# cannot silently override a user-selected shorter duration.
source_gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "reference_time=reference)" in source_gui
assert "target_duration.setValue(seconds)" in source_gui
assert "analyzed(cuts)  # Replan using cached evidence" in source_gui
assert "status.setWordWrap(True)" in source_gui
assert "'selected_target_seconds':float(target_duration.value())" in source_gui
print('PASS: user-selected duration, readable warning, and cached replan')


# Request semantics: prioritize means rank first, never prohibit filler.
priority=interpret_request(
    'make a 10 minute edit, prioritize combat, add ripple transition '
    'between cuts at 1 second fades')
assert priority['target_seconds']==600.,priority
assert priority['focus_kills'] and priority['combat_first'],priority
assert not priority['combat_only'],priority
assert priority['explicit_crossfade'],priority
assert priority['transition_style']=='radial',priority
assert abs(priority['crossfade_seconds']-1.)<.001,priority
assert not priority['explicit_end_fade'],priority
only=interpret_request('Make a 60-second edit, only combat, no filler footage')
assert only['combat_only'] and only['focus_kills'],only
general=interpret_request('Create a 20-minute gameplay video')
assert not general['focus_kills'] and not general['combat_only'],general
# Strict behavior remains available ONLY by explicit wording.
from local_director import chat_reply
ack=chat_reply('Make a 10 minute video and prioritize combat')
assert 'supporting scenes' in ack and 'combat only' not in ack,ack
# Source correctness: no default strict blocks for prioritized edits.
gui_text=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "pending.get('combat_only')" in gui_text
assert "opening_priority_markers=unverified_opening" in gui_text
assert "temporal_action_windows" in gui_text
assert "action_sequences=result.get('action_sequences',[])" in gui_text
print('PASS: 10-minute combat priority permits supporting scenes and temporal action evidence')

# Long-form regression: no 204 independent 4.5-second activity fragments.
from longform_scene_planner import plan_longform, duration as scene_duration
longsource=[(0.,2858.,1.)]
peaks=[(float(i)*12.+30.,8.) for i in range(1,200)]
quiet=[(float(i),float(i+14)) for i in range(70,2780,78)]
longedit,details=plan_longform(
    longsource,900.,activity_peaks=peaks,quiet=quiet,
    playback_speed=1.,explicit_speed=False)
assert longedit and abs(scene_duration(longedit)-900.)<.12,details
assert len(longedit)<45,(len(longedit),details)
assert all((b-a)/speed>12. for a,b,speed in longedit),longedit
assert details['retained_motion']>0,details
assert abs(details['retime_percent'])<=2.51,details
# With no quiet or marker-free gaps, a long continuous fight must not be cut
# into dozens of artificial 4.5-second pieces.
busy=[(float(i)*6.,10.) for i in range(1,100)]
no_safe,diagnostic=plan_longform(
    [(0.,600.,1.)],300.,activity_peaks=busy,quiet=[],
    playback_speed=1.,explicit_speed=False)
assert not no_safe and diagnostic['warning'],(no_safe,diagnostic)
# The UI must route 5-minute+ edits to this planner.
source_gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "if target_duration.value()>=300. and not strict_combat:" in source_gui
assert "segments,longform_report=plan_longform(" in source_gui
assert "longform_scene_planner" in source_gui
print('PASS: 15-minute edits use scene blocks instead of 4.5s motion slices')

# v1.0.21 regression: regular motion peaks can appear inside an otherwise
# low-motion interval. Quiet windows should remain eligible while true
# action evidence and audio spikes protect a cut.
from longform_scene_planner import _quiet_seam,_build_blocks
spikes=[float(i)*12.+30. for i in range(1,200)]
quiet_cut=_quiet_seam(70.,84.,0.,2858.,spikes,[],[])
assert quiet_cut is not None and 70.<quiet_cut<84.,quiet_cut
assert all(abs(quiet_cut-t)>=2.5 for t in spikes),quiet_cut
assert _quiet_seam(
    70.,84.,0.,2858.,spikes,[],[(69.,85.,.9)]) is None
assert _quiet_seam(
    70.,84.,0.,2858.,spikes,[72.,75.,78.,81.,84.],[]) is None
new_blocks,seams,_,_,_=_build_blocks(
    [(0.,2858.,1.)],peaks,quiet,[],[])
assert len(new_blocks)>=12,(len(new_blocks),seams[:10])
assert any(reason=='quiet' for _,reason in seams),seams[:10]
assert all((b-a)>12. for a,b,*_ in new_blocks),new_blocks
print('PASS: low-motion seams survive dense unverified spikes, actions remain protected')


# Regression: an estimated fight at 51.5 seconds must be moved near
# the beginning, not clear the edit and disable Apply selected edit.
from director_executor import prioritize_action_opening
original=[(0.,65.,1.),(90.,125.,1.),(160.,205.,1.)]
arranged,first=prioritize_action_opening(original,[51.5],3.)
assert first is not None and first<=3.0,(first,arranged)
assert abs(runtime(arranged)-runtime(original))<.001,arranged
assert arranged[0][0]<=51.5<=arranged[0][1],arranged
assert arranged[0][0]>40.,arranged
# Prioritize action, do not silently drop the early footage.
assert any(abs(a-0.)<.001 and abs(b-arranged[0][0])<.001
           for a,b,_ in arranged[1:]),arranged
# A scene already meeting the opening constraint remains unchanged.
unchanged,lead=prioritize_action_opening(
    [(40.,65.,1.),(90.,125.,1.)],[42.],3.)
assert unchanged==[(40.,65.,1.),(90.,125.,1.)] and lead==2.
# Missing evidence should not invent an action candidate.
missing,lead=prioritize_action_opening(original,[400.],3.)
assert missing==original and lead is None
gui_text=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
assert "rearranged,first_match=prioritize_action_opening(" in gui_text
assert "Combat-first requirement failed — edit blocked." not in gui_text
print('PASS: later detected fight moves to opening without disabling Apply or losing footage')
