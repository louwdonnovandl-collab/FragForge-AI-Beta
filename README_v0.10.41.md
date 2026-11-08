# FragForge AI v0.10.41 — Optional automatic combat scan

This first implementation uses an Ollama **vision-capable** model to inspect sampled gameplay still frames. Qwen3:4b alone cannot see the footage. Install a vision model on Windows (example: `ollama pull qwen3-vl:2b`) and ensure Ollama is running. Model availability and hardware fit vary; use a supported vision model if the example is unavailable.

In Mr Director, request a combat-focused short, choose Prepare Edit, enable **Automatically scan gameplay with local vision AI**, select an installed model, then Analyze. The scan samples at most 48 frames from the full recording and identifies *possible* combat frames, not verified kills. It uses those candidate timestamps to prioritize montage clips. It fails closed if no credible candidates are found. Manual timestamps and explicit unverified fallback remain available. Analysis may take minutes and misses short events between sampled frames.

No model weights are included. No model is silently downloaded. Feedback-based model training, continuous video recognition and verified kill counts are **not** implemented yet. This build requires Windows testing.
