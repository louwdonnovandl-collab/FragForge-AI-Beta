# FragForge v0.10.36 — Intelligent Scene Director (heuristic first stage)

Based on v0.10.35. Keeps the local Qwen3 chat, installation, modern Mr Director interface, and Director timeline execution.

## Changes
- During the existing 1 fps long-form visual scan, record isolated high-motion-change peaks. No additional scan required.
- Select intro source excerpts from the strongest measured peaks when possible; label them as unverified action candidates, never confirmed kills.
- Place restrained V3 effects (40% opacity) and A2 sound cues only at ranked activity peaks, with a minimum 18-second separation and 18-cue cap.
- Place transition sound cues at actual discontinuous source cuts and the start of the intro, not at arbitrary clip indices.
- Record a reason in each effect/audio clip label for inspection.
- Update version and GitHub artifact name automatically through version.py.

## Limitations
This is **not** semantic Project Zomboid recognition. Frame differences can indicate camera movement, UI changes, and other activity; they cannot prove zombie kills, looting, or driving. Sound cues are suggestions and should be reviewed. True cross-dissolves and music licensing remain future work.

## Test
Load a long Project Zomboid video on V1. Ask for a 10-second action intro, 20-minute edit, sound cues, and 40% overlays. Prepare Edit, analyze, review, tick Replace Timeline, and Apply. Check the clip labels and playback. Undo if needed.
