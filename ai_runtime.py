"""Shared Ollama job coordination and conservative memory profiles.

Ollama is a shared local service: never spawn or kill its daemon from FragForge.
"""
import threading

PROFILES = {
    'Eco': {'budget_gb': 2, 'num_ctx': 1024, 'max_frames': 12, 'image_width': 320},
    'Balanced': {'budget_gb': 4, 'num_ctx': 2048, 'max_frames': 24, 'image_width': 448},
    'Accelerated': {'budget_gb': 8, 'num_ctx': 4096, 'max_frames': 48, 'image_width': 512},
}
_lock = threading.RLock()
_active = None

def acquire(job):
    global _active
    with _lock:
        if _active is not None:
            return False
        _active = job
        return True

def release(job):
    global _active
    with _lock:
        if _active == job:
            _active = None

def busy():
    with _lock:
        return _active is not None

def ollama_ram_gb():
    """Best-effort Windows working-set estimate for all llama-server processes."""
    import os, subprocess, csv, io
    if os.name != 'nt':
        return None
    try:
        p = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq llama-server.exe', '/FO', 'CSV', '/NH'],
                           capture_output=True, text=True, timeout=6,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        total_kb = 0
        for row in csv.reader(io.StringIO(p.stdout)):
            if len(row) < 5 or row[0].lower() != 'llama-server.exe':
                continue
            digits = ''.join(c for c in row[4] if c.isdigit())
            if digits: total_kb += int(digits)
        return total_kb / (1024 * 1024)
    except Exception:
        return None
