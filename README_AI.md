# FragForge AI v0.10.16 — Auto Edit progress and duration presets

Open AI Tools and select **15-second highlight**, **Custom highlight montage**, or **Full-length edit (up to 1 hour)**. A progress bar reports FFmpeg analysis progress in highlight modes. Full-length mode preserves the selected source footage (up to 3600 seconds) in sequential one-minute timeline segments; it completes planning immediately and is **not** semantic AI analysis. It places occasional effects and soundboard sounds when enabled. Export uses the existing separate render progress bar.

**Important:** A full-hour edit requires at least one hour of source footage. A shorter source remains shorter; the editor does not invent footage. The 15-second preset targets three 5-second highlights where available. Preview and export can be resource intensive for long projects. Scene-change detection is heuristic, not gameplay-event recognition. Windows GUI testing is still required.
