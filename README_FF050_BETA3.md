# FF_050 Beta.3 — Mr Director UI and Ollama safety

This is a **source update**, not a tested Windows executable.

## Changes
- Mr Director window: three tabs (Mr Director, Preview Edit, AI Mode).
- One chat history, duplicate reply bubble hidden.
- AI Mode: Eco 2 GB, Balanced 4 GB (default), Accelerated 8 GB **target** Ollama process memory budgets.
- Modes adjust vision frame count, image size and context length.
- Refresh AI unloads the two FragForge models and checks Ollama's running model list. Models load again on demand. It does **not** kill or restart the shared Ollama daemon; that could disrupt other apps and is not a safe way to guarantee one server process.
- Global job lock blocks a second analysis or chat request while one is active; refresh is blocked while a job runs.
- Vision scan checks Windows llama-server working-set memory before each frame and stops if over the selected target. Memory can spike between checks; the target is **not a hard cap**.
- Cancel requests both FFmpeg and vision workers; Edit Preview warns before closing during active analysis.
- Send Message routes to chat, rather than treating words such as 'kill' as a command to prepare an edit.

## Known limitations
- The Preview Edit tab opens the existing full edit-review dialog; it is not yet embedded in the tab.
- Memory monitor uses `tasklist` and can be approximate. No OS-enforced memory cap.
- Crash root cause not established; Windows executable and long-running analysis have not been tested in this environment.
- Recognition accuracy is unchanged; no model training was performed.

## Test plan
1. Build from source using the existing manual GitHub Actions workflow.
2. Start in Balanced mode. Run short analysis; verify progress and completion.
3. Attempt a second analysis while one is active; expect refusal.
4. Test Refresh AI only when idle, then run `ollama ps` and restart a short analysis.
5. Repeat in Eco, then Accelerated, watching Task Manager for transient memory spikes.
6. Test cancel and closing the preview; report any Windows Reliability Monitor crash details.
