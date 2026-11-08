# FF_050 Beta.8 — first music automation patch

This is a **source-only test build**, not a finished UI overhaul.

- Genre-only requests such as `rock music` now randomly select a bundled track of the requested genre.
- Explicit track names and genre/track-number requests take precedence over random selection.
- A requested music track is selected automatically when opening Director Edit Preview.
- Existing music timeline insertion trims each instance to the remaining video duration and repeats short tracks to fill the montage; the final audio mix still requires Windows testing.
- The replace-timeline checkbox defaults to checked for an explicit Mr Director edit, but an approval confirmation is still required.
- Progress bar text now shows one percentage rather than duplicate text inside the bar.
- The preview window title has been changed as an interim step.

**Not yet implemented:** animated Mr Director writing UI, separate progress tab, removal of all editing checkboxes, complete automatic request routing, model scheduling improvements, or fixes for slow analysis/memory pressure. These remain planned, not tested.

**Tests:** Python compile and local music selection tests. No Windows GUI, Ollama, or full export test performed here.
