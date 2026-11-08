# FF_049 Beta.1 — Recognition markers (local AI groundwork)

## Implemented
- Evidence-first marker fusion: vision classifications and unclassified audio transients with timestamps.
- Mr Director-readable recognition review: candidate event, confidence, nearby audio indicator, and explicit uncertainty.
- **Review AI markers** button in Auto Edit after a vision scan; optional JSON export for later manual labeling.
- No model retraining or network upload; report stays on the user's machine.
- Unit tests cover correlation, non-invention of gunshots/kills, and report export.

## Known limits / next research
- Current Ollama vision model scans sampled still frames; no temporal action recognition or verified kills.
- Audio scanner detects peaks, not specific gunshots, speech, laughter or explosions.
- No correction UI, dataset ingestion, model fine-tuning or audio classification yet.
- Audio-only marker review is not available without the vision scan enabled.
- Model confidence is self-reported, not calibrated. Always review against source footage.

## Test workflow
1. Enable vision scan and audio scan in Auto Edit; select installed Ollama vision model.
2. Analyze a short gaming clip; select **Review AI markers**.
3. Export JSON, inspect timestamps against video, record false positives/negatives.
4. Do not use markers as confirmed kill events without review.
