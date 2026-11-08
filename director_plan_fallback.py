"""FragForge AI v0.10.46 — robust local Ollama director plan generation.
Standard-library only. Returns a dict with 'steps' and 'source'.
"""
import json
import re
import urllib.request
from urllib.error import URLError, HTTPError

ENDPOINT = 'http://127.0.0.1:11434/api/generate'
MODEL = 'qwen3:4b'


def _extract_json(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError('Ollama returned an empty response')
    raw = re.sub(r'<think>[\s\S]*?</think>', '', raw, flags=re.I).strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for i, ch in enumerate(raw):
            if ch in '{[':
                try:
                    obj, _ = decoder.raw_decode(raw[i:])
                    return obj
                except json.JSONDecodeError:
                    pass
        raise ValueError('Ollama response did not contain valid JSON')


def _validate(data):
    if isinstance(data, list):
        data = {'steps': data}
    if not isinstance(data, dict):
        raise ValueError('Editing plan must be a JSON object')
    steps = data.get('steps', data.get('actions'))
    if not isinstance(steps, list) or not steps:
        raise ValueError('Editing plan requires non-empty steps list')
    cleaned = []
    for step in steps[:30]:
        if isinstance(step, str) and step.strip():
            cleaned.append({'action': step.strip()})
        elif isinstance(step, dict) and (step.get('action') or step.get('type')):
            cleaned.append(step)
    if not cleaned:
        raise ValueError('Editing plan contained no usable steps')
    data['steps'] = cleaned
    data['source'] = 'ollama'
    return data


def _ollama(prompt, endpoint, model, timeout):
    payload = json.dumps({'model': model, 'prompt': prompt, 'stream': False,
                          'format': 'json', 'options': {'temperature': 0.1}}).encode('utf-8')
    req = urllib.request.Request(endpoint, data=payload,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as response:
        envelope = json.load(response)
    if not isinstance(envelope, dict):
        raise ValueError('Invalid Ollama API envelope')
    return _validate(_extract_json(envelope.get('response', '')))


def fallback_plan(request, errors=None):
    """Safe, non-destructive suggestions; not proof of detected game events."""
    request = str(request or 'Create a gaming edit').strip()
    steps = [
        {'action': 'analyze_media', 'description': 'Inspect duration, audio and scene changes'},
        {'action': 'suggest_cuts', 'description': 'Review candidate dead-time sections before removal'},
        {'action': 'review_transitions', 'description': 'Suggest smooth transitions between approved cuts'},
    ]
    lower = request.lower()
    if any(word in lower for word in ('caption', 'subtitle', 'speech')):
        steps.append({'action': 'suggest_captions', 'description': 'Review speech and highlight caption candidates'})
    if any(word in lower for word in ('effect', 'cinematic', 'kill', 'combat')):
        steps.append({'action': 'suggest_effects', 'description': 'Review context-appropriate visual effects; no events assumed detected'})
    if 'intro' in lower:
        steps.append({'action': 'suggest_intro', 'description': 'Propose intro duration and style for approval'})
    return {'source': 'fallback', 'request': request, 'steps': steps,
            'warning': 'Local AI did not produce a valid plan; review suggestions before applying.',
            'errors': list(errors or [])}


def generate_director_plan(request, endpoint=ENDPOINT, model=MODEL, timeout=45):
    """Try full prompt, then concise retry, then return an offline fallback."""
    request = str(request or '').strip() or 'Create a gaming edit'
    prompts = [
        'Return ONLY a JSON object with a nonempty steps array. Each step has an action string. '
        'Do not claim to detect events without analyzing video. User request: ' + request,
        'JSON only. Format: {"steps":[{"action":"analyze_media"},{"action":"suggest_cuts"}]}. '
        'Editing request: ' + request[:500],
    ]
    errors = []
    for attempt, prompt in enumerate(prompts, 1):
        try:
            plan = _ollama(prompt, endpoint, model, timeout)
            plan['attempt'] = attempt
            return plan
        except (ValueError, KeyError, TypeError, TimeoutError, OSError, URLError, HTTPError,
                json.JSONDecodeError) as exc:
            errors.append(f'Attempt {attempt}: {type(exc).__name__}: {exc}')
    return fallback_plan(request, errors)
