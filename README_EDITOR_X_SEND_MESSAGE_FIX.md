Editor-X Send Message routing fix

Send Message never invokes run_edit/open_auto_editor. It saves editing instructions and asks local Ollama for a conversational reply. Prepare Edit still initiates analysis immediately. Offline chat retains the saved plan and directs users to Prepare Edit. Windows runtime test pending.
