# TeleMonitor — Telegram & Social-Media Illegal Trade Monitor (PS02)

TeleMonitor is a full-spectrum OSINT platform for monitoring **public** Telegram
channels/groups and social-media posts for illegal trade — drug sales, illegal
arms, fake documents, and the sale/rent of bank accounts, ATM kits and SIM
cards (mule-account recruitment). It classifies posts with an explainable
slang/emoji-aware engine, extracts actionable identifiers (phone, UPI, handles,
crypto wallets, bank accounts, IFSC, sites), links them across channels into
syndicate graphs, detects coordinated campaigns, and exports police-grade
forensic PDF dossiers.

---

## Measured Results (official PS02 answer key)

| Metric | Score |
|---|---|
| Classification precision | **1.000** (zero false positives) |
| Classification recall | **0.977** (F1 0.988) |
| Recall by difficulty | easy 1.00 · medium 1.00 · **hard 0.974** |
| Recall by label | drugs 0.97 · arms 0.98 · fake_docs 0.99 · bank 0.97 · ATM 0.99 · SIM 0.98 |
| Identifier F1 | phones 0.99 · sites 0.99 · UPI 0.92 · handles 0.89 · bank accounts 0.74 · wallets 0.66 |
| Coordinated-campaign detection | 86–100% cross-channel coverage |
| Entity linking | 23/28 expected cross-channel identifier links matched |
| Robustness | 54,950 real public Telegram messages also classified — only genuinely criminal content flagged, no noise regression |

Scores are produced by `scripts/eval_ps02.py` against the official dataset's
answer key (`99_answer_key/`, judges only). The pipeline contains no
answer-key references and no dataset-specific hardcoding — it generalises via
vocabulary (objects × intents), Hinglish/Devanagari terms, leetspeak
de-obfuscation, emoji-pair codes (❄️👃 cocaine, 🍀😮‍💨 ganja, 🧸🔫 coded weapons),
and a conversation-context pass for buyer inquiries.

---

## Key Capabilities

- **Dual ingestion** — Telegram Desktop JSON exports (`result.json` with
  segment texts, photos, forwards) and CSV/JSON social posts; every image is
  OCR'd (EasyOCR, English + Hindi) and perceptually hashed for near-duplicate
  detection. A dry-run `POST /import/validate` previews any dataset
  (field mapping, timestamp health, label agreement) before importing.
