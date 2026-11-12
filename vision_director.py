"""Optional local Ollama vision analysis of gameplay stills. Estimates, not verified kills."""
import base64, json, re, subprocess, urllib.request
from pathlib import Path
from media import binary
from ai_runtime import PROFILES, ollama_ram_gb, MemoryBudgetGuard
from combat_calibration import calibration_sample_times, calibration_report
from eli_action_reasoning import (parse_sequence_reply,sequence_centers,
                                  temporal_action_windows)

HOST='http://127.0.0.1:11434'

def _post(url,payload,timeout=80):
    req=urllib.request.Request(url,json.dumps(payload).encode('utf-8'),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def installed_models():
    try:
        with urllib.request.urlopen(HOST+'/api/tags',timeout=4) as r:
            return [x.get('name','') for x in json.load(r).get('models',[])]
    except Exception:return []

def extract_frame(path,seconds,width=512):
    cmd=[binary('ffmpeg'),'-hide_banner','-loglevel','error','-ss',str(max(0.,seconds)),'-i',str(path),'-frames:v','1','-vf',f'scale={width}:-2','-f','image2pipe','-vcodec','mjpeg','-']
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if p.returncode or not p.stdout:raise RuntimeError('Frame extraction failed: '+p.stderr.decode(errors='replace')[-250:])
    return base64.b64encode(p.stdout).decode('ascii')

EVENTS=('combat','looting','walking','driving','menu','other')


def _parse_classification(response, seconds):
    """Only final response content is a classification; never parse chain-of-thought."""
    answer=str(response.get('response') or '').strip()
    if not answer:
        reason=response.get('done_reason','unknown')
        tokens=response.get('eval_count','?')
        thinking=len(response.get('thinking') or '')
        raise ValueError(f'No final JSON (stop={reason}, tokens={tokens}, reasoning_chars={thinking})')
    try:
        data=json.loads(answer)
    except json.JSONDecodeError:
        match=re.search(r'\{[^{}]*\}',answer)
        if not match:raise ValueError('Vision model returned invalid final JSON')
        data=json.loads(match.group())
    if not isinstance(data,dict):raise ValueError('Vision model returned non-object JSON')
    event=str(data.get('event','other')).lower().strip()
    if event not in EVENTS:event='other'
    try:confidence=max(0.,min(1.,float(data.get('confidence',0))))
    except (ValueError,TypeError):confidence=0.
    # This is a single-frame *candidate*, never proof of a new splatter or kill.
    raw=data.get('blood_splatter',False)
    blood=(raw is True or str(raw).lower() in ('true','yes','1'))
    try: blood_confidence=max(0.,min(1.,float(data.get('blood_confidence',0)))) if blood else 0.
    except (ValueError,TypeError): blood_confidence=0.
    return {'time':round(seconds,2),'event':event,'confidence':confidence,
            'blood_splatter':blood,'blood_confidence':blood_confidence}


def classify_frame(path,seconds,model,profile="Balanced"):
    prompt=('Classify the visible Project Zomboid gameplay image. '
            'Allowed event values: combat, looting, walking, driving, menu, other. '
            'Only choose combat when an attack is visibly underway; nearby zombies alone do not prove combat. '
            'One still image cannot verify a kill. '
            'Also indicate whether an apparent blood splatter or blood stain is VISIBLE in the image; '
            'do not mistake red UI, lighting, clothing or paint for blood. '
            'Blood does not establish a hit or kill, and a still image cannot establish when blood appeared. '
            'Return JSON keys event, confidence (0 to 1), blood_splatter (boolean), blood_confidence (0 to 1).')
    frame=extract_frame(path,seconds,PROFILES[profile]["image_width"])
    base={'model':model,'prompt':prompt,'images':[frame], 'stream':False,
          'think':False,'format':'json','keep_alive':'30s'}
    errors=[]
    # Retry once with a larger budget when the model consumes all output on reasoning.
    # The second request is not a claim that reasoning was disabled.
    for budget in (384,1536):
        payload=dict(base,options={'temperature':0,'num_predict':budget,'num_ctx':PROFILES[profile]['num_ctx']})
        try:
            response=_post(HOST+'/api/generate',payload,timeout=150)
            return _parse_classification(response,seconds)
        except (ValueError,TimeoutError) as exc:
            errors.append(str(exc))
    raise ValueError('Vision classification failed: '+'; '.join(errors))

def classify_action_sequence(path,center,end,model,profile="Balanced"):
    """Compare three ordered images for action motion, never a confirmed kill."""
    interval=.75
    times=[max(0.,min(float(end)-.15,float(center)+delta))
           for delta in (-interval,0.,interval)]
    if len(set(round(t,2) for t in times))<3:
        raise ValueError('Insufficient footage for a temporal action sample')
    images=[extract_frame(path,t,min(448,PROFILES[profile]['image_width']))
            for t in times]
    prompt=(
        'You are comparing THREE CHRONOLOGICAL gameplay frames from '
        'Project Zomboid: earlier, middle, later (0.75 seconds apart). '
        'Identify motion evidence, not a static pose. Return exactly one JSON '
        'object with keys: action, confidence, visible_change, '
        'attacker_target_interaction, new_blood_visible. action is one of '
        'gunfire, punch, kick, weapon_swing, shove, impact, explosion, '
        'blood_change, none. gunfire means visual muzzle flash '
        'or visible firing animation, not just holding a gun. punch means '
        'arm striking, kick means leg striking, weapon_swing means visible '
        'bat/axe/knife swing, shove means push/grapple, impact means visible '
        'contact across frames. explosion means visible expanding blast or '
        'detonation across frames, not a static fire or smoke cloud. '
        'blood_change means new blood particles/splatter become visible '
        'between frames, not a pre-existing blood pool. Set '
        'new_blood_visible=true only if new blood appears in the sequence. '
        'Only set visible_change=true when movement is evidenced between '
        'these images. For impact, require actual 
        'attacker-to-target interaction. Ordinary walking, aiming without '
        'firing, looting, inventory screens, camera movement, and nearby '
        'zombies alone should be none. Never claim a kill or exact gunshot '
        'sound from still images. If uncertain say none with low confidence.')
    payload={'model':model,'prompt':prompt,'images':images,'stream':False,
             'think':False,'format':'json','keep_alive':'30s',
             'options':{'temperature':0,'num_predict':384,
                        'num_ctx':PROFILES[profile]['num_ctx']}}
    response=_post(HOST+'/api/generate',payload,timeout=150)
    return parse_sequence_reply(response,center,times)


def initial_sample_times(end,budget,seed_times=()):
    """Spend coarse vision calls on both timeline coverage and motion hotspots."""
    end=max(.25,float(end))
    limit=max(1,(int(budget)+1)//2)
    # When motion peaks exist, reserve at least half the coarse budget for
    # the strongest peaks. This replaces unproductive uniform-only coverage.
    evenly=max(1,min(limit,int(end/12)+1))
    if seed_times:
        evenly=max(1,(evenly+1)//2)
    picks=[max(0.,min(end-.2,(i+.5)*end/evenly))
           for i in range(evenly)]
    for second,score in sorted(seed_times,key=lambda pair:-float(pair[1])):
        if len(picks)>=limit:
            break
        moment=max(0.,min(end-.2,float(second)))
        if all(abs(moment-existing)>=3. for existing in picks):
            picks.append(moment)
    return sorted(set(round(moment,2) for moment in picks))


def retained_sample_times(ranges, limit, seed_times=()):
    """Spread local vision frames across the SOURCE intervals kept on V1.

    Sampling occurs in compressed retained-footage time, never in discarded
    footage. Existing activity peaks can bias the scan toward possible action
    without asserting that a fight occurred.
    """
    ranges=sorted((max(0.,float(a)),float(b)) for a,b in ranges
                  if float(b)-float(a)>=.3)
    total=sum(b-a for a,b in ranges)
    limit=max(1,int(limit))
    if not ranges or total<=0.:return []
    def at(offset):
        offset=max(0.,min(total-.001,offset))
        for a,b in ranges:
            length=b-a
            if offset<length:return max(a+.02,min(b-.02,a+offset))
            offset-=length
        return ranges[-1][1]-.02
    # Retain broad coverage across every selected scene, then reserve
    # remaining slots for likely motion hotspots.
    broad=max(1,limit//2)
    stamps=[at((i+.5)*total/broad) for i in range(broad)]
    for a,b in ranges:
        if len(stamps)>=limit:break
        middle=(a+b)/2
        if all(abs(middle-t)>.35 for t in stamps):stamps.append(middle)
    for t,score in sorted(seed_times,key=lambda pair:-float(pair[1])):
        if len(stamps)>=limit:break
        t=float(t)
        if any(a<=t<=b for a,b in ranges) and all(abs(t-x)>.4 for x in stamps):
            stamps.append(t)
    while len(stamps)<limit:
        for i in range(limit*2):
            if len(stamps)>=limit:break
            t=at((i+.35)*total/(limit*2))
            if all(abs(t-x)>.2 for x in stamps):
                stamps.append(t)
        break
    return sorted(round(t,3) for t in stamps[:limit])


def _in_ranges(t,ranges):
    return any(float(a)<=float(t)<=float(b) for a,b in ranges)


def scan(path,end,model,progress=None,cancel=None,max_frames=None,
         profile="Balanced",seed_times=(),requested_events=("combat",),
         reference_time=None,allowed_ranges=None):
    """Use the requested frame budget with motion-guided scene refinement.

    Phase 1 covers the timeline and its strongest FFmpeg motion peaks.
    Phase 2 samples close to estimated events in 3-second increments.
    The caller may choose a smaller budget independently of RAM profile.
    """
    from ollama_memory import release_model
    end=max(.25,float(end))
    budget=max(1,int(max_frames or PROFILES[profile]["max_frames"]))
    # Reserve actual image slots for 3-frame action comparisons; do not
    # increase total scanned images beyond the user-selected frame budget.
    wants_actions='combat' in (requested_events or ())
    sequence_limit=min(8,max(1,budget//16)) if wants_actions and budget>=24 else 0
    still_budget=max(1,budget-3*sequence_limit)
    retained=[(max(0.,float(a)),min(end,float(b)))
              for a,b in (allowed_ranges or ()) if float(b)>float(a)+.3]
    relevant_peaks=[(t,score) for t,score in seed_times
                    if not retained or _in_ranges(t,retained)]
    broad=(retained_sample_times(retained,max(1,(still_budget+1)//2),relevant_peaks)
           if retained else initial_sample_times(end,still_budget,seed_times))
    if reference_time is not None and (not retained or _in_ranges(reference_time,retained)):
        # Reserve up to a third of the first pass for the supplied benchmark,
        # while keeping the same overall frame budget and timeline coverage.
        coarse_limit=max(1,(still_budget+1)//2)
        reference_quota=min(12,max(1,coarse_limit//3))
        reference_samples=calibration_sample_times(
            reference_time,end,reference_quota)
        remaining_coarse=max(0,coarse_limit-len(reference_samples))
        broad_rest=(retained_sample_times(retained,max(1,remaining_coarse),relevant_peaks)
                    if retained else initial_sample_times(
                        end,max(1,2*remaining_coarse),seed_times
                    )[:remaining_coarse]) if remaining_coarse else []
        reference_samples=[t for t in reference_samples
                           if not retained or _in_ranges(t,retained)]
        broad=sorted(set(reference_samples+broad_rest))
    coarse_uniform_count=max(1,len(broad))
    remaining=max(0,still_budget-len(broad))
    try:
        coarse=_scan_samples(
            path,broad,model,
            (lambda done, _total:progress(done,budget)) if progress else None,
            cancel,profile)
        desired=set(requested_events or ('combat',))
        # A still frame cannot establish a fight. Look at adjacent moments.
        # Reserve follow-up samples for promising visual OR motion candidates,
        # even when the initial still-frame classifier missed combat entirely.
        hits=sorted(
            (s for s in coarse['samples']
             if s.get('event') in desired and float(s.get('confidence',0))>=.60),
            key=lambda s:-float(s.get('confidence',0)))
        anchor_limit=max(1,min(4,remaining//7)) if remaining else 0
        anchors=([float(reference_time)] if reference_time is not None and anchor_limit
                  and (not retained or _in_ranges(reference_time,retained)) else [])
        for item in hits:
            moment=float(item['time'])
            if (not retained or _in_ranges(moment,retained)) and all(abs(moment-other)>=12. for other in anchors):
                anchors.append(moment)
            if len(anchors)>=anchor_limit:break
        for second,score in sorted(relevant_peaks,key=lambda pair:-float(pair[1])):
            if len(anchors)>=anchor_limit:break
            moment=float(second)
            if (not retained or _in_ranges(moment,retained)) and all(abs(moment-other)>=12. for other in anchors):
                anchors.append(moment)
        times=[]
        for delta in (-1.5,1.5,-3.,3.,-4.5,4.5,-6.,6.,-7.5,7.5):
            for anchor in anchors:
                moment=round(max(0.,min(end-.2,anchor+delta)),2)
                if ((not retained or _in_ranges(moment,retained))
                        and all(abs(moment-float(x['time']))>=.55
                        for x in coarse['samples'])
                        and all(abs(moment-existing)>=.55 for existing in times)):
                    times.append(moment)
                if len(times)>=remaining:break
            if len(times)>=remaining:break
        # Use any remaining budget for a second view of high-motion regions
        # and interleaved coverage, never for invented combat labels.
        if len(times)<remaining:
            extras=[float(t) for t,_ in sorted(
                relevant_peaks,key=lambda pair:-float(pair[1]))]
            count=max(1,coarse_uniform_count)
            if retained:
                extras.extend(retained_sample_times(retained,max(1,remaining*2),relevant_peaks))
            else:
                extras.extend((i+.25)*end/count for i in range(count))
                extras.extend((i+.75)*end/count for i in range(count))
            for moment in extras:
                moment=round(max(0.,min(end-.2,moment)),2)
                if ((not retained or _in_ranges(moment,retained))
                        and all(abs(moment-float(x['time']))>=.55
                        for x in coarse['samples'])
                        and all(abs(moment-existing)>=.55 for existing in times)):
                    times.append(moment)
                if len(times)>=remaining:break
        times=sorted(times[:remaining])
        if times:
            fine=_scan_samples(
                path,times,model,
                (lambda done,_total:progress(len(broad)+done,budget))
                if progress else None,cancel,profile)
        else:
            fine={'samples':[],'errors':[],'failed_frames':0}
        # Target gunfire, punches, kicks, swings, shoves and impacts in
        # selected multi-frame bursts. Missing/invalid model responses are
        # recorded as errors and never invent action events.
        sequences=[];sequence_errors=[]
        if sequence_limit:
            all_stills=coarse['samples']+fine['samples']
            centers=sequence_centers(
                all_stills,relevant_peaks,end,sequence_limit,reference_time)
            if retained:
                centers=[t for t in centers if _in_ranges(t-.75,retained)
                         and _in_ranges(t+.75,retained)]
            for i,center in enumerate(centers):
                if cancel is not None and cancel.is_set():
                    raise RuntimeError('Vision scan cancelled')
                warning=MemoryBudgetGuard(profile).check(ollama_ram_gb())
                if warning:raise RuntimeError(warning)
                try:
                    sequences.append(
                        classify_action_sequence(path,center,end,model,profile))
                except Exception as exc:
                    sequence_errors.append(
                        f'action sequence {center:.1f}s: {str(exc)[:150]}')
                if progress:progress(
                    min(budget,len(broad)+len(times)+3*(i+1)),budget)
        observations={float(x['time']):x for x in coarse['samples']}
        observations.update((float(x['time']),x) for x in fine['samples'])
        result=dict(coarse)
        result['samples']=sorted(observations.values(),key=lambda x:float(x['time']))
        result['coarse_frames']=len(coarse['samples'])
        result['refined_frames']=len(fine['samples'])
        result['action_sequences']=sequences
        result['action_frame_attempts']=3*len(centers) if sequence_limit else 0
        result['action_errors']=sequence_errors[:10]
        result['action_windows']=temporal_action_windows(sequences,end)
        result['max_frames']=budget
        result['failed_frames']+=fine.get('failed_frames',0)
        result['errors']+=fine.get('errors',[])
        result['scan_method']=('retained V1 motion-guided frames + temporal actions'
                               if retained else 'motion-guided stills + targeted 3-frame action reasoning')
        result['retained_v1_ranges']=retained
        result['calibration']=calibration_report(result['samples'],reference_time)
        if progress:
            progress(budget,budget)
        return result
    finally:
        release_model(model)


def _scan_samples(path, samples, model, progress=None, cancel=None, profile="Balanced"):
    found=[];errors=[]
    count=len(samples)
    guard = MemoryBudgetGuard(profile)
    for i,t in enumerate(samples):
        ram = ollama_ram_gb()
        warning = guard.check(ram)
        if warning:
            raise RuntimeError(warning)
        if cancel is not None and cancel.is_set():raise RuntimeError('Vision scan cancelled')
        try:found.append(classify_frame(path,t,model,profile))
        except Exception as exc:
            errors.append(str(exc))
            if len(errors)>=3 and not found:raise RuntimeError('Vision scan unavailable: '+errors[-1]+'; try a different vision model such as llava:7b')
        warning = guard.check(ollama_ram_gb())
        if warning:
            raise RuntimeError(warning)
        if progress:progress(i+1,count)
    return {'samples':found,'errors':errors[:3],'failed_frames':len(errors),'model':model}

def scene_windows(samples,source_end,event="combat",half_width=9.,
                  threshold=.65,context_before=2.,context_after=2.):
    """Estimate a scene only after TWO distinct supporting frame observations.

    A single classifier hit no longer becomes an 18-second combat claim.
    Observed non-event frames constrain the opening and ending, with at
    most two seconds of context beyond observed action. Scene estimates
    are not claims of a confirmed kill.
    """
    rows=sorted((x for x in samples if 'time' in x),
                key=lambda x:float(x['time']))
    positives=[x for x in rows
               if x.get('event')==event
               and float(x.get('confidence',0))>=threshold]
    groups=[]
    for item in positives:
        time=float(item['time'])
        if groups:
            previous=float(groups[-1][-1]['time'])
            intervening=sum(
                1 for x in rows
                if previous<float(x['time'])<time
                and x.get('event')!=event
                and float(x.get('confidence',0))>=.6)
            if time-previous<=5.5 and intervening<2:
                groups[-1].append(item)
                continue
        groups.append([item])
    windows=[]
    for group in groups:
        distinct={round(float(item['time']),2) for item in group}
        if len(distinct)<2:
            # A lone image may show a nearby zombie, not an attack.
            continue
        first=min(distinct);last=max(distinct)
        prior=[float(x['time']) for x in rows
               if first-6.<=float(x['time'])<first
               and x.get('event')!=event
               and float(x.get('confidence',0))>=.55]
        later=[float(x['time']) for x in rows
               if last<float(x['time'])<=last+6.
               and x.get('event')!=event
               and float(x.get('confidence',0))>=.55]
        lead=max(0.,min(float(context_before),float(half_width)))
        tail=max(0.,min(float(context_after),float(half_width)))
        begin=first-lead
        finish=last+tail
        if prior:
            begin=max(begin,(max(prior)+first)/2-lead/2)
        if later:
            finish=min(finish,(last+min(later))/2+tail/2)
        begin=max(0.,begin)
        finish=min(float(source_end),finish)
        if finish-begin>=1.:
            confidence=sum(float(x.get('confidence',0)) for x in group)/len(group)
            windows.append((begin,finish,round(confidence,3)))
    merged=[]
    for begin,finish,confidence in windows:
        if merged and begin<=merged[-1][1]+.10:
            a,b,p=merged[-1]
            merged[-1]=(a,max(finish,b),max(confidence,p))
        else:
            merged.append((begin,finish,confidence))
    return merged


def combat_windows(samples,source_end,half_width=9.):
    return scene_windows(samples,source_end,event='combat',half_width=half_width)

