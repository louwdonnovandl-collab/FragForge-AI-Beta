# FragForge v0.10.39 — Prepare Edit Repair

Fixes the disabled/nonresponsive Prepare Edit button after a failed AI request, preserves the last valid plan across follow-up chat, and lets Prepare Edit parse the current instruction without Ollama. Also rejects several patterns of untagged model deliberation.

This is a source-level repair; Windows behavior and export duration require user testing. Kill detection is not implemented.
