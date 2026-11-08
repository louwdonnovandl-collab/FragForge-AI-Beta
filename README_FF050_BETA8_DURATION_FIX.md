# FF_050 Beta.8 duration correction

- Explicit 60-second requests now default to 1.0x unless the user explicitly asks for another speed.
- Timeline validation requires final V1 playback duration to match the requested duration (within tolerance); a shorter edit is no longer silently accepted.
- When combat-focused candidate windows cannot fill the requested duration, the planner makes another pass across the full source using ranked activity evidence, without falsely claiming additional kills.
- Music continues to match the actual output timeline duration.

Limitations: the app still needs a real Windows export test. When there is insufficient source footage, the edit is rejected rather than inventing extra footage. This does not guarantee semantic combat accuracy.
