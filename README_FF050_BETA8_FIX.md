# FF_050 Beta.8 — targeted fix 2

This is a source update, not a verified Windows installer.

- Editing requests sent in chat now route into the actual edit preparation workflow instead of being answered as generic tutorials.
- Built-in genre music is chosen from the full request. A random rock track is chosen for an unspecified rock request, while named tracks retain priority.
- Requested music must exist and have a valid duration before applying. Missing music no longer silently permits an edit without a soundtrack; failed insertion restores the original timeline.
- The working screen has its own tab, one progress bar, Mr Director's avatar, and a lightweight animated writing status. Editing settings remain in a separate Details tab until the larger UI redesign.
- Removed the redundant progress percentage and the visible replace-timeline checkbox. Applying still requires confirmation.

Known limitations: writing animation is a lightweight UI placeholder, not an animated pen over a book. The scene selection algorithm has not yet been redesigned, so repeated candidate highlights and shorter-than-requested outputs may still occur. AI memory orchestration is unchanged. Windows GUI and final export require testing.
