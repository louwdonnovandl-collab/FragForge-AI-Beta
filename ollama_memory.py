"""Unload only models owned by FragForge. Never kill a shared Ollama server."""
import json
import urllib.request

HOST = 'http://127.0.0.1:11434'

def release_model(model, host=HOST, timeout=8):
    if not isinstance(model, str) or not model.strip():
        return False, 'No model specified'
    data = json.dumps({'model': model.strip(), 'keep_alive': 0}).encode('utf-8')
    req = urllib.request.Request(host.rstrip('/') + '/api/generate', data=data,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
        return True, str(result.get('done_reason', 'Unload requested'))
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'

def release_models(models, host=HOST):
    return {name: release_model(name, host=host) for name in dict.fromkeys(models) if name}

def running_models(host=HOST, timeout=5):
    with urllib.request.urlopen(host.rstrip('/') + '/api/ps', timeout=timeout) as response:
        return [str(m.get('name', '')) for m in json.load(response).get('models', [])]

def refresh_models(models, host=HOST):
    """Unload FragForge's models and verify Ollama is responding.

    Next AI request automatically loads its selected model again. This does NOT
    terminate/restart the Ollama daemon or affect unrelated applications.
    """
    requested = release_models(models, host=host)
    loaded = running_models(host=host)
    return requested, loaded
