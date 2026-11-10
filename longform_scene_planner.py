"""Long-form gameplay planner: whole scenes, not fixed 4.5-second peaks.

Motion and audio events are unverified editing cues. Scene boundaries are
chosen in quiet intervals away from activity; an uncuttable active stretch
is kept whole. No Ollama rescan is required to use this planner.
"""
import math


def duration(segments):
    return sum((b-a)/max(.01,rate) for a,b,rate in segments)


def _clean_ranges(segments):
    merged=[]
    for a,b,_ in sorted(segments):
        a=float(a);b=float(b)
        if b-a<.5:continue
        if merged and a<=merged[-1][1]+.07:
            merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else:
            merged.append((a,b))
    return merged


def _safe(t,motion,audio,actions):
    return (all(abs(t-x)>=9. for x in motion)
            and all(abs(t-x)>=3. for x in audio)
            and all(not a-5.<=t<=b+5. for a,b,_ in actions))


def _build_blocks(segments,peaks,quiet,audio_events,action_windows):
    motion=sorted((float(t),float(v)) for t,v in peaks if float(v)>=4.)
    sound=sorted((float(x['time']),float(x.get('strength',0)))
                 for x in audio_events if 'time' in x)
    action=sorted((float(a),float(b),float(conf))
                  for a,b,conf in action_windows if float(b)>float(a))
    times=[t for t,_ in motion]
    sounds=[t for t,_ in sound]
    blocks=[];available_cuts=[]
    for start,end in _clean_ranges(segments):
        # Quiet spans are the preferred editing seams; long gaps between
        # activity observations offer a secondary, lower-confidence seam.
        candidates={}
        for qa,qb in quiet:
            left=max(start,float(qa));right=min(end,float(qb))
            if right-left>=10.:
                t=(left+right)/2.
                if start+18.<t<end-18. and _safe(t,times,sounds,action):
                    candidates[round(t,2)]='quiet'
        timeline=sorted(set(t for t in times+sounds if start<t<end))
        for a,b in zip([start]+timeline,timeline+[end]):
            if b-a<42.:continue
            t=(a+b)/2.
            if start+18.<t<end-18. and _safe(t,times,sounds,action):
                candidates.setdefault(round(t,2),'activity gap')
        # Target a 60-90s scene, but never fabricate a cut when no safe seam
        # exists. This may leave long unbroken scenes in the plan.
        cuts=[start]
        cursor=start
        sorted_candidates=sorted(candidates)
        while end-cursor>120.:
            nearby=[t for t in sorted_candidates
                    if cursor+28.<=t<=min(end-18.,cursor+125.)]
            if not nearby:break
            chosen=min(nearby,key=lambda t:abs(t-(cursor+76.)))
            cuts.append(chosen);cursor=chosen
        cuts.append(end)
        if len(cuts)>2 and cuts[-1]-cuts[-2]<18.:
            cuts.pop(-2)
        for a,b in zip(cuts,cuts[1:]):
            if b-a<1.:continue
            events=sum(1 for x,y,_ in action if min(y,b)>max(x,a))
            motion_count=sum(1 for t,_ in motion if a<=t<b)
            sound_count=sum(1 for t,_ in sound if a<=t<b)
            score=(events*260. + motion_count*30. + sound_count*9.
                   +min(90.,b-a)*.28 - 15.)
            blocks.append((a,b,score,events,motion_count,sound_count))
        for t in cuts[1:-1]:
            available_cuts.append((t,candidates.get(round(t,2),'activity gap')))
    return blocks,available_cuts,motion,sound,action


