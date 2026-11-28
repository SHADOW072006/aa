# TeleMonitor Problem-Statement Compliance Plan

## Context

Project is a FastAPI + React Telegram OSINT monitor. Backend tests pass (330/330) and frontend builds. Need ensure every "Must have" and "Good to have" requirement is covered for the 24-hour final.

## Requirement Mapping

### Must have

1. Import sample dataset or collect from 2-3 public channels and classify posts
   - Already: CSV/JSON import routes, Telegram collector, scanner, classifier, scoring.
   - Task: Add a documented demo flow using provided sample dataset and 2-3 safe public channels.

2. Extract identifiers and link across channels
   - Already: phone/UPI/crypto/handle/URL extractors, entity graph, MinHash near-duplicate linking.
   - Task: Verify extractor coverage against sample labels; add missing identifier types if needed (email, location).

3. Alert dashboard with evidence snapshots
   - Already: alerts API, alerts page, evidence persistence, provenance/hash fields.
   - Task: Ensure every flagged alert includes text, timestamp, channel, hash, and screenshot/media path.

### Good to have

4. OCR of images/posters
   - Partial: import handler references image path/OCR/media hash.
   - Task: Confirm OCR dependency and wiring; add OCR to scanner-collected media if feasible.

5. Hindi/Hinglish slang support
   - Partial: lexicons include Hindi terms.
   - Task: Audit lexicon coverage against sample labelled slang; expand Hindi/Hinglish variants.

6. Automatic evidence report (PDF)
   - Already: ReportLab scan report and channel dossier.
   - Task: Add per-alert evidence PDF export if required by rubric.

## Out of scope (do not implement)

- Private group access, fake identities, seller interaction, private account collection.

## Ordered Implementation Tasks

1. Run demo import with sample dataset; fix any schema/mapping errors.
2. Verify classifier output on labelled sample; tune thresholds/lexicons.
3. Validate identifier extraction against sample expected identifiers.
4. Confirm alert dashboard evidence fields render correctly.
5. Test link-analysis graph on sample identifiers.
6. Complete OCR path and dependency check.
7. Expand Hindi/Hinglish lexicon coverage.
8. Add per-alert PDF export if needed.
9. End-to-end demo rehearsal and test suite run.

## Validation

- Backend pytest full suite passes.
- Frontend build passes.
- Demo run: import sample -> classify -> alerts -> graph -> PDF export.
- Manual check: no private data or seller interaction.

## Open Questions

- Is OCR library installed and licensed for demo environment?
- Should per-alert PDF be required or only scan/channel reports?
- What exact sample dataset schema will R4C provide?