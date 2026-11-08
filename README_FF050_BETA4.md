# FF_050 Beta.4 source update

- Qwen3 reasoning enabled in chat; final answers extracted after `</think>` and shown in full.
- Existing GUI shows a thinking status while its QThread runs.
- Eco 2GB, Balanced 4GB, Accelerated 8GB monitored target budgets.
- 10% tolerance and 5-second continuous sampled exceedance above 110% before a vision safety stop.
- Memory check is sampled before and after each frame; this is not a hard process cap and does not guarantee prevention of OS out-of-memory.
- Existing Beta.3 Refresh AI and single-job coordination retained.
- Windows executable has not been tested; validate with a short chat request before scanning long footage.
