# FragForge v0.10.31 — Optional Free AI Installation

Mr Director now has **Install Free AI** next to **Connect**. Click it and approve the download; a PowerShell window opens and uses winget to install Ollama if needed, then pulls `qwen3:4b`. The model is downloaded once, not bundled into the application. After the installer completes, click **Connect**.

The Windows build workflow copies `Install-FragForge-LocalAI.ps1` into the application folder. Keep the script alongside `FragForge.exe` after extracting the build artifact. Installation requires internet access, Windows Package Manager (winget), disk space and user approval. This does NOT add gameplay kill detection or intro rendering; those are separate unfinished editor capabilities.
