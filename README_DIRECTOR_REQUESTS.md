# v0.10.30 — Mr Director request queue

Fixes: Director now captures explicit kill, looting, intro, fade, effects and sound requests, replies with counts of supported vs unsupported tasks, and carries the queue into Auto Edit. Ollama receives recent text history.

**Not implemented:** gameplay recognition, event-aware effects, automatic kill intro, speech captions. These are marked NOT IMPLEMENTED instead of silently dropped. Existing Auto Edit still only executes its supported operations. This is a request-tracking and communication fix, not a semantic video editor.
