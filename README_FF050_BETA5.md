# FragForge FF_050 Beta.5 — targeted analysis and music safeguards

- Keeps prior Beta.4 Qwen reasoning, AI modes, and Refresh AI.
- Progress no longer reaches 100% before the complete analysis result is delivered. The initial scene-analysis stage is capped at 95% when vision is enabled; vision progress stays below 100% until results are ready.
- After 180 seconds without a progress update, displays an explicit possible-stall warning and instructs cancellation. This is a warning, not a worker timeout; long-running Ollama calls may still need investigation.
- Exact music title requests no longer silently select an unrelated first track. If no exact title or recognized genre matches, the chooser returns no selection.
- The music library is BYO licensed tracks, up to 50. No audio songs are bundled. Existing music-file insertion remains, but a completed render with a chosen song has not been verified in this environment.
- This is a source package, NOT a tested Windows build. Run manual GitHub Actions Windows build and verify end-to-end with an actual recording. If analysis still stalls, collect logs/Windows Reliability Monitor details for a deeper worker timeout fix.
