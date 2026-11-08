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

def scan(path,end,model,progress=None,cancel=None,max_frames=None,profile="Balanced"):
    # Uniform samples avoid relying on motion peaks, which previously returned zero.
    # 48 frames across a 47-minute source is only a coarse first pass.
    max_frames = max_frames or PROFILES[profile]["max_frames"]
    count=max(1,min(max_frames,int(end/12)+1))
    samples=[min(end-0.2,(i+.5)*end/count) for i in range(count)]
    try:
        return _scan_samples(path, samples, model, progress, cancel, profile)
    finally:
        from ollama_memory import release_model
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

def combat_windows(samples,source_end,half_width=9.):
    # Never claim these are confirmed kills.
    hits=[x for x in samples if x.get('event')=='combat' and x.get('confidence',0)>=.65]
    return [(max(0.,x['time']-half_width),min(source_end,x['time']+half_width),float(x['confidence'])) for x in hits]
