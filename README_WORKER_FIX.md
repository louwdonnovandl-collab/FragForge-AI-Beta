# FragForge v0.10.20 - AI worker startup hotfix

Root cause: AutoAnalysisWorker assigned `self.start=start`, which shadowed the inherited QThread.start() method. Calling `worker.start()` therefore tried to call a float instead of launching the thread. The UI showed a running animation, but no analysis worker ran; cancellation had nothing to cancel.

Fix: renamed the source time attribute to `self.source_start` and updated the analysis invocation. The existing timeout, FFmpeg progress and cancellation logic remains.

Test on Windows with a short video: Analyze should move beyond Starting analysis and produce progress or a specific error. Cancel should work once the worker is running.
