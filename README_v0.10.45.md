# v0.10.45 Vision Response Repair

- Diagnoses empty final responses separately from reasoning-only output and token exhaustion.
- Retries each failed frame once at a larger output budget.
- Keeps successful classifications when some frames fail; reports failed frame count.
- Provides llava:7b as an alternative vision model in the model selector (install via the in-app button).
- Does not interpret thinking as a scene classification or claim verified zombie kills.
- Existing timeline verification and compact UI retained.

Note: Ollama models are not bundled. Windows, FFmpeg, and real video performance require user testing.
