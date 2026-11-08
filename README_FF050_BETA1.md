# FF_050 Beta.1 — First combined integration checkpoint

Implemented in this package:
- Local music-folder selection (up to 50 user-supplied, licensed files), title/genre metadata and explainable genre-based selection. Optional JSON sidecars can specify `title`, `genre`, `mood`, `license`.
- Requested music no longer blocks applying an otherwise valid edit; a confirmation offers applying without music.
- Analysis progress no longer switches to an endlessly animated indeterminate bar when processing stalls. It holds its last known percentage and shows waiting status.
- Version metadata updated for the Windows GitHub Actions release.

Not yet implemented: a complete multi-tab UI, training from every edit, automatic model fine-tuning, genuine acoustic genre recognition, audio event classification, reliable kill recognition, adaptive RAM management, and bundled 50 licensed songs. Existing recognition markers remain candidates. These require further engineering and validation before release claims.

The music selector uses filename/sidecar metadata, not an AI listening model. User should verify licenses for all music. Do not publish a release ZIP containing copyrighted music without appropriate permission.

Run local checks before starting the manual Windows workflow. Keep previous working release and Git tag for rollback.

## FF_050 Beta.2 — Ollama memory management
- Vision analysis uses a 30-second model keep-alive during frame scanning, then explicitly requests model unload on completion, cancellation, or error.
- Planning and chat API requests use keep_alive=0 to avoid retaining the model after each completed request.
- Director Edit Preview includes a manual Release AI Memory button for the selected vision model and qwen3:4b. Do not press it while analysis is running.
- No force-kill of llama-server and no Ollama service shutdown. Model unload requests are best effort and can take time; check `ollama ps` and Task Manager.
- The requested full multi-tab redesign, continuous learning, and acoustic recognition remain future work. This release is a targeted memory-management build.
