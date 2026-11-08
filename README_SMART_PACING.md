# FragForge v0.10.23: Smart Pacing (offline heuristic)

- Full-length AI edit now analyses frame-to-frame motion, removes 5+ second stagnant footage, and offers 2x speed for 12+ second quiet sections.
- Does **not** truly recognize walking, looting, kills, or game events. It is a visual activity heuristic. Preview suggested segments before applying.
- No more randomly timed BOOM effects or soundboard cues in full-length mode. Existing montage effects remain optional, default off for sound.
- Existing fade-in/out at segment boundaries retained.
- Result list shows each segment's source times and speed, plus estimated output duration.
- Preserve original game audio with FFmpeg atempo when speeding video.
- Source and Windows builds need live testing. No neural recognition model is bundled.
