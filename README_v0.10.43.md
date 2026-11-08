# FragForge v0.10.43 — Multimodal Director

- Collapsible Edit Preview sections retained.
- Local Qwen3-VL frame classification retained; user can launch `ollama pull qwen3-vl:2b` from the Edit Preview.
- New optional audio transient analysis (FFmpeg, offline, no additional model) runs after vision analysis.
- Audio supports ranking visually identified combat; it does not independently identify gunshots, zombies or confirmed kills.
- The combined analysis can be slow; 48 vision frames is coarse sampling.
- Requires Ollama and installed qwen3-vl:2b for the combined scan.
- Source build only; Windows runtime and model accuracy not yet tested.
