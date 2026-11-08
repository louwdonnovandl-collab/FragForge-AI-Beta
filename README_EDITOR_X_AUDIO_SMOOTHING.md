# Editor-X — automatic montage audio and transition tuning

Changes to AI-generated montages only:
- Gameplay V1 source audio defaults to 42% rather than potentially overwhelming SFX.
- Transition sound cues default to 40% and have a 120 ms fade.
- Activity sound cues default to 34% with a 120 ms fade.
- Background music defaults to 24%, with up to 750 ms fade at each music segment edge.
- Video cuts use short 180 ms (maximum) fades, with shorter fades for short clips.
- Original user-editable clip volume controls remain available.

This is level balancing and short fades, **not** true overlapping video crossfades or dynamic sidechain ducking. Some abrupt scene changes may remain. These settings require a Windows render/listening test before being considered verified.
