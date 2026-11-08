"""Reliable local Ollama communication for Mr Director (no cloud API required)."""
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
    """Remove Qwen thinking tokens even on Ollama versions ignoring think=false."""
    value = re.sub(r'<think>.*?</think>', '', str(value), flags=re.I | re.S)
    if '</think>' in value.lower():
        value = re.split(r'</think>', value, flags=re.I)[-1]
    value = re.sub(r'<\|(?:im_start|im_end|endoftext)\|>', '', value)
    value = value.strip()
    # Some Qwen3 runners expose untagged deliberation as ordinary content.
    # Reject it instead of presenting private drafting text as Mr Director.
    if re.search(r'(?im)^\s*(the user says|i must respond|possible response:|another idea:|this is 1 sentence|however, the user|we are in the context)\b', value):
        return ''
    return value


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
    return {'num_ctx': 2048, 'num_predict': limit, 'temperature': temperature}


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
        'You are Mr Director inside FragForge AI. Return ONLY one JSON object with fields: '
        'mode (longform or highlight), remove_stagnant, speedup, effects, sounds, captions, '
        'focus_kills, focus_loot, fade_transition (booleans), intro_seconds (0-20), '
        'requested_speed (1-5), target_minutes (0-180), reply (brief, truthful). '
        'Never claim to have analyzed or edited video. Automatic kill recognition is unavailable. '
        'Do not include thinking. /no_think\nInitial plan: ' + json.dumps(fallback) + '\nRecent chat: ' + context +
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
    """Generate a conversational reply with bounded, explicit error handling.

    Qwen3 sometimes emits reasoning even when think=false. /no_think and a
    short generation budget reduce this, but do not guarantee suppression.
    """
    system = (
        'You are Mr Director, the friendly gaming-video assistant in FragForge. '
        'Answer naturally in 1-3 short sentences. Do not show your reasoning. '
        'Do not claim edits have been applied unless the editor confirms them. '
        'Automatic kill recognition is not yet available.'
    )
    messages = [{'role': 'system', 'content': system}]
    for entry in (history or [])[-4:]:
        if isinstance(entry, str) and entry.startswith('You: '):
            messages.append({'role': 'user', 'content': entry[5:][:350]})
        elif isinstance(entry, str) and entry.startswith('Mr Director: '):
            messages.append({'role': 'assistant', 'content': entry[13:][:350]})
    messages.append({'role': 'user', 'content': '/no_think\n' + message[:1000]})
    payload = {'model': model, 'messages': messages, 'stream': False,
               'think': False, 'keep_alive': 0, 'options': _options(300, .45)}
    errors = []
    try:
        result = _post('/api/chat', payload, timeout=90)
        reply = clean_reply(result.get('message', {}).get('content', ''))
        if reply:
            return reply[:1500]
        errors.append('Chat endpoint returned no visible answer')
    except Exception as exc:
        errors.append(str(exc))
    # Some model/runner combinations behave better through /api/generate.
    try:
        reply = _generate('/no_think\n' + system + '\nUser: ' + message[:700] +
                          '\nMr Director:', model, 300)
        if reply:
            return reply[:1500]
        errors.append('Generate endpoint returned no visible answer')
    except Exception as exc:
        errors.append(str(exc))
    raise RuntimeError('Ollama did not return a usable answer. ' + ' | '.join(errors))
