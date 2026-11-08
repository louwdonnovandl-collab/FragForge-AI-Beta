# FragForge v0.10.29 — Mr Director hide-window repair

Fixed:
- Windows build workflow now bundles the `assets/` directory (previously omitted), so Mr Director's art can load in the installed EXE.
- Clicking Mr Director OR his speech bubble says "Okay, I'll hide!" and hides the ENTIRE AI chat window after 850 ms.
- A half-head tab remains visible at the RIGHT edge of the main editor.
- Clicking the half-head restores the whole chat window and speech bubble.
- Mr Director's window is now modeless, so the editor stays usable while the assistant is open.
- Fixed chat text formatting for the greeting.
- The existing Ollama local model and offline fallback remain.

Test after rebuilding via GitHub Actions. The EXE is not runtime-tested in this environment.
