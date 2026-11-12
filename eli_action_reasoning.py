"""Temporal action estimates for Eli Studio's local Ollama vision model.

Uses three ordered gameplay frames around a source timestamp. The model
estimates visible motion; it cannot certify a hit, gunshot sound, or kill.
All decisions are inspectable and user-reviewable, never ground truth.
"""
import json
import re

ACTION_TYPES=('gunfire','punch','kick','weapon_swing','shove','impact','explosion','blood_change','none')
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
    'weapon_attack':'weapon_swing','swinging_weapon':'weapon_swing',
    'swinging_an_object':'weapon_swing','bat_attack':'weapon_swing',
    'shoot':'gunfire','gun_shot':'gunfire','shooting_gun':'gunfire',
    'exploding':'explosion','explosive_blast':'explosion',
    'splatter':'blood_change','new_blood_splatter':'blood_change',
    'blast':'explosion','detonation':'explosion',
    'new_blood':'blood_change','blood_splatter_change':'blood_change',
    'unknown':'none','other':'none','walking':'none',
}
ACTIVE_ACTIONS=set(ACTION_TYPES)-{'none'}


def _model_bool(value):
    """Accept JSON booleans and explicit true/false strings from small VLMs."""
    if isinstance(value,bool):
        return value
    if isinstance(value,str):
        return value.strip().lower() in ('true','yes','1')
    return value == 1


def _model_confidence(value):
    """Normalize 0..1 or 0..100 numerical confidence; reject unknown values."""
    try:
        number=float(str(value).strip().rstrip('%'))
        if number>1. and number<=100.:
            number/=100.
        return max(0.,min(1.,number))
    except (TypeError,ValueError):
        return 0.


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
    name=str(payload.get('action') or payload.get('detected_action') or 'none').strip().lower().replace(' ','_').replace('-','_')
    name=ACTION_ALIASES.get(name,name)
    if name not in ACTION_TYPES:
        name='none'
    confidence=_model_confidence(payload.get('confidence',0))
    # An isolated screenshot is not an action. A temporal answer must explicitly
    # report a CHANGE across the ordered frames; the model may be uncertain.
    movement=_model_bool(payload.get('visible_change',False))
    # An impact is not specific combat unless the model explicitly reports
    # interaction between a character/weapon and a target across the frames.
    interaction=_model_bool(payload.get('attacker_target_interaction',False))
    new_blood=_model_bool(payload.get('new_blood_visible',False))
    if (not movement or (name=='impact' and not interaction)
            or (name=='blood_change' and not new_blood)):
        name='none'
    return {
        'time':round(float(center),2),
        'frame_times':[round(float(t),2) for t in frame_times],
        'action':name,'confidence':round(confidence,3),
        'visible_change':movement,
        'attacker_target_interaction':interaction,
        'new_blood_visible':new_blood,
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
    # Reserve one third of the action frames for repeated attacks in the
    # immediately following seconds rather than scattering every sample.
    initial_limit=max(1,(2*limit+2)//3)
    picks=[]
    def add(t,spacing=7.):
        t=max(.8,min(end-.8,float(t)))
        if all(abs(t-old)>=spacing for old in picks):
            picks.append(t)
    if reference is not None:add(reference)
    strong=sorted(
        ((float(item['time']),float(item.get('confidence',0)))
         for item in samples if item.get('event')=='combat'),
        key=lambda x:-x[1])
    for t,_ in strong:
        if len(picks)>=initial_limit:break
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
        if len(picks)>=initial_limit:break
    for t,_ in peak_list:
        if len(picks)>=initial_limit:break
        add(t)
    # Spend a share of the available three-frame checks just AFTER promising
    # actions to detect repeated hits within the same 4-second key scene.
    # The previous 12s spacing prevented any 4+4+4 grouping.
    anchors=list(picks)
    for anchor in anchors:
        if len(picks)>=limit:break
        add(anchor+2.8,spacing=1.8)
    for anchor in anchors:
        if len(picks)>=limit:break
        add(anchor+5.6,spacing=1.8)
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
