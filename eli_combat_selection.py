"""Select actual combat-key scenes BEFORE generic activity filler.

All timestamps refer to the source recording and remain inside the footage
still available to Eli. We do not invent action labels from loudness/motion.
This module plans only: the existing V1 apply and transition paths are reused.
"""


def _length(segment):
    return (float(segment[1])-float(segment[0]))/float(segment[2])


def select_combat_montage(available, key_scenes, motion_peaks, target_seconds,
                          speed=1., minimum_shot=1.5):
    """Use longest/highest-evidence scenes first, then fill unused source.

    Unlike an equal-chunk montage, a 34-second fight can remain 34 seconds
    if the requested output duration allows it. Supporting footage is never
    called combat. Returns (segments, diagnostics).
    """
    rate=float(speed);target=float(target_seconds)
    if not .25<=rate<=8. or target<=0:raise ValueError('Invalid target or speed')
    spans=sorted((float(a),float(b)) for a,b,*_ in available if float(b)>float(a))
    if not spans:raise ValueError('No available source footage')
    source_budget=target*rate
    total=sum(b-a for a,b in spans)
    if total+0.05<source_budget:raise ValueError('Insufficient source footage')
    candidates=[]
    for scene in key_scenes or ():
        sa=float(scene['start']);sb=float(scene['end'])
        for a,b in spans:
            left=max(a,sa);right=min(b,sb)
            if right-left>=minimum_shot*rate:
                conf=float(scene.get('confidence',.65))
                events=int(scene.get('event_count',1))
                # Duration and repeated events matter, without forcing a
                # 34-second scene into 4-second slices.
                score=events*100+conf*25+(right-left)/rate
                candidates.append((score,left,right,events))

    ranked=sorted(candidates,key=lambda item:(-item[0],item[1]))
    chosen=[];remaining=source_budget
    for score,a,b,events in ranked:
        if remaining<minimum_shot*rate:break
        if any(not (b<=x+.1 or a>=y-.1) for x,y in chosen):continue
        length=min(b-a,remaining)
        if length<minimum_shot*rate:continue
        chosen.append((a,a+length))
        remaining-=length
    action_seconds=sum(b-a for a,b in chosen)/rate

    def free_spans():
        free=[]
        # Leave one source second between chosen scenes when possible.
        occupied=sorted(chosen)
        for a,b in spans:
            cursor=a
            for x,y in occupied:
                if y<=cursor or x>=b:continue
                right=min(b,max(a,x-1.))
                if right>cursor:free.append((cursor,right))
                cursor=max(cursor,min(b,y+1.))
                if cursor>=b:break
            if b>cursor:free.append((cursor,b))
        return free

    # Favor high-motion supporting scenes, without converting them into
    # fictitious attacks. Keep each such segment up to 12 output seconds.
    if remaining>.05:
        candidates=[]
        for a,b in free_spans():
            if b-a<.1:continue
            score=sum(float(s) for t,s in (motion_peaks or ()) if a<=float(t)<b)
            candidates.append((score,a,b))
        for _,a,b in sorted(candidates,key=lambda row:(-row[0],row[1])):
            if remaining<=.05:break
            while remaining>.05 and b-a>.05:
                take=min(b-a,remaining,12.*rate)
                if take<=.05:break
                chosen.append((a,a+take))
                remaining-=take
                a+=take
    if remaining>.06:
        raise ValueError(f'Only {target-remaining/rate:.2f}s available after retaining combat scenes')
    chosen.sort()
    # Merge contiguous filler to avoid repeated meaningless cuts.
    joined=[]
    for a,b in chosen:
        if joined and abs(a-joined[-1][1])<.04:
            joined[-1]=(joined[-1][0],b)
        else:joined.append((a,b))
    output=[(a,b,rate) for a,b in joined]
    if abs(sum(_length(row) for row in output)-target)>.08:
        raise ValueError('Generated montage does not match requested duration')
    return output,{
        'key_scenes_used':sum(1 for a,b in joined if any(
            a<scene['end'] and b>scene['start'] for scene in key_scenes or ())),
        'candidate_keys':len(key_scenes or ()),
        'action_seconds':round(action_seconds,2),
        'supporting_seconds':round(max(0.,target-action_seconds),2),
        'clips':len(output),'duration':round(target,2)}
