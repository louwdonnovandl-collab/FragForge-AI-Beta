"""Temporal action estimates for Eli Studio's local Ollama vision model.

Uses three ordered gameplay frames around a source timestamp. The model
estimates visible motion; it cannot certify a hit, gunshot sound, or kill.
All decisions are inspectable and user-reviewable, never ground truth.
"""
import json
import re

ACTION_TYPES=('gunfire','punch','kick','weapon_swing','shove','impact','none')
ACTION_ALIASES={
    'shooting':'gunfire','shot':'gunfire','gunshot':'gunfire',
    'firing':'gunfire','firearm':'gunfire',
    'punching':'punch','fist_strike':'punch',
    'kicking':'kick','leg_kick':'kick',
    'swing':'weapon_swing','swinging':'weapon_swing',
    'melee':'weapon_swing','melee_swing':'weapon_swing',
    'bat_swing':'weapon_swing','axe_swing':'weapon_swing',
    'pushing':'shove','push':'shove','grapple':'shove',
    'hit':'impact','contact':'impact','collision':'impact',
    'unknown':'none','other':'none','walking':'none',
}
ACTIVE_ACTIONS=set(ACTION_TYPES)-{'none'}


def parse_sequence_reply(response, center, frame_times):
    """Parse constrained action JSON, treating unsupported claims as none."""
    answer=str(response.get('response') or '').strip()
    if not answer:
        raise ValueError('No visible temporal action response')
    try:
        payload=json.loads(answer)
    except json.JSONDecodeError:
        match=re.search(r'\{[^{}]*\}',answer)
        if not match:raise ValueError('Vision model returned no action JSON')
        payload=json.loads(match.group(0))
    if not isinstance(payload,dict):
        raise ValueError('Vision model returned invalid action data')
    name=str(payload.get('action','none')).strip().lower().replace(' ','_').replace('-','_')
    name=ACTION_ALIASES.get(name,name)
    if name not in ACTION_TYPES:
        name='none'
    try:confidence=max(0.,min(1.,float(payload.get('confidence',0))))
    except (TypeError,ValueError):confidence=0.
    # An isolated screenshot is not an action. A temporal answer must explicitly
    # report a CHANGE across the ordered frames; the model may be uncertain.
    movement=payload.get('visible_change',False) is True
    # An impact is not specific combat unless the model explicitly reports
    # interaction between a character/weapon and a target across the frames.
    interaction=payload.get('attacker_target_interaction',False) is True
    if not movement or (name=='impact' and not interaction):
        name='none'
    return {
        'time':round(float(center),2),
        'frame_times':[round(float(t),2) for t in frame_times],
        'action':name,'confidence':round(confidence,3),
        'visible_change':movement,
        'attacker_target_interaction':interaction,
        'combat_candidate':bool(name in ACTIVE_ACTIONS and confidence>=.65),
        'audio_support':False,
        'evidence':'3 ordered gameplay frames; estimated motion, not verified combat outcome',
    }


def sequence_centers(samples,peaks,source_end,limit,reference=None):
    """Spread targeted temporal checks across the recording.

    Prioritize frame-based combat suggestions, then strong visual-activity
    peaks, using an optional known reference as a calibration point.
    The reference is NOT an automatically positive event.
    """
    limit=max(0,int(limit))
    if limit==0:return []
    end=max(.25,float(source_end))
    picks=[]
    def add(t):
        t=max(.8,min(end-.8,float(t)))
        if all(abs(t-old)>=12. for old in picks):
            picks.append(t)
    if reference is not None:add(reference)
    strong=sorted(
        ((float(item['time']),float(item.get('confidence',0)))
         for item in samples if item.get('event')=='combat'),
        key=lambda x:-x[1])
    for t,_ in strong:
        if len(picks)>=limit:break
        add(t)
    # Visual activity is only a reason to inspect a region, not a claim of
    # combat. Diversity prevents checking six frames in the same fight.
    peak_list=sorted(((float(t),float(v)) for t,v in peaks),key=lambda x:-x[1])
    # Deduplicate into time buckets and rotate across the whole source.
    buckets=max(1,min(limit,6))
    for bucket in range(buckets):
        for t,v in peak_list:
            if min(buckets-1,int(t/end*buckets))==bucket:
                add(t)
                break
        if len(picks)>=limit:break
    for t,_ in peak_list:
        if len(picks)>=limit:break
        add(t)
    return sorted(picks[:limit])


def temporal_action_windows(sequences,source_end):
    """Return approximate action windows grounded in multi-frame comparisons."""
    end=float(source_end)
    valid=sorted(
        (sample for sample in sequences
         if sample.get('combat_candidate')
         and sample.get('action') in ACTIVE_ACTIONS
         and len(sample.get('frame_times',[]))>=2),
        key=lambda x:float(x['time']))
    windows=[]
    for item in valid:
        start=max(0.,min(float(x) for x in item['frame_times'])-2.)
        stop=min(end,max(float(x) for x in item['frame_times'])+3.)
        conf=float(item.get('confidence',0))
        if stop-start<1.:continue
        if windows and start<=windows[-1][1]+2.:
            a,b,old=windows[-1]
            windows[-1]=(a,max(b,stop),max(old,conf))
        else:
            windows.append((start,stop,conf))
    return windows


def merge_evidence_windows(*window_groups):
    """Union duplicate positive evidence so runtime is never double counted."""
    items=sorted((float(a),float(b),float(conf))
                 for group in window_groups for a,b,conf in group if b>a)
    result=[]
    for a,b,confidence in items:
        if result and a<=result[-1][1]+.15:
            start,finish,older=result[-1]
            result[-1]=(start,max(finish,b),max(older,confidence))
        else:
            result.append((a,b,confidence))
    return result


def corroborate_actions(sequences,audio_events,radius=2.):
    """Attach unclassified audio evidence, never hallucinate a gunshot/kill."""
    out=[]
    for sample in sequences:
        item=dict(sample);time=float(item['time'])
        item['audio_support']=any(
            abs(float(event.get('time',-99999))-time)<=radius
            for event in audio_events)
        out.append(item)
    return out
