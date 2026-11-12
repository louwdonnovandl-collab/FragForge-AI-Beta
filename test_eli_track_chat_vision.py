"""Regression checks for Eli track highlighting, chat send and scoped vision."""
from pathlib import Path
import ast
from vision_director import retained_sample_times, _in_ranges

ranges=[(100.,106.),(400.,410.),(900.,906.)]
times=retained_sample_times(ranges,48,[(102.,8.),(650.,99.),(902.,40.)])
assert times and all(_in_ranges(t,ranges) for t in times),times
assert any(100<=t<=106 for t in times)
assert any(400<=t<=410 for t in times)
assert any(900<=t<=906 for t in times)
assert not any(500<t<800 for t in times)

gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
vision=Path(__file__).with_name('vision_director.py').read_text(encoding='utf-8')
ast.parse(gui)
ast.parse(vision)
for required in (
    'track_picked=Signal(str)',
    'self.track_picked.emit(track)',
    'def select_timeline_track(self,track):',
    'self.timeline.selected_indices=set(self.track_selection)',
    'class EliMessageKeys(QObject):',
    'request.installEventFilter(self._eli_chat_key_filter)',
    'request.viewport().installEventFilter(self._eli_chat_key_filter)',
    'request.clear()',
    'self.allowed_ranges=list(allowed_ranges or ())',
    'allowed_ranges=current_ranges',
):
    assert required in gui,required
assert 'retained_sample_times(retained' in vision
assert 'if retained else initial_sample_times' in vision
print('PASS: track-wide highlighting, Enter/chat clear and V1-scope combat samples')
