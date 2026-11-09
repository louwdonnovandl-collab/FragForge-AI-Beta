"""Pure, testable timeline planning helpers. Activity is not semantic kill recognition."""

def runtime(segments):
    return sum((b-a)/max(.1,s) for a,b,s in segments)


def select_runtime(segments, target_seconds, quiet=(), reserve_intro=0):
    """Prefer active source spans while preserving chronological order.

    Source spans may be trimmed, but are never re-ordered. Returns a best-effort
    duration target; the intro is budgeted separately.
    """
    budget=max(0.,float(target_seconds)-reserve_intro)
    if not segments or budget<=0:return []
    if runtime(segments)<=budget:return list(segments)
    ranked=[]
    for i,(a,b,speed) in enumerate(segments):
        midpoint=(a+b)/2
        low_activity=any(x<=midpoint<y for x,y in quiet)
        # Active 1x spans rank above low-activity or accelerated spans.
        ranked.append((int(low_activity),int(speed>1),i))
    remaining=budget
    selected=[]
    for _,__,i in sorted(ranked):
        if remaining<.3:break
        a,b,speed=segments[i]
        take=min(b-a,remaining*speed)
        if take>=.3:
            selected.append((a,a+take,speed))
            remaining-=take/speed
    return sorted(selected,key=lambda c:c[0])


def intro_candidates(segments, seconds):
    """Choose distinct source excerpts as *unverified* action candidates."""
    if seconds<=0 or not segments:return []
    # Favor unaccelerated spans; spread picks over the recording.
    spans=[(a,b) for a,b,s in segments if s<=1.01 and b-a>=1.]
    if not spans:spans=[(a,b) for a,b,_ in segments if b-a>=1.]
    if not spans:return []
    clips=[];remaining=float(seconds)
    count=min(4,max(1,int(seconds/2.5)))
    for i in range(count):
        idx=min(len(spans)-1,int((i+.5)*len(spans)/count))
        a,b=spans[idx]
        take=min(b-a,remaining/(count-i))
        if take>0.1:clips.append((a,a+take,1.));remaining-=take
    if remaining>.1:
        # Reuse the longest candidate if necessary to meet the requested intro.
        a,b=max(spans,key=lambda ab:ab[1]-ab[0]);take=min(b-a,remaining)
        if take>.1:clips.append((a,a+take,1.))
    return clips


def ranked_activity_cues(peaks, timeline, min_gap=18., max_cues=18):
    """Map source-time activity peaks onto output timeline with reason and confidence.

    Timeline entries are (part, source_start, source_end, speed). Returns output
    seconds. Peak candidates are visual changes, NOT verified gameplay events.
    """
    candidates=[];position=0.
    for part,a,b,speed in timeline:
        length=(b-a)/max(.1,speed)
        if part=='main' and speed<=1.01:
            for source_time,contrast in peaks:
                if a+1.<=source_time<=b-1. and contrast>=4.:
                    candidates.append((position+(source_time-a)/speed,float(contrast),'visual activity peak'))
        position+=length
    chosen=[]
    for candidate in sorted(candidates,key=lambda item:-item[1]):
        if all(abs(candidate[0]-prior[0])>=min_gap for prior in chosen):
            chosen.append(candidate)
            if len(chosen)>=max_cues:break
    return sorted(chosen)

def intro_from_activity(segments, peaks, seconds):
    """Build an intro from visually active candidates, never call them kills."""
    if seconds<=0:return []
    usable=[]
    for t,contrast in sorted(peaks,key=lambda item:-item[1]):
        for a,b,s in segments:
            if s<=1.01 and a+1<=t<=b-1 and b-a>=2.:
                x=max(a,t-1.25);y=min(b,x+2.5)
                if y-x>=1. and all(abs(x-u)>5 for u,_,_ in usable):
                    usable.append((x,y,1.))
                break
        if len(usable)>=8:break
    if not usable:return intro_candidates(segments,seconds)
    selected=[];remaining=float(seconds)
    for a,b,s in usable:
        take=min(b-a,remaining)
        if take>.1:selected.append((a,a+take,1.));remaining-=take
        if remaining<=.1:break
    if remaining>.1:
        extra=intro_candidates(segments,remaining)
        selected.extend(extra)
    return selected


def precision_montage(segments, peaks, target_seconds, speed=1.0, intro_seconds=0):
    """Select active excerpts for a duration-constrained montage.

    Activity peaks are visual-motion candidates, not confirmed kills. Returns
    (intro, main) with clips at the requested playback speed and a hard budget.
    """
    speed=max(.25,float(speed))
    budget=max(0.,float(target_seconds)-max(0.,float(intro_seconds)))
    eligible=[(float(a),float(b)) for a,b,_ in segments if b-a>.3]
    if not eligible or budget<=0:return [],[]
    # Prefer windows surrounding high visual activity, with chronological output.
    candidates=[]
    for t,score in sorted(peaks,key=lambda x:-float(x[1])):
        for a,b in eligible:
            if a<=t<b:
                x=max(a,float(t)-3*speed);y=min(b,x+6*speed)
                if y-x>.3 and all(y<=u or x>=v for u,v,_ in candidates):
                    candidates.append((x,y,float(score)))
                break
    if not candidates:
        candidates=[(a,min(b,a+8*speed),0.) for a,b in eligible]
    # Fill all unused intervals, including partial gaps around activity peaks.
    # Old 8-second chunk rejection discarded entire chunks if a peak overlapped
    # even a fraction, causing false "insufficient footage" failures.
    occupied=sorted((a,b) for a,b,_ in candidates)
    for a,b in eligible:
        cursor=a
        for u,v in occupied:
            if v<=cursor or u>=b:continue
            if u>cursor+.03:candidates.append((cursor,min(u,b),0.))
            cursor=max(cursor,min(v,b))
            if cursor>=b:break
        if cursor<b-.03:candidates.append((cursor,b,0.))
    selected=[];remaining=budget
    for a,b,_ in sorted(candidates,key=lambda c:-c[2]):
        if remaining<=.03:break
        take=min(b-a,remaining*speed)
        if take>.03:
            selected.append((a,a+take,speed));remaining-=take/speed
    selected.sort(key=lambda x:x[0])
    # Duration is measured in output seconds after speed adjustment.
    # Prevent overlapping selected source intervals from double-counting footage.
    if abs(runtime(selected)-budget)>max(.15,min(1.,budget*.005)):
        return [],[]
    return [],selected
