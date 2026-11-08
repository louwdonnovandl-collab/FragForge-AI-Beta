# FragForge AI v0.10.33 — Director Execution Engine (first implementation)

## New working timeline operations
- Director requests such as "cut it to 20 minutes" are parsed into a target total runtime. The Auto Edit preview selects source segments based on activity, preserves chronological order, and aims for that runtime including the intro.
- A requested 10-second intro is assembled from candidate active gameplay segments and placed at the beginning of V1. These are NOT verified kills. Review the intro and replace wrong clips manually.
- Visual effects on V3 and built-in soundboard cues on A2 are now available in long-form mode and inserted sparingly at cuts, with visual opacity 40%.
- Existing short fade-in/out per clip is applied to long-form edits. This is NOT a true overlapping cross-dissolve and may show dark transitions.
- A post-apply report shows clips, effects, cues and approximate runtime, and errors if assets were skipped.

## Testing
1. Replace GitHub repository source with this ZIP's contents and run the Windows GitHub Actions workflow.
2. Load gameplay onto V1, open Mr Director, connect Ollama, ask for a 10-second intro, sound cues, effects, and a 20-minute output.
3. Click Prepare Edit. Check Auto Edit preview: target 20 min, intro 10 sec, visual/sound checkboxes enabled, duration estimate close to 20 min.
4. Tick 'Replace current timeline' and click 'Apply selected edit'. Confirm the warning. Check the timeline for intro clips, V3 effects and A2 audio.
5. Export a short test first. Check effects, audio mixing, duration and transition quality.

## Limitations
- No semantic recognition of zombie kills, looting, or licensed rock songs; intro candidates are selected from activity data and are not guaranteed action moments.
- Existing motion analysis can misclassify walking/driving. No guaranteed exact 20:00 if available usable footage is shorter.
- Existing FFmpeg exporter may be slow with many clips/effects. Windows execution and rendering have not been tested here.
- No true cross-dissolve or beat-synced audio yet. Manual approval required to replace timeline.