def plan_longform(segments,target_seconds,activity_peaks=(),quiet=(),
                  audio_events=(),action_windows=(),playback_speed=1.,
                  explicit_speed=False,prefer_action=False):
    """Select complete segments for a 5-minute+ edit; return (clips, report).

    Dynamic programming ranks complete source blocks while targeting runtime.
    When speed was not explicitly specified, at most 2.5% *uniform* retiming
    is permitted to hit the target without severing a scene. No shortened
    partial action windows, no default crossfades, no fabricated event labels.
    """
    target=float(target_seconds)
    rate=float(playback_speed)
    report={'target_seconds':target,'scene_blocks':0,'selected_blocks':0,
            'selected_clips':0,'motion_markers':0,'retained_motion':0,
            'audio_markers':0,'retained_audio':0,'action_windows':0,
            'retained_action_windows':0,'cuts':[],'rate':rate,
            'retime_percent':0.,'warning':'','first_scene':'chronological'}
    if target<300. or rate<=0.:
        report['warning']='This scene-preserving planner requires at least five minutes.'
        return [],report
    blocks,cutpoints,motion,sounds,actions=_build_blocks(
        segments,activity_peaks,quiet,audio_events,action_windows)
    report['scene_blocks']=len(blocks)
    report['motion_markers']=len(motion)
    report['audio_markers']=len(sounds)
    report['action_windows']=len(actions)
    if not blocks or sum((b-a)/rate for a,b,*_ in blocks)<target*.975:
        report['warning']='Not enough usable source footage for this duration.'
        return [],report
    # Quantize to whole seconds, keeping true durations for final checking.
    # Store utility and selected IDs so the same scene cannot be reused.
    tolerance=0.025 if not explicit_speed else 0.0001
    upper=target*(1+tolerance)
    max_bucket=int(math.ceil(upper))+2
    states={0:(0.,0.,())}
    for index,(a,b,score,events,motions,audios) in enumerate(blocks):
        length=(b-a)/rate
        units=max(1,int(round(length)))
        if units>max_bucket:continue
        next_states=dict(states)
        for bucket,(utility,seconds,chosen) in states.items():
            new_bucket=bucket+units
            if new_bucket>max_bucket:continue
            candidate=(utility+score,seconds+length,chosen+(index,))
            previous=next_states.get(new_bucket)
            if previous is None or candidate[0]>previous[0]:
                next_states[new_bucket]=candidate
        states=next_states
    choices=[]
    for utility,seconds,ids in states.values():
        if not ids or not abs(seconds-target)<=target*tolerance:
            continue
        # Activity matters, but excessive cuts are undesirable for long-form.
        desirability=utility-8.*len(ids)-18.*abs(seconds-target)
        choices.append((desirability,-abs(seconds-target),ids,seconds))
    if not choices:
        report['warning']=(
            'Cannot reach this duration using complete scene blocks without '
            'cutting near activity. Choose a slightly different duration or '
            'review cut points manually.')
        return [],report
    _,_,indices,unretimed=max(choices)
    proposed_rate=rate*unretimed/target
    if abs(proposed_rate/rate-1.)>tolerance+.00001:
        report['warning']='Requested speed prevents a scene-safe exact-duration edit.'
        return [],report
    selected=[blocks[i] for i in indices]
    selected.sort(key=lambda b:b[0])
    # "Prioritize" is first, never "combat only". Put a selected candidate
    # action scene at the front without splitting it, then follow with remaining
    # clips in source order. With no evidence, use the strongest activity scene.
    if prefer_action and selected:
        best=max(range(len(selected)),
                 key=lambda i:(selected[i][3]>0,selected[i][3],
                               selected[i][4],selected[i][2]))
        if best:
            selected.insert(0,selected.pop(best))
            report['first_scene']=(
                'AI action estimate (not verified)' if selected[0][3]>0
                else 'strong visual activity (unverified)')
    clips=[(a,b,proposed_rate) for a,b,*_ in selected]
    # Avoid creating a transition between consecutively retained source blocks.
    joined=[]
    for a,b,rate_value in clips:
        if joined and abs(a-joined[-1][1])<=.07:
            joined[-1]=(joined[-1][0],b,rate_value)
        else:joined.append((a,b,rate_value))
    report['selected_blocks']=len(selected)
    report['selected_clips']=len(joined)
    report['rate']=round(proposed_rate,6)
    report['retime_percent']=round(100.*(proposed_rate/rate-1.),3)
    report['retained_motion']=sum(
        any(a<=t<=b for a,b,_ in joined) for t,_ in motion)
    report['retained_audio']=sum(
        any(a<=t<=b for a,b,_ in joined) for t,_ in sounds)
    report['retained_action_windows']=sum(
        any(min(y,b)>max(x,a) for a,b,_ in joined)
        for x,y,_ in actions)
    report['cuts']=[
        {'source_seconds':round(t,2),'type':why}
        for t,why in cutpoints
        if any(abs(t-a)<.08 or abs(t-b)<.08 for a,b,_ in joined)]
    if abs(duration(joined)-target)>.12:
        report['warning']='Internal runtime validation failed.'
        return [],report
    return joined,report
