# FragForge AI v0.10.22 - Long-form auto editor

- Full-length mode uses the full source media duration (up to 60 minutes), not the selected timeline segment's trim.
- A separate 1fps 96x54 grayscale scan detects nearly identical frames persisting at least five seconds.
- Detected stagnant intervals are excluded from the proposed edit; all other footage is preserved in sequence.
- Full-length cuts are split into manageable <=120-second clips.
- Each resulting clip has a short fade-in and fade-out, including export, to soften hard cuts (fade through black, not a true overlapping cross-dissolve).
- Review the suggested retained ranges before applying. Enable Replace Timeline to build a sequential long-form edit.
- This is heuristic static-frame detection, not trained loading-screen recognition. Animated loading screens and slow gameplay may require manual review.
- Long recordings can take time to scan and render. The Windows GUI and real 38-minute recordings remain untested.
