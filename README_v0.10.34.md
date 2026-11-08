# FragForge AI v0.10.34 — Director AI Repair

## Fixes
- Ollama calls use a bounded context and token budget to reduce timeouts and GPU load.
- Detailed HTTP error bodies are displayed in chat for diagnosis instead of only "HTTP 500".
- Chat endpoint failure retries through the generate endpoint.
- Qwen thinking text is removed from visible replies, even if Ollama ignores `think: false`.
- AI plan errors are identified as failures; offline suggestions are explicitly labelled.
- Central `version.py` controls version display and the GitHub Actions artifact name.
- Workflow reads the version automatically and verifies Python source syntax before building.

## Known limitations
- No guarantee the Ollama 500 is fixed on every machine; server logs may still be required.
- A successful AI plan still needs review and approval in the editor; it is not an automatic export.
- Gameplay kill/loot detection remains unverified; intro clips are candidates.
- Automatic app updates, AI model updates/uninstall and the 50-track music library are not included in this repair release.

## Windows build
Upload the full contents of this ZIP to the repository root, including `.github/workflows/windows-build.yml` and `version.py`. Trigger GitHub Actions, download the new version-named artifact, and run `FragForge.exe`.
