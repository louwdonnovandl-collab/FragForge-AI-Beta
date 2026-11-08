# Editor-X 2.0 foundation upgrade — Beta 8 source patch

## What this source package actually changes
- Adds `editor_x_brain.py` with deterministic extraction of duration, intro speed, combat/exploration, captions, music genre, transitions, pause/stagnant cleanup.
- Changes local chat identity and instructions to Editor-X; explicitly prioritizes current instructions and existing V1 edits.
- Sends chat to `qwen3:4b` by default; uses `think:false`, larger context and bounded retry; returns a useful **proposal** when Ollama produces no visible answer.
- Refresh AI now clears local chat, pending requests and preview state **after successful model refresh** without touching project media/timeline.
- Rebrands selected old chat messages.

## Important integration boundaries
- The new intent parser is provided as a module; it does **not** replace the legacy `assistant_engine` or `director_executor` rendering pipeline. The existing Prepare Edit workflow still uses its original plan schema.
- Recognition, actual transitions, caption generation, music beat-sync, undo/redo and post-render validation are NOT implemented by this patch. Those require deeper integration and footage testing.
- Refresh AI cannot forcibly cancel an active job; it correctly refuses while jobs are running. Model unloading depends on Ollama.
- The app's other old Mr Director labels may remain elsewhere; full rebrand is not complete.
- This is a source-level integration patch, **not a tested Windows executable**.

## Integration
Replace the same-named files in your FragForge source repository and add `editor_x_brain.py` in the repository root alongside `local_director.py`. Rebuild using your existing GitHub Actions workflow. Test chat, Refresh AI, Prepare Edit and exported results on a copy of your project before using it on important footage.

## Test
Run `python -m unittest test_editor_x_brain.py` from the source folder.
