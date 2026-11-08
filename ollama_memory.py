"""Bounded, local-only Ollama model lifecycle helpers.

Only unload named models explicitly used by FragForge; never kill the Ollama service.
"""
import json
import urllib.request

HOST = 'http://127.0.0.1:11434'


def release_model(model, host=HOST, timeout=8):
    """Ask Ollama to unload a specific model, returning (success, message)."""
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
