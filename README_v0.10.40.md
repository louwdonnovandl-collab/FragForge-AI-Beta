# v0.10.40 — Combat Review & Compact UI

- The Director Edit Preview has a smaller screen-aware default size and scrollable settings/results. Bottom action buttons remain outside the scroll area.
- For combat-focused requests, enter **source-video timestamps** of confirmed combat in the edit preview (e.g. `00:04:32, 00:12:08`). The montage prioritizes footage around those moments, instead of assuming motion equals kills.
- When no combat timestamps are entered, applying a combat-focused edit requires explicit approval to use **unverified** action candidates.
- Existing 60-second target duration and rollback verification remain in place. If insufficient marked combat footage exists to reach the requested duration, timeline validation rejects and restores the old edit. Add more timestamps rather than using unrelated filler.
- **Not included:** automatic semantic zombie-kill recognition. This requires a separately validated gameplay recognition model.

## Test
1. Build using `.github/workflows/windows-build.yml`.
2. Load Project Zomboid footage, ask for a 60-second combat-focused Short, and click Prepare Edit.
3. Enter several known combat timestamps (source video time), Analyze, review candidate clips, check Replace timeline, Apply.
4. Confirm actual 60-second timeline and review combat relevance.
