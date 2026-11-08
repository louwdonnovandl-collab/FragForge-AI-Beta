# FragForge AI v0.10.35 — Director Chat Reliability

- Qwen3 /no_think instruction on chat requests, plus response cleaning.
- Chat fallback to /api/generate when /api/chat errors or returns an empty visible response.
- Clearer progress and error status, and cleanup of finished QThread workers.
- Retains v0.10.34 GUI, editing engine, and automatic GitHub artifact naming.

## Test
Build with GitHub Actions, open Mr Director, Connect, then Send Message: Hello, reply in one sentence. Wait up to three minutes. If it fails, copy the error in the chat and Ollama server logs.

This source is syntax-checked but not runtime-tested on Windows. Event-specific kill recognition remains unimplemented.
