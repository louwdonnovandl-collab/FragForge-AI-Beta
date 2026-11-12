"""Eli Studio current-V1 editing regression checks (Qt-free)."""
from pathlib import Path
from eli_v1_context import current_v1, revise_v1_timeline, source_paths


def scene(at,start,end,path='game.mp4',speed=1.,**props):
    return dict(at=at,start=start,end=end,path=path,speed=speed,
                kind='video',track='V1',audio=True,**props)


# The original 35-minute recording remains in the library, but Eli is allowed
# to use ONLY these manually retained scenes in their saved sequence.
clips=[scene(0,160,166,volume=.7,transition='fade',crossfade_seconds=.5),
       scene(6,10,18,volume=.4,transition='fade',crossfade_seconds=.5),
       scene(14,900,906,volume=.8,transition='fade',crossfade_seconds=.5,
             eli_end_fade=True),
       dict(kind='audio',track='A2',at=0,start=0,end=20,path='music.mp3')]
v1=current_v1(clips)
assert len(v1)==3
assert len(source_paths(v1))==1
segments,templates=revise_v1_timeline(v1,0)
assert [(a,b) for a,b,_ in segments]==[(160,166),(10,18),(900,906)]
assert [c['volume'] for c in templates]==[.7,.4,.8]
assert sum((b-a)/rate for a,b,rate in segments)==20

# Further shortening picks from the existing scenes, never source intervals
# that were removed from V1. Timeline order remains the current V1 order.
short,origin=revise_v1_timeline(v1,8,activity_peaks=[(902,30),(11,12)])
assert abs(sum((b-a)/rate for a,b,rate in short)-8)<.001
assert all(any(c['start']<=a<b<=c['end'] for c in v1)
           for a,b,_ in short)
assert [c['start'] for c in origin]==sorted(
    [c['start'] for c in origin],
    key=lambda x:[c['start'] for c in v1].index(x))

# Manual speeds are preserved unless the user explicitly requests a change.
speed_clips=[scene(0,40,50,speed=2.,transition='wipeleft')]
segments,templates=revise_v1_timeline(speed_clips,0)
assert segments==[(40.,50.,2.)]
assert templates[0]['transition']=='wipeleft'
segments,_=revise_v1_timeline(speed_clips,0,explicit_speed=1.)
assert segments==[(40.,50.,1.)]

# Two source files on V1 remain two source files; no silent substitution.
mixed=[scene(0,5,10,path='a.mp4'),scene(5,15,20,path='b.mp4')]
segments,templates=revise_v1_timeline(mixed,0)
assert [c['path'] for c in templates]==['a.mp4','b.mp4']

# Insufficient footage must stop, not revive deleted footage.
try:
    revise_v1_timeline(mixed,30)
    raise AssertionError('Should have rejected 30s request for 10s of kept footage')
except ValueError as exc:
    assert 'without restoring deleted scenes' in str(exc)

gui=Path(__file__).with_name('gui.py').read_text(encoding='utf-8')
for expected in ('def update_timeline_clock(self):',
                 'self.audio_sync_timer.timeout.connect(self.update_timeline_clock)',
                 'self._clock_last_source_change',
                 'v1_snapshot=current_v1(self.clips)',
                 'state[\'v1_templates\']=templates',
                 'current_v1(self.clips)!=v1_snapshot'):
    assert expected in gui, expected
print('PASS: V1-only Eli edits, retained manual scenes, speeds, audio isolation and playback clock')
