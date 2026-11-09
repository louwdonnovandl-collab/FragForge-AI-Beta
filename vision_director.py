"""Optional local Ollama vision analysis of gameplay stills. Estimates, not verified kills."""
import base64, json, re, subprocess, urllib.request
from pathlib import Path
from media import binary
from ai_runtime import PROFILES, ollama_ram_gb, MemoryBudgetGuard

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

def scan(path,end,model,progress=None,cancel=None,max_frames=None,
         profile="Balanced",seed_times=(),requested_events=("combat",)):
    """Use a 2x visual-frame budget with targeted event-boundary refinement.

    Phase 1 broadly samples the recording and known motion peaks. Phase 2
    inspects up to half the total budget near promising scenes at 3s spacing.
    Estimates are not verified gameplay outcomes. Limits are per profile.
    """
    from ollama_memory import release_model
    end=max(.25,float(end))
    budget=max(1,int(max_frames or PROFILES[profile]["max_frames"]))
    coarse_budget=max(1,(budget+1)//2)
    coarse_uniform_count=max(1,min(coarse_budget,int(end/12)+1))
    broad=[max(0.,min(end-.2,(i+.5)*end/coarse_uniform_count))
           for i in range(coarse_uniform_count)]
    # If uniform sampling has spare slots, include high-motion positions.
    extra_slots=max(0,coarse_budget-len(broad))
    for second,score in sorted(seed_times,key=lambda pair:-float(pair[1])):
        if extra_slots<=0:
            break
        t=max(0.,min(end-.2,float(second)))
        if all(abs(t-existing)>=5. for existing in broad):
            broad.append(t)
            extra_slots-=1
        if extra_slots<=0:
            break
    broad=sorted(set(round(t,2) for t in broad))
    remaining=max(0,budget-len(broad))
    try:
        coarse=_scan_samples(
            path,broad,model,
            (lambda done, _total:progress(done,budget)) if progress else None,
            cancel,profile)
        desired=set(requested_events or ('combat',))
        hits=sorted(
            (s for s in coarse['samples'] if s.get('event') in desired
             and float(s.get('confidence',0))>=.65),
            key=lambda s:-float(s.get('confidence',0)))
        anchors=[]
        for hit in hits:
            moment=float(hit['time'])
            if all(abs(moment-previous)>=22. for previous in anchors):
                anchors.append(moment)
            if len(anchors)>=5:
                break
        times=[]
        # 3 second step adds observations before, during and after action.
        # This avoids trimming a fight to a single still-image timestamp.
        for anchor in anchors:
            for delta in range(-4,5):
                moment=round(max(0.,min(end-.2,anchor+delta*3.)),2)
                if (all(abs(moment-x['time'])>=1. for x in coarse['samples'])
                        and moment not in times):
                    times.append(moment)
        # Even when no combat is recognized during the coarse pass, use the
        # extra 2x budget on high-motion candidates and interleaved times.
        # Otherwise a difficult recording would silently receive only the
        # previous version's coarse sampling count.
        if len(times)<remaining:
            extras=[float(t) for t,_ in sorted(
                seed_times,key=lambda pair:-float(pair[1]))]
            if coarse_uniform_count>0:
                extras.extend((i+.25)*end/coarse_uniform_count
                              for i in range(coarse_uniform_count))
                extras.extend((i+.75)*end/coarse_uniform_count
                              for i in range(coarse_uniform_count))
            for t in extras:
                t=round(max(0.,min(end-.2,t)),2)
                if (all(abs(t-x['time'])>=.5 for x in coarse['samples'])
                        and all(abs(t-existing)>=.5 for existing in times)):
                    times.append(t)
                if len(times)>=remaining:
                    break
        times=sorted(times[:remaining])
        if times:
            fine=_scan_samples(
                path,times,model,
                (lambda done,_total:progress(len(broad)+done,budget))
                if progress else None,cancel,profile)
        else:
            fine={'samples':[],'errors':[],'failed_frames':0}
        observations={float(x['time']):x for x in coarse['samples']}
        observations.update((float(x['time']),x) for x in fine['samples'])
        result=dict(coarse)
        result['samples']=sorted(observations.values(),key=lambda x:float(x['time']))
        result['coarse_frames']=len(coarse['samples'])
        result['refined_frames']=len(fine['samples'])
        result['max_frames']=budget
        result['failed_frames']+=fine.get('failed_frames',0)
        result['errors']+=fine.get('errors',[])
        result['scan_method']='coarse+3s event-boundary sampling'
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
    """Estimated activity boundaries from repeated frames and event changes.

    Output: (source_begin, source_end, confidence). No kill assertion.
    """
    rows=sorted((x for x in samples if "time" in x),
                key=lambda x:float(x['time']))
    positive=[x for x in rows if x.get('event')==event
              and float(x.get('confidence',0))>=threshold]
    groups=[]
    for item in positive:
        t=float(item['time'])
        if groups:
            previous=float(groups[-1][-1]['time'])
            negatives=sum(1 for x in rows
                          if previous<float(x['time'])<t
                          and x.get('event')!=event
                          and float(x.get('confidence',0))>=.6)
            if t-previous<=6.5 and negatives<2:
                groups[-1].append(item)
                continue
        groups.append([item])
    intervals=[]
    for group in groups:
        first=float(group[0]['time'])
        last=float(group[-1]['time'])
        before=[float(x['time']) for x in rows
                if first-6.<=float(x['time'])<first
                and x.get('event')!=event
                and float(x.get('confidence',0))>=.55]
        after=[float(x['time']) for x in rows
               if last<float(x['time'])<=last+6.
               and x.get('event')!=event
               and float(x.get('confidence',0))>=.55]
        start=((max(before)+first)/2-context_before
               if before else first-half_width)
        stop=((last+min(after))/2+context_after
              if after else last+half_width)
        intervals.append((max(0.,start),min(float(source_end),stop),
                          max(float(x.get('confidence',0)) for x in group)))
    merged=[]
    for start,stop,conf in intervals:
        if merged and start<=merged[-1][1]:
            a,b,p=merged[-1]
            merged[-1]=(a,max(stop,b),max(conf,p))
        else:
            merged.append((start,stop,conf))
    return merged


def combat_windows(samples,source_end,half_width=9.):
    return scene_windows(samples,source_end,event='combat',half_width=half_width)

