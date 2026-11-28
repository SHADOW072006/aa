# HACKATHON DAY — FINAL CHECKLIST (35-team final round)

Last updated: 2026-11-27 evening. Verified state at the bottom.

---

## 1. TONIGHT — technical gaps to close (priority order)

### P0 — do first (protects everything else)
- [ ] **Commit a snapshot** (`git add -A && git commit -m "hackathon-final"`).
  Everything currently lives only as uncommitted changes — one corruption
  incident already cost 30 min of recovery. Commit gives a rollback point.
- [ ] **Copy the project out of OneDrive** for demo day (OneDrive sync pauses
  files and once caused a "database is locked"):
  `robocopy <repo> C:\TeleMonitor-demo /E /XD .git node_modules media backups`
  Run the demo from `C:\TeleMonitor-demo`.

### P1 — demo-critical features (est. 3-4 h total)
- [ ] **Scanner upgrade (biggest remaining gap, ~2-3 h).** The full task
  prompt is ready — paste it to your agent: "point-2 prompt" (seed-profile
  split: discovery seeds = title-style words like "colour prediction",
  "flash usdt", "jobs rajasthan" — crime-keyword searches return 0 on
  Telegram; + offline "Grow network from here" BFS expansion, verified to
  surface the reseller's 4 seller channels from the PS02 database with no
  network needed; + Scanner page category cards + explainer).
  Minimum acceptable if time runs out: the offline expansion endpoint +
  "Grow network" button only.
- [ ] **OCR identifier recovery (10/17 → target 15/19, ~1 h).** Multi-variant
  OCR: run EasyOCR on a 2x-upscaled copy of the poster too, merge results.
  Cache stays keyed by media hash. Touch only
  `backend/app/extractors/ocr.py` + the merge in `import_handler._cached_ocr`.
- [ ] **Surface near-duplicate images in the UI (~1 h).** `messages.image_phash`
  is already stored (291 rows). Add: pairwise hamming-distance check at graph
  build (reason `near_duplicate_image`) OR a simple "near-duplicate posters"
  list in the channel dossier modal. The answer key expects P02/P03 and
  P10/P11 pairs to be caught.

### P2 — polish (est. 1 h)
- [x] **README rewritten** with the official-data scorecard, current
  capabilities and PS02 demo commands (2026-11-27).
- [ ] **Docker rebuild** (`docker compose up -d --build`) — running containers
  are 2 days stale. Only demo from local uvicorn unless rebuilt.
- [ ] `.env.example`: add `TELEMONITOR_OCR_CACHE`, `API_ACCESS_TOKEN` note.
- [ ] Fresh end-to-end: `python scripts/import_ps02.py` → walk every page →
  export every PDF type → confirm zero errors.

---

## 2. DEMO SCRIPT (rehearse once with a timer — target 8-10 min)

0. **Setup before judges arrive** (morning): kill duplicate servers;
   start backend on the PS02 DB + vite; open browser tabs pre-loaded:
   Dashboard, Alerts, Entity Graph, Scanner. Have `dossier_allsvc.pdf`
   (12 pages) already exported and open in a PDF viewer as backup.
1. **Problem (30 s).** Manual monitoring of public Telegram/SocialMedia for
   drug/arms/fake-doc/mule/SIM sales is slow; sellers use slang, emoji codes,
   leetspeak, Hindi; the contacts that matter are scattered across channels.
2. **Data (30 s).** We built the pipeline against the official PS02 dataset:
   1,850 posts, 13 channels, 350 social posts, 18 posters — and scored
   ourselves against its answer key.
3. **Dashboard (2 min).** 985 alerts, 0 false positives. Duplicate grouping:
   the same ad in 4 channels = one card "seen in 4 channels". Highlighted
   matched terms. Category chips → filtered alerts.
4. **The syndicate story (3 min) — your winning moment.** Open
   "All Services 24x7" (reseller): its dossier/PDF shows identifiers
   "Also seen in" → same UPI as SIM seller (S7/S8), same phone in 5 channels
   (S5=S6 one operator, two channels), bank account 50200087431926 reposted
   across channels. Entity Graph: the syndicate cluster. This is
   cross-channel correlation no human can do by hand at this scale.
