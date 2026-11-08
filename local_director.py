"""Reliable local Ollama communication for Editor-X (no cloud API required)."""
import json
import re
import urllib.error
import urllib.request

HOST = 'http://127.0.0.1:11434'
DEFAULT_MODEL = 'qwen3:4b'


def available_models(timeout=4):
    with urllib.request.urlopen(HOST + '/api/tags', timeout=timeout) as response:
        data = json.load(response)
    return [m['name'] for m in data.get('models', []) if isinstance(m.get('name'), str)]


def clean_reply(value):
    """Extract the complete final answer, excluding reasoning when tagged."""
    if value is None:
        return ''
    value = str(value)
    # Some Ollama/Qwen versions put untagged reasoning before </think>.
    if re.search(r'</think>', value, flags=re.I):
        value = re.split(r'</think>', value, flags=re.I)[-1]
    else:
        value = re.sub(r'<think>.*?</think>', '', value, flags=re.I | re.S)
        # An unfinished thinking section is not a user-visible answer.
        value = re.sub(r'<think>.*$', '', value, flags=re.I | re.S)
    value = re.sub(r'<\|(?:im_start|im_end|endoftext)\|>', '', value)
    return value.strip()


def _post(endpoint, payload, timeout=75):
    req = urllib.request.Request(
        HOST + endpoint, data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1500).decode('utf-8', 'replace')
        raise RuntimeError(f'Ollama HTTP {exc.code}: {detail or exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Cannot contact Ollama at {HOST}: {exc.reason}') from exc


def _options(limit=240, temperature=.3):
    return {'num_ctx': 4096, 'num_predict': limit, 'temperature': temperature}


def _generate(prompt, model, limit=240, json_mode=False):
    payload = {'model': model, 'prompt': prompt, 'stream': False,
               'think': False, 'keep_alive': 0, 'options': _options(limit)}
    if json_mode:
        payload['format'] = 'json'
    return clean_reply(_post('/api/generate', payload, timeout=120).get('response', ''))


def make_plan(message, model=DEFAULT_MODEL, history=None):
    from assistant_engine import interpret_request
    fallback = interpret_request(message)
    context = '\n'.join((history or [])[-4:])[:1200]
    prompt = (
        'You are Editor-X, FragForge AI’s built-in editing planner. Return ONLY one JSON object with fields: '
        'mode (longform or highlight), remove_stagnant, speedup, effects, sounds, captions, '
        'focus_kills, focus_loot, fade_transition (booleans), intro_seconds (0-20), '
        'requested_speed (1-5), target_minutes (0-180), reply (brief, truthful). '
        'Never claim an edit was applied before the editor confirms it. Only describe visual events verified by the video scanner. '
        'Return only valid JSON in the final answer.\nInitial plan: ' + json.dumps(fallback) + '\nRecent chat: ' + context +
        '\nCurrent request: ' + message[:1800]
    )
    # Retry malformed/empty Ollama output, then preserve a usable rule-based plan.
    result = None
    errors = []
    for candidate in (prompt, 'Return ONLY a JSON object for this video editing request. '
                      '/no_think\nFields: mode, remove_stagnant, speedup, effects, sounds, captions, '
                      'focus_kills, focus_loot, fade_transition, intro_seconds, '
                      'requested_speed, target_minutes, reply. Request: ' + message[:700]):
        try:
            raw = _generate(candidate, model, 320, json_mode=True)
            if not raw.strip():
                raise ValueError('Ollama returned an empty editing plan')
            from director_plan_fallback import _extract_json
            candidate_result = _extract_json(raw)
            if not isinstance(candidate_result, dict) or not candidate_result:
                raise ValueError('Ollama returned no plan fields')
            result = candidate_result
            break
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, OSError) as exc:
            errors.append(str(exc))
    if result is None:
        plan = dict(fallback)
        plan['source'] = 'fallback'
        plan['warning'] = 'Local AI plan unavailable: ' + ('; '.join(errors)[-400:] if errors else 'empty response') + '. Review the basic edit plan.'
        return plan, 'My local AI could not prepare a detailed plan, so I made a basic edit plan for your review.'
    plan = dict(fallback)
    for key in ('remove_stagnant', 'speedup', 'effects', 'sounds', 'captions',
                'focus_kills', 'focus_loot', 'fade_transition'):
        if type(result.get(key)) is bool:
            plan[key] = result[key]
    if result.get('mode') in ('longform', 'highlight'):
        plan['mode'] = result['mode']
    for key, low, high in (('intro_seconds', 0, 20), ('requested_speed', 1, 5),
                           ('target_minutes', 0, 180)):
        try:
            plan[key] = max(low, min(high, int(result[key])))
        except (KeyError, TypeError, ValueError):
            pass
    # Explicit numerical requests always override guesses from the language model.
    for key in ('target_minutes', 'target_seconds', 'intro_seconds', 'requested_speed'):
        if fallback.get(key):
            plan[key] = fallback[key]
    if fallback.get('target_seconds') and fallback['target_seconds'] <= 180:
        plan['mode'] = 'highlight'
    plan['music'] = fallback.get('music', False)
    plan['explicit_speed'] = fallback.get('explicit_speed', False)
    reply = clean_reply(result.get('reply', 'I prepared an edit for your review.'))[:350]
    return plan, reply


