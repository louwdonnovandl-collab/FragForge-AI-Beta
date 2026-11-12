"""Current-V1-aware source selection for Eli Studio.

Every suggested source window is intersected with footage still represented on
V1. Manual cuts, trims and scene reorders remain constraints on subsequent Eli
edits. These functions never operate on the original media-library inventory.
"""
import copy
import os


EPS=0.00001


def clip_seconds(clip):
    return max(0., (float(clip['end'])-float(clip['start'])) /
               max(.01, float(clip.get('speed',1.))))


def current_v1(clips):
    return [copy.deepcopy(c) for _,c in sorted(
        ((i,c) for i,c in enumerate(clips)
         if c.get('track')=='V1' and c.get('kind')=='video'),
        key=lambda pair:(float(pair[1].get('at',0.)),pair[0]))]


def source_paths(clips):
    return {os.path.normcase(os.path.abspath(str(c['path']))) for c in clips}


def restrict_segments_to_v1(segments, v1):
    """Intersect source-time spans with the already-retained V1 footage.

    A source interval previously deleted or trimmed away cannot be planned
    again. Keep distinct manual clip boundaries instead of merging them.
    """
    output=[]
    for c in v1:
        left=float(c['start']); right=float(c['end'])
        for a,b,rate in segments:
            x=max(float(a),left);y=min(float(b),right)
            if y-x>.30:
                output.append((x,y,float(rate)))
    return output


def align_plan_to_v1(segments,v1,explicit_speed=False,preserve_order=True):
    """Return scene fragments and their originating manual V1 templates.

    The plan must be COMPLETELY covered by existing V1 source spans. Planned
    slices are divided at original manual edit boundaries and retain the
    original clip's volume, effects, transitions and speed unless explicitly
    overridden. No source footage is fabricated to satisfy an edit duration.
    """
    rows=[]
    for sequence,(a,b,rate) in enumerate(segments):
        a=float(a);b=float(b)
        if b-a<=EPS:continue
        coverage=[]
        for index,c in enumerate(v1):
            left=max(a,float(c['start']))
            right=min(b,float(c['end']))
            if right-left>EPS:
                coverage.append((left,right,index,c))
        # Do not silently fill or bridge parts the user removed.
        cursor=a
        for left,right,_,_ in sorted(coverage,key=lambda p:(p[0],-p[1])):
            if left>cursor+.03:
                raise ValueError('Eli tried to select source footage that is absent from V1')
            cursor=max(cursor,right)
            if cursor>=b-.03:break
        if cursor<b-.03:
            raise ValueError('Eli tried to restore a trimmed or deleted V1 scene')
        # A source range can occur twice in a timeline (intentional replay).
        # In that case prefer the earliest saved timeline occurrence; avoid
        # duplicating it without an explicit user instruction.
        taken=[]
        for left,right,index,c in sorted(coverage,key=lambda p:(p[0],p[2])):
            if any(left>=u-.001 and right<=v+.001 for u,v in taken):
                continue
            taken.append((left,right))
            chosen_rate=float(rate) if explicit_speed else float(c.get('speed',1.))
            if chosen_rate<=0:raise ValueError('V1 contains an invalid clip speed')
            rows.append((sequence,index,left,right,chosen_rate,copy.deepcopy(c)))
    if preserve_order:
        rows.sort(key=lambda row:(row[1],row[2],row[0]))
    else:
        rows.sort(key=lambda row:(row[0],row[2],row[1]))
    return ([(a,b,rate) for _,_,a,b,rate,_ in rows],
            [template for *_,template in rows])


def revise_v1_timeline(v1, target_seconds, activity_peaks=(),
                       focus_action=False, action_markers=(),
                       explicit_speed=None, prioritize_action=False):
    """Choose only already-present V1 scenes, retaining their sequence and data.

    Prefer complete scenes. Trim only the final chosen scene to meet an exact
    target. Scene boundaries and source trims are never expanded. Independent
    source clips and duplicate source references are supported.
    """
    if not v1:return [],[]
    rate_override = float(explicit_speed) if explicit_speed is not None else None
    if rate_override is not None and rate_override<=0:
        raise ValueError('Invalid requested playback speed')
    candidates=[]
    for index,c in enumerate(v1):
        speed=rate_override if rate_override is not None else max(.01,float(c.get('speed',1.)))
        playback=(float(c['end'])-float(c['start']))/speed
        if playback<.05:continue
        action=sum(float(c['start'])<=float(t)<=float(c['end'])
                   for t in action_markers if True)
        strength=sum(float(score) for t,score in activity_peaks
                     if float(c['start'])<=float(t)<float(c['end'])
                     and os.path.normcase(os.path.abspath(str(c['path'])))
                     ==os.path.normcase(os.path.abspath(str(v1[0]['path']))))
        priority=(10000*action if focus_action else 0)+strength
        candidates.append((index,c,speed,playback,priority,action))
    available=sum(x[3] for x in candidates)
    budget=float(target_seconds) if target_seconds and float(target_seconds)>0 else available
    if budget>available+.08:
        raise ValueError(
            f'The current V1 timeline has only {available:.2f}s of footage. '
            f'Cannot create a {budget:.2f}s edit without restoring deleted scenes.')
    if budget<=.05:return [],[]
    # Leave source order unchanged unless the request explicitly asks for
    # combat at the beginning, and then only reorder whole retained scenes.
    remaining=budget
    ranked=sorted(candidates,key=lambda x:(-x[4],x[0])) if budget<available-.08 else candidates
    chosen=[]
    for index,c,rate,length,priority,action in ranked:
        if remaining<=.03:break
        if length<=remaining+.02:
            chosen.append((index,c,rate,float(c['start']),float(c['end'])))
            remaining-=length
    if remaining>.04:
        # A single last clip may be trimmed; never fill with footage from
        # outside the existing manual trims.
        for index,c,rate,length,priority,action in ranked:
            if any(row[0]==index for row in chosen):continue
            amount=min(float(c['end'])-float(c['start']),remaining*rate)
            if amount>.03:
                chosen.append((index,c,rate,float(c['start']),float(c['start'])+amount))
                remaining-=amount/rate
                break
    if remaining>.08:
        raise ValueError('Unable to meet duration using only the existing V1 clips.')
    if prioritize_action and focus_action:
        chosen.sort(key=lambda row:(-int(any(float(row[3])<=float(t)<=float(row[4])
                                               for t in action_markers)),row[0]))
    else:
        chosen.sort(key=lambda row:row[0])
    segments=[(start,end,rate) for _,_,rate,start,end in chosen]
    templates=[copy.deepcopy(c) for _,c,_,_,_ in chosen]
    return segments,templates
