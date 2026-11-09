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


def precision_montage(segments, peaks, target_seconds, speed=1.0, intro_seconds=0, combat_markers=()):
    """Select active excerpts for a duration-constrained montage.

    Activity peaks are visual-motion candidates, not confirmed kills. Returns
    (intro, main) with clips at the requested playback speed and a hard budget.
    """
    speed=max(.25,float(speed))
    budget=max(0.,float(target_seconds)-max(0.,float(intro_seconds)))
    eligible=[(float(a),float(b)) for a,b,_ in segments if b-a>.3]
    # For combat-focused requests, begin within a few seconds of the first
    # estimated fight instead of filling 20-30 seconds with earlier gameplay.
    # These are candidates, NOT verified kills.
    markers=sorted(float(t) for t in combat_markers)
    if markers:
        first_action=max(0.,markers[0]-3.*speed)
        eligible=[(max(a,first_action),b) for a,b in eligible
                  if b-max(a,first_action)>.3]
    if not eligible or budget<=0:return [],[]
    # Build complete activity sequences instead of cutting every marker into
    # fixed six-second chunks. Group nearby peaks and retain context on both sides.
    candidates=[]
    for a,b in eligible:
        local=sorted((float(t),float(score)) for t,score in peaks if a<=float(t)<b)
        groups=[]
        for t,score in local:
            if groups and t-groups[-1][-1][0]<=4.*speed:
                groups[-1].append((t,score))
            else:
                groups.append([(t,score)])
        for group in groups:
            first,last=group[0][0],group[-1][0]
            x=max(a,first-2.5*speed)
            y=min(b,last+2.*speed)
            # Long sequences remain variable-length; cap at 20 output seconds
            # to preserve variety in short montages.
            if y-x>20.*speed:
                y=x+20.*speed
            if y-x>.3:
                candidates.append((x,y,max(score for _,score in group)))
    candidates.sort(key=lambda item:(item[0],item[1]))
    merged=[]
    for a,b,score in candidates:
        if merged and a<=merged[-1][1]+.15:
            u,v,s=merged[-1]
            merged[-1]=(u,max(v,b),max(s,score))
        else:
            merged.append((a,b,score))
    candidates=merged
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
    # Preserve complete high-priority action moments whenever they fit.
    priority=sorted((c for c in candidates if c[2]>0),key=lambda c:-c[2])
    filler=sorted((c for c in candidates if c[2]<=0),key=lambda c:c[0])
    for a,b,_ in priority:
        length=(b-a)/speed
        if length<=remaining+.001:
            selected.append((a,b,speed));remaining-=length
    # If every candidate is longer than the entire budget, allow the best
    # partial candidate as a last resort, and disclose that it is unverified.
    if not selected and priority and remaining>.03:
        a,b,_=priority[0]
        take=min(b-a,remaining*speed)
        selected.append((a,a+take,speed));remaining-=take/speed
    if markers:
        # Never place unrelated source footage before the first selected
        # activity segment. Fill remaining runtime in short, nearby pieces.
        earliest=min((a for a,b,s in selected),default=eligible[0][0])
        chunks=[]
        for a,b,_ in filler:
            a=max(a,earliest)
            while b-a>.03:
                end=min(b,a+5.*speed)
                proximity=min((max(u-end,a-v,0.) for u,v,_ in selected),
                              default=0.)
                chunks.append((proximity,a,end))
                a=end
        chunks.sort(key=lambda item:(item[0],item[1]))
        for _,a,b in chunks:
            if remaining<=.03:break
            take=min(b-a,remaining*speed)
            if take>.03:
                selected.append((a,a+take,speed));remaining-=take/speed
    else:
        for a,b,_ in filler:
            if remaining<=.03:break
            take=min(b-a,remaining*speed)
            if take>.03:
                selected.append((a,a+take,speed));remaining-=take/speed
    # Keep duration validation strict; never claim a 60-second montage when
    # the available source cannot actually supply sixty seconds.
    if remaining>.03:
        for a,b,_ in priority:
            if any(not (b<=u or a>=v) for u,v,_ in selected):continue
            take=min(b-a,remaining*speed)
            if take>.03:
                selected.append((a,a+take,speed));remaining-=take/speed
            if remaining<=.03:break
            if remaining<=.03:break
    selected.sort(key=lambda x:x[0])
    # Duration is measured in output seconds after speed adjustment.
    # Prevent overlapping selected source intervals from double-counting footage.
    if abs(runtime(selected)-budget)>max(.15,min(1.,budget*.005)):
        return [],[]
    return [],selected
