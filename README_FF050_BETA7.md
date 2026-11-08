# FF_050 Beta.7 — blood-visual candidate recognition (experimental)

This build adds single-frame blood-splatter **candidates** to the existing local Ollama vision analysis. The classifier asks the model for `blood_splatter` and `blood_confidence`, and the recognition marker review/export shows candidates with estimated confidence >= 0.5. These are not confirmed new splatters, hits, or kills. This does not yet implement temporal frame comparison, a dedicated trained blood detector, or the requested simplified autonomous editor UI.

## Test
1. Build on GitHub Actions and launch on Windows with Ollama and qwen3-vl:2b installed.
2. Load a recording containing known blood effects; open Mr Director and request analysis.
3. Review AI markers and export the JSON. Check `blood_splatter_candidate` timestamps against the original video and report false positives.
4. Do not apply edits unless the preview is valid. If analysis stalls, use Cancel/Back to Assistant; cancellation of an active HTTP request may still be delayed.

**Known limitation:** full end-to-end analysis, cancellation, and timeline/music insertion are not verified by these source-level tests. The 50-song library from Beta.6 is retained.
