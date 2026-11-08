# Editor-X 2.0 — Audio Intelligence Patch

## Fixed in the actual editor code
- Removed automatic `board_001` / `board_003` sound cues at montage clip boundaries.
- Removed automatic `board_024` sound cues triggered only by visual contrast peaks.
- Disabled the automatic sound-cue checkbox; it cannot be silently re-enabled by parsed AI requests.
- Existing user-inserted SFX clips are preserved. This patch does **not** automatically delete sound clips from saved projects.

## New module: `audio_intelligence.py`
- FFmpeg-based streaming audio measurement (low memory).
- Time-stamped RMS loudness, peak loudness, silence and sudden loudness-change candidates.
- Non-destructive inspection of automatic cue labels in an existing timeline.
- Does not claim to recognize gunshots, speech, or particular events.

## Next integration steps
- Wire audio analysis to the Prepare Edit worker and show its results in Preview Edit.
- Add optional local sound event classifier and speech transcription.
- Link event evidence to video timestamps; add SFX only on explicit request/verified event.
- Implement music continuity and dialogue-aware ducking; test MP4 export on Windows.
- Add safe UI action to review and remove legacy automatically generated cues from current timeline.

## Validation
`python -m unittest test_audio_intelligence test_editor_x_brain -v`

Source-based checks only. Windows GUI and real exported video not tested here.