def chat_reply(message, model=DEFAULT_MODEL, history=None):
    """Chat with Ollama; deterministic fallback keeps editing instructions useful."""
    from editor_x_brain import parse_instruction, describe_intent
    intent=parse_instruction(message)
    system=(
        'You are Editor-X, the integrated AI video editor inside FragForge. '
        'You CAN plan and apply edits through the FragForge editor after user approval. '
        'Send Message is conversation only; Prepare Edit starts analysis. '
        'The current V1 timeline is the source of truth; preserve existing edits by default. '
        'Follow the latest user instruction; older requests are context, not restrictions. '
        'Combat and exploration can coexist in separate sections. '
        'Do not recommend external editors or claim that you cannot edit files. '
        'Never invent music tracks, video observations, or completed changes. '
        'Do not claim to recognize an event without video-analysis evidence. '
        'Keep answers concise and helpful; explain the intended change and ask the user '
        'to use Prepare Edit. No markdown tables. /no_think'
    )
    messages=[{'role':'system','content':system}]
    for entry in (history or [])[-6:]:
        if isinstance(entry,str) and entry.startswith('You: '):
            messages.append({'role':'user','content':entry[5:][:500]})
        elif isinstance(entry,str) and entry.startswith('Editor-X: '):
            messages.append({'role':'assistant','content':entry[10:][:500]})
    messages.append({'role':'user','content':message[:2500]})
    errors=[]
    chosen_model=DEFAULT_MODEL if DEFAULT_MODEL in available_models_safe() else model
    for endpoint in ('/api/chat','/api/generate'):
        try:
            payload={'model':chosen_model,'stream':False,'think':False,
                     'keep_alive':0,'options':_options(700,.35)}
            if endpoint=='/api/chat':payload['messages']=messages
            else:payload['prompt']=system+'\nUser: '+message[:1500]+'\nEditor-X:'
            data=_post(endpoint,payload,timeout=150)
            raw=(data.get('message') or {}).get('content','') if endpoint=='/api/chat' else data.get('response','')
            answer=clean_reply(raw)
            if answer:return answer[:5000]
            errors.append(endpoint+': empty visible response; done_reason='+str(data.get('done_reason')))
        except Exception as exc:errors.append(endpoint+': '+str(exc)[:220])
    # Offline response is clearly a proposal, never a claim that footage was analyzed.
    return describe_intent(intent)+' [Local AI unavailable: '+(' | '.join(errors))[:260]+']'


def available_models_safe():
    try:return available_models(timeout=3)
    except Exception:return []
