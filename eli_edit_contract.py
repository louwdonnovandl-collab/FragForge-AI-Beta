"""Eli Studio: verifiable multi-scene edits, not duration-only trims.

The scene planner works in SOURCE seconds on clean retained footage. It prefers
motion evidence across the recording and never labels activity as a verified kill.
"""
import math


def _clean_spans(segments):
    spans=[]
    for a,b,_ in sorted(segments,key=lambda row:float(row[0])):
        a,b=float(a),float(b)
        if b-a<.05:continue
        if spans and a<=spans[-1][1]+.07:
            spans[-1]=(spans[-1][0],max(spans[-1][1],b))
        else:
            spans.append((a,b))
    return spans


def _fits(spans, at, length):
    for left,right in spans:
        if left-.001<=at<=right+.001 and right-left+1e-5>=length:
            start=max(left,min(at-length*.38,right-length))
            return (start,start+length)
    return None


def plan_visible_montage(segments, peaks, target_seconds, speed,
                         max_scenes=6, min_gap=1.):
    """Create distinct, activity-guided scenes summing to an exact runtime.

    A crossfade between adjacent source frames is visually indistinguishable
    from the unedited recording. Prefer source-separated scenes. If the
    footage cannot supply at least two distinct scenes, refuse rather than
    announce that transitions were added.
    """
    target=float(target_seconds);rate=float(speed)
    if target<=0 or not .1<=rate<=8.:
        raise ValueError('A positive duration and playback speed are required')
    spans=_clean_spans(segments)
    total=sum(b-a for a,b in spans)
    required=target*rate
    if total<required-.05:
        raise ValueError(
            f'Only {total/rate:.1f}s of usable footage remains at {rate:g}×; '
            f'the requested edit needs {target:g}s.')
    if target<12.:
        raise ValueError('A montage with visible transitions needs at least 12 seconds')
    # Distribute selections over usable footage, not video timestamps,
    # so long loading screens cannot absorb an entire selection bucket.
    cum=[];pos=0.
    for a,b in spans:
        cum.append((pos,pos+(b-a),a,b))
        pos+=b-a
    def source_offset(t):
        for u,v,a,b in cum:
            if a<=t<=b:return u+(t-a)
        return None
    def to_source(offset):
        offset=max(0.,min(total-1e-6,offset))
        for u,v,a,b in cum:
            if u<=offset<v:return a+(offset-u)
        return spans[-1][1]-1e-6
    motion=[]
    for entry in peaks or ():
        try:
            t,score=float(entry[0]),float(entry[1])
        except (TypeError,ValueError,IndexError):
            continue
        offset=source_offset(t)
        if offset is not None:motion.append((offset,t,score))

    maximum=min(int(max_scenes),max(2,int(target//9)))
    desired=min(maximum,max(3,round(target/12.)))
    for count in range(desired,1,-1):
        clip_seconds=target/count*rate
        if clip_seconds<4.5*rate:continue
        chosen=[]
        for i in range(count):
            lo=total*i/count
            hi=total*(i+1)/count
            eligible=sorted((row for row in motion if lo<=row[0]<hi),
                            key=lambda row:(-row[2],abs(row[0]-(lo+hi)/2)))
            # Strong action within the time bucket first, followed by
            # quiet-scene-safe fallback points within the same bucket.
            trial=[t for _,t,_ in eligible[:40]]
            trial.extend(to_source(lo+(hi-lo)*f) for f in (.5,.33,.67,.18,.82))
            selected=None
            for t in trial:
                fit=_fits(spans,t,clip_seconds)
                if fit is None:continue
                a,b=fit
                if any(a<y+min_gap and b>x-min_gap for x,y in chosen):
                    continue
                selected=fit;break
            if selected is None:break
            chosen.append(selected)
        if len(chosen)!=count:continue
        chosen.sort()
        # Source-separated scenes must contain a real visual discontinuity.
        if not any(b[0]-a[1]>=min_gap-.02
                   for a,b in zip(chosen,chosen[1:])):
            continue
        planned=[(a,b,rate) for a,b in chosen]
        actual=sum((b-a)/rate for a,b,_ in planned)
        if abs(actual-target)>.05:
            continue
        return planned,dict(scenes=len(planned),duration=actual,
                            playback_speed=rate,source_seconds=required,
                            distinct_cuts=sum(y[0]-x[1]>=min_gap-.02
                                              for x,y in zip(chosen,chosen[1:])))
    raise ValueError(
        'Eli could not find two or more source-separated scenes for the '
        f'{target:g}s montage. Your V1 footage was not changed.')


def validate_edit_contract(clips, target_seconds=0., requested_speed=None,
                           transition_style=None, transition_seconds=.5):
    """Reject a duration-only edit when the user requested speed and fades."""
    videos=sorted(
        (c for c in clips if c.get('track')=='V1' and
         c.get('kind','video')=='video'),
        key=lambda c:float(c.get('at',0)))
    if not videos:return ['No scenes were applied to V1.']
    errors=[]
    def duration(c):
        return (float(c['end'])-float(c['start'])) / max(.01,float(c.get('speed',1.)))
    end=max(float(c['at'])+duration(c) for c in videos)
    if target_seconds and abs(end-float(target_seconds))>max(.15,min(1.,float(target_seconds)*.005)):
        errors.append(f'Timeline duration is {end:.2f}s instead of {target_seconds:g}s.')
    if requested_speed is not None:
        mismatched=[i for i,c in enumerate(videos,1)
                    if abs(float(c.get('speed',1.))-float(requested_speed))>.001]
        if mismatched:
            errors.append(f'{len(mismatched)} V1 scenes are not at {requested_speed:g}×.')
    if transition_style is not None:
        if len(videos)<2:
            errors.append('No transition can be applied: Eli created only one scene.')
        for previous,following in zip(videos,videos[1:]):
            if abs(float(following['at']) -
                   (float(previous['at'])+duration(previous)))>.05:
                errors.append('V1 scenes contain an unrenderable gap or overlap.')
                break
            if (str(following.get('transition','')).lower()!=str(transition_style).lower()
                or abs(float(following.get('crossfade_seconds',0.))-float(transition_seconds))>.015
                or not following.get('eli_force_transition')):
                errors.append('A requested scene transition was not assigned to V1.')
                break
    return errors
