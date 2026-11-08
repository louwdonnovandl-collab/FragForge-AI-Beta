# FragForge AI v0.10.27 — Mr Director (local)
Mr Director is a red-haired anime assistant with a speech bubble and chat-based editing requests.
No OpenAI API is used. The application connects only to local Ollama at `http://127.0.0.1:11434`.

## Windows setup
1. Install Ollama from https://ollama.com/download/windows
2. In PowerShell: `ollama pull qwen3:4b`
3. Start Ollama (normally launches automatically).
4. Launch FragForge, open AI Director, press **Connect**, then **Ask Mr Director**.
5. Review the plan and select **Run Edit** to start existing video analysis.
6. Approve timeline changes separately in the Auto Edit window.

If Ollama is not installed, Mr Director falls back to the offline instruction parser.
No online search is performed in this version. Video understanding, automatic captions,
generated intros and kill-triggered effects are NOT implemented yet.
The supplied character art is embedded as an image; animation is not yet implemented.
Model processing may use GPU memory while running.
