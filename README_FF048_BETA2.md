# FF_048 beta.2 — shorter edit approval and local music library

- A valid shorter-than-requested montage prompts **Keep shorter edit**, **Re-edit**, or **Cancel** instead of automatically rejecting it. Re-edit/Cancel restores the original timeline. Re-edit requires analyzing again with adjusted settings.
- Added a music library folder picker that discovers up to 50 user-supplied audio tracks and selects the first track as a default; the existing music insertion code places the selected track on A2. Users may choose a different file using the existing music picker.
- **No songs are bundled.** Import only tracks you own or are licensed to use. This build does not implement AI music matching, beat syncing, or a 50-track licensed catalog.
- The existing Ollama planning fallback remains under investigation; this update does not claim to fix it.
