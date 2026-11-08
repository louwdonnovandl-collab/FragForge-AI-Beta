# FragForge AI v0.10.21 — Media removal and undo/redo toolbar

- Added Undo and Redo buttons to the top toolbar, retaining Ctrl+Z and Ctrl+Y shortcuts.
- Added Remove Selected Media button under the Media Library.
- Library removal asks for confirmation, does not delete source files from disk, and leaves timeline clips intact.
- Timeline Delete removes a selected timeline clip, with an undo snapshot.
- Library imports and removals now capture undo history.
- Preserves AI analysis fix from v0.10.20.

Windows Qt runtime still needs testing.