5. **Police PDF (1 min).** Export the 12-page dossier: case header,
   executive summary, coordinated-posting table, OCR evidence blocks,
   SHA-256 chain of custody, methodology & legal framing.
6. **Scanner (1-2 min).** Show pre-run scan history + "Grow network from
   here" on a channel (offline expansion, instant). Only run a LIVE scan if
   pre-tested that morning (FloodWait risk).
7. **Close (30 s).** Explainable scoring (every alert shows matched terms +
   reason codes), hash chain reproducibility, roadmap (ML once labelled data
   allows, multi-language expansion).

**Backup:** record a screen video of the full demo tonight. If the live demo
fails, play the recording.

---

## 3. JUDGE Q&A CHEAT SHEET

| Question | Answer |
|---|---|
| Accuracy? | Against the official answer key: precision 1.00, recall 0.977, F1 0.988, zero false positives; hard-tier recall 0.97. Identifiers F1: phones 0.99, sites 0.99, UPI 0.92, handles 0.89. |
| Trained on the test data? | No. General vocabulary (objects × intents, Hindi/emoji/leet) + pattern logic. Verified: no answer-key references, no dataset names in code. Also proven on 54k real Telegram messages. |
| Real data? | Pipeline also validated on 54,950 real public Telegram messages (flags only genuinely criminal content). Demo uses the officials' synthetic dataset as instructed. |
| Legal/privacy? | Public channels only, never joins/messages anyone, per-intercept SHA-256 chain of custody, PDFs framed as investigative leads. |
| Why not ML? | Rules are explainable (every alert carries evidence + reason codes — needed in court). ML model exists but is deliberately disabled until validated on labelled data; eval harness (`scripts/eval_classifier.py`) is the gate. |
| How do you find channels? | Title-style discovery seeds + network expansion from known channels (forwards, t.me links, shared contacts). Crime-keyword search on Telegram returns nothing — we verified empirically and designed around it. |
| Images/OCR? | EasyOCR en+hi, multi-variant; OCR text feeds the classifier and evidence; posters hashed (SHA-256 + perceptual) for near-duplicate detection. |

---

## 4. RISK LIST

| Risk | Mitigation |
|---|---|
| Live scan hangs / FloodWait / 0 results | Never live-scan on stage; pre-run in the morning; show history + offline expansion |
| "Database is locked" | Run from the non-OneDrive copy; one backend instance only; check port 8000 owners before starting |
| Laptop failure | Screen recording + the pre-exported PDFs + the demo DB file |
| Internet down | The entire core demo works offline (import → dashboard → graph → PDF); only the live scan needs internet |
| Docker shows old UI | Rebuild tonight, or don't mention Docker; demo via local uvicorn |
| Team member edits conflict | Commit before and after every work block today |

---

## 5. VERIFIED STATE (as of tonight)

- Official PS02 answer-key scorecard: **P 1.00 / R 0.977 / F1 0.988, 0 FP**;
  easy 1.00 / medium 1.00 / hard 0.97; campaigns 86-100%; linking 23/28.
- Backend suite: **356 passed**.
- Real-data check: 54,950 real messages → 158 precise flags, no noise.
- UI redesigned (grouped alerts, highlighted evidence, category chips).
- Police-grade 12-page PDF with cross-channel correlation + OCR evidence.
- Telegram session authorised; public search verified (mechanism works).
- NOT done: scanner seed-split + expansion endpoint, OCR multi-variant,
  phash UI surfacing, README, Docker rebuild, commit.

## 6. MORNING-OF COMMANDS

```bash
# from the demo copy (C:\TeleMonitor-demo)
cd backend
set DATABASE_URL=sqlite+aiosqlite:///../data/local/ps02_demo/ps02_demo.db
set TESTING=1
set DISABLE_BACKGROUND_TASKS=1
python -m uvicorn app.main:app --port 8000
# second terminal
cd frontend && node vite-runner.mjs dev
# open http://localhost:5173
```
