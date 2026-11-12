"""Static regression checks for Windows-sized Eli Studio editor."""
import ast
from pathlib import Path

gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
ast.parse(gui)
for required in (
    'screen.availableGeometry()',
    'header_scroll=QScrollArea(root)',
    'header_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)',
    'header_scroll.setWidget(header_host)',
    'self.monitor_host.setMinimumSize(280,165)',
    'right.setMinimumWidth(245)',
    'top.setStretchFactor(1,4)',
    'self.timeline.setMinimumHeight(180)',
    'validate_edit_contract(',
    'plan_visible_montage(',
    "clip['eli_force_transition']=True",
):
    assert required in gui,required

print('PASS: syntax, bounded window, scrollable toolbar and edit contract integration')
