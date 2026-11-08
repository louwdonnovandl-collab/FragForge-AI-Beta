# FF_048 beta.1 — planning and analysis diagnostics

- Ollama structured planning requests now explicitly request `/no_think`, disable reasoning where supported, and allow up to 120 seconds for non-streaming planning responses.
- The offline planning warning includes bounded error details for troubleshooting.
- Vision progress now retains the stage and timestamp used by the heartbeat instead of being overwritten immediately.
- The analysis progress bar shows a percentage when work reports it and an indeterminate indicator when it cannot.
- When no clips are available, the editor explains how to retry. Combat-only requests still require credible evidence or explicit consent for unverified footage.

**Limitations:** This does not add verified kill detection, transcription, or new effects. A 100% vision scan does not guarantee a usable edit. Windows build and real-media integration testing are still required.
