# FragForge v0.10.18 — Auto Edit feedback hotfix

This build improves the Auto Edit analysis dialog when FFmpeg does not immediately emit progress timestamps.

- Shows elapsed analysis time every second.
- Switches to an indeterminate moving bar after 4 seconds without measurable progress (does not invent a percentage).
- Labels the scan and scene-detection stages.
- Stops the activity indicator on completion or failure.
- Keeps 15-second, custom and one-hour editing modes.

If it still never completes, capture the stage and elapsed time and send them for diagnosis. This package does not claim to resolve every possible FFmpeg hang.
