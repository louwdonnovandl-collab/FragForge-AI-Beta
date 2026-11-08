# v0.10.38 — Timeline Verification

- Explicit short requests (up to 5 minutes) open the duration-constrained montage mode.
- Before claiming success, check actual V1 and entire timeline duration against requested runtime.
- Roll back to the previous timeline if validation fails.
- Requested music must actually be placed or the edit is rejected.
- Editing parameters changed after analysis require a new analysis.

**Limitations:** Action peaks are not confirmed kills. Music must be selected by the user. Windows execution and video rendering are not tested here.
