# FragForge AI v0.6.0 — Crossfade preview build

- Adds an export crossfade selector: None, 0.20, 0.35, 0.50, or 1.00 seconds.
- Video joins use FFmpeg `xfade`; audio joins use `acrossfade`.
- Preserves the existing v0.5.1 timeline, preview, trim, split, undo and project features.
- Crossfades are applied on export, **not yet displayed in the preview timeline**.
- Rendering with transitions re-encodes the assembled output and can take longer.
- Each clip must be longer than the selected transition.
- Not tested on Windows in this environment; test a short two-clip project before production use.

Upload the contents of this source folder to the GitHub repository root, replacing files with matching paths. The existing `.github/workflows/windows-build.yml` is retained.
