"""Regression checks for V1 ripple deletion. No Qt or FFmpeg required."""
from eli_timeline_ripple import ripple_delete_v1


def clip(at, length, track='V1', start=0, **flags):
    return dict(path='game.mp4',start=float(start),
                end=float(start+length),at=float(at),track=track,
                kind='video' if track.startswith('V') else 'audio',
                speed=1.,**flags)


# Close a middle edit, preserve cut options, and leave independent tracks alone.
clips=[clip(0,5,eli_auto_montage=True,crossfade_seconds=.5,transition='fade'),
       clip(5,5,eli_auto_montage=True,crossfade_seconds=.5,transition='fade'),
       clip(10,5,eli_auto_montage=True,crossfade_seconds=.5,transition='fade'),
       clip(15,5,eli_auto_montage=True,crossfade_seconds=.5,transition='fade',eli_end_fade=True),
       clip(4,2,track='V3'),
       clip(0,20,track='A2',label='User music')]
result=ripple_delete_v1(clips,1)
assert result['moved']==2 and result['seam']==5
assert [c['at'] for c in clips if c['track']=='V1']==[0,5,10]
assert clips[-1]['at']==0 and clips[-2]['at']==4
assert clips[1]['crossfade_seconds']==.5
assert [c for c in clips if c['track']=='V1'][-1]['eli_end_fade']

# First and final scene removal, including transfer of final fade.
clips=[clip(0,4),clip(4,6),clip(10,3,eli_end_fade=True)]
ripple_delete_v1(clips,0)
assert [c['at'] for c in clips]==[0,6]
ripple_delete_v1(clips,1)
assert len(clips)==1 and clips[0]['eli_end_fade']

# Preserve intentional gaps before the removed scene, but close the deleted
# scene and any gap after it in the affected V1 sequence.
clips=[clip(0,3),clip(6,2),clip(10,5),clip(15,2)]
ripple_delete_v1(clips,1)
assert [c['at'] for c in clips]==[0,3,8]

# Non-V1 deletions must not alter V1 positions.
clips=[clip(0,3),clip(3,4),clip(0,9,track='A1')]
assert not ripple_delete_v1(clips,2)['ripple']
assert [c['at'] for c in clips]==[0,3]

# Generated Eli music is shortened (not manual audio).
clips=[clip(0,5),clip(5,5),
       clip(0,10,track='A2',label='Eli background music — selected from requested genre'),
       clip(0,10,track='A1',label='Manual voice recording')]
ripple_delete_v1(clips,1)
assert [c['end'] for c in clips if c['track']=='A2']==[5]
assert [c['end'] for c in clips if c['track']=='A1']==[10]
print('PASS: V1 ripple delete, transitions, final fade, undo-safe data, music cleanup')
