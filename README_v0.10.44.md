# FragForge v0.10.44 — Vision installer launch fix

- Fixes Windows error `Windows cannot find Vision` when clicking Install / update vision AI.
- Starts PowerShell directly and runs the discovered Ollama executable with the selected vision model.
- Preserves the existing multimodal video/audio analysis and collapsible settings.
- Requires Windows build and live installation testing; source syntax checked only.
