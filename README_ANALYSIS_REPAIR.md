# FragForge v0.10.19 — analysis engine repair

- One FFmpeg analysis pass instead of two serial scans.
- Reads FFmpeg progress through a background pipe reader; captures scene timestamps from stderr file.
- Terminates a stalled process after 30 seconds without progress, or at a bounded overall runtime.
- Adds Cancel analysis button.
- Errors surface in the UI instead of indefinite animation.
- Uses 2 fps, 320-pixel frames for lightweight scene analysis.
- This is offline scene-change detection, not semantic kill detection.
- Keep a backup of your working v0.10.14 or v0.10.18 build.