- **Explainable illegal-sale classifier (intent_v3)** — category anchors +
  sale/recruitment intent + contact-identifier corroboration, with negative
  context (news/awareness), benign-collocation guards ("TXN hash", "weed
  killer", toy guns), and leetspeak de-obfuscation (`g@nja`, `A.T.M`). Every
  alert carries matched terms, reason codes and a score breakdown.
- **Identifier extraction** — phone (incl. words/Devanagari digits), UPI
  (allow-listed PSP suffixes), handles (incl. poster author identity), TRON
  wallets, bank accounts, IFSC, Luhn-validated cards, IMEI, sites, locations
  (gazetteer), emails, t.me links. Only actor identifiers create entity links;
  urls/locations stay evidence.
- **Cross-channel syndicate graph** — shared contacts fuse channels into
  clusters; near-duplicate text (MinHash) and near-duplicate images (perceptual
  hash) surface coordinated campaigns and reseller forwarding.
- **Buyer-inquiry context pass** — short questions that trail a flagged ad in
  the same channel are flagged even without keywords.
- **Police-grade forensic PDFs** — case header, executive summary, identifier
  table with "Also Seen In (Other Channels)" correlation, coordinated-posting
  table, intercept transcripts with OCR-recovered text and SHA-256 chain of
  custody, methodology & handling notes. Unicode fonts render Hindi and
  emoji-bearing channel names.
- **Live recon scanner** — seed-profile-driven public search with rate-limit
  handling, composite channel scoring, watchlist promotion and adaptive poll
  tiers for continuous monitoring.

---

## Architecture

```
tele/
├── backend/app/
│   ├── api/            # REST: alerts, channels, scan, graph, discovery,
│   │                   #       search, seeds, pivots, evidence, governance
│   ├── classifiers/    # intent_v3 explainable rules engine + lexicon loader
│   ├── collectors/     # telegram collector, scanner, Telegram-export importer,
│   │                   # CSV/JSON import + validation, OCR cache
│   ├── db/             # SQLAlchemy models, SQLite engine & auto-migration
│   ├── extractors/     # identifier extractor, normaliser, OCR (EasyOCR en+hi)
│   ├── graph/          # entity graph, chain tracer (NetworkX + MinHash/LSH)
│   ├── reports/        # ReportLab police-grade PDF generator (Unicode fonts)
│   └── services/       # evidence hashing/chain-of-custody, MinHash,
│                       # scoring, seeds, retention, reclassification
├── frontend/src/       # React/Vite dashboard: Dashboard, Alerts, Scanner,
│                       # Channels, Graph, Search, Seeds, Pivots, Import
├── data/
│   ├── lexicons/       # drug / arms / financial-crime slang (JSON)
│   ├── demo/           # self-contained synthetic demo + run_demo.py checks
│   └── local/          # PS02 dataset + demo DB + eval reports (gitignored)
└── scripts/
    ├── import_ps02.py  # rebuild the PS02 database from the official dataset
    ├── eval_ps02.py    # scorecard against the official answer key
    ├── run_demo.py     # end-to-end synthetic demo + acceptance checks
    ├── eval_classifier.py
    └── train_classifier.py
```

---

## Quick Start

### Prerequisites
- Python 3.12 · Node 20+
- Optional for live Telegram scanning: API credentials from
  [my.telegram.org/apps](https://my.telegram.org/apps)
- Optional for OCR: `pip install -r backend/requirements-ocr.txt` (EasyOCR;
  models download to `~/.EasyOCR` on first use)

### 1. Import the PS02 dataset & build the demo database

```bash
python scripts/import_ps02.py    # → data/local/ps02_demo/ps02_demo.db
python scripts/eval_ps02.py      # → scorecard vs official answer key
```

### 2. Run the dashboard on the imported data

```bash
cd backend
set DATABASE_URL=sqlite+aiosqlite:///../data/local/ps02_demo/ps02_demo.db
set TESTING=1
set DISABLE_BACKGROUND_TASKS=1
uvicorn app.main:app --port 8000

cd ../frontend
npm install
node vite-runner.mjs dev         # http://localhost:5173
```

### 3. Live Telegram mode (optional)

```bash
cd backend
copy .env.example .env           # add TELEGRAM_API_ID / API_HASH / PHONE
uvicorn app.main:app --port 8000
```

First launch asks for a Telegram OTP once; afterwards the collector runs
headless and the Scanner performs public-channel discovery searches.

### 4. Docker

```bash
docker compose up --build        # backend :8000, dashboard :5173
```

---

## API Reference (selected)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/channels/{id}/details` | Full forensic dossier (profile, threat score, categories, identifiers, correlated channels, intercepts with OCR) |
| `GET` | `/channels/{id}/network` | Cytoscape ego-network of connecting nodes & syndicate channels |
| `GET` | `/channels/{id}/export/pdf` | Police-grade PDF dossier (exec summary, correlation, campaigns, transcripts, methodology) |
| `GET` | `/channels/{id}/chain/export/pdf` | Cross-channel syndicate-chain investigation PDF |
| `POST` | `/scan/run` · `GET /scan/jobs/{id}` | Background public-channel scans with live metrics |
| `GET` | `/alerts/` · `/alerts/{id}` | Flagged intercepts with evidence, reason codes and coordination signals |
| `GET` | `/alerts/stats` | Risk counts, unreviewed count, top-category histogram |
| `GET` | `/graph/` | Global entity co-occurrence graph (Cytoscape JSON) |
| `GET` | `/search/identifier` · `/search/identifier/export/pdf` | Identifier search + forensic search report |
| `POST` | `/import/validate` | Dry-run import preview (writes nothing) |
| `POST` | `/import/csv` · `/import/json` | CSV/JSON ingestion with dedup, hashing and OCR |
| `GET` | `/seeds/` · `/pivots/` · `/evidence/` · `/governance/*` | Seed profiles, pivot queue, evidence browser, retention/audit |

Interactive Swagger docs: `http://localhost:8000/docs`

---

## Forensic Workflows

1. **Import & validate** — `scripts/import_ps02.py` (Telegram exports +
   social CSV) or `POST /import/validate` for a write-nothing preview of an
   unknown dataset.
2. **Triage** — the Dashboard groups duplicate cross-channel posts into a
   single card ("seen in N channels"); alerts show highlighted matched terms,
   typed copy-able identifier chips and OCR evidence blocks.
3. **Correlate** — the Entity Graph fuses channels by shared contacts,
   near-duplicate text and near-duplicate images; the channel dossier lists
   each identifier's "Also Seen In" channels.
4. **Report** — one-click 12-page police dossier (case header, executive
   summary, correlation tables, transcripts, methodology) or per-identifier
   search reports.

---

## Tests

```bash
cd backend
python -m pytest -q              # 356 tests, isolated from live DB/sessions
cd ../frontend
npx tsc --noEmit                 # frontend type check
```

---

## Legal & Operational Notice

- **Public sources only** — the system never joins private channels/groups,
  never contacts anyone, and stores everything locally.
- All PDFs are framed as **investigative leads, not proof of wrongdoing**,
  with SHA-256 evidence hashes for chain-of-custody verification.
- When operating a live Telegram monitor, use a dedicated account and follow
  your jurisdiction's OSINT handling rules.
