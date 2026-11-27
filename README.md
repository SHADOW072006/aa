# TeleMonitor — Telegram Threat Intelligence & Illegal Trade OSINT Platform

TeleMonitor is a full-spectrum Open Source Intelligence (OSINT) and threat monitoring dashboard for Telegram. It provides automated reconnaissance, deep channel profiling, entity extraction, syndicate network graph analysis, and forensic PDF report generation across public Telegram channels and criminal groups.

---

## Key Capabilities

- **Automated Public Channel Scanner**: Conducts reconnaissance using 62 curated `illegal_trade` seed terms across 6 core categories (`drugs`, `arms`, `fake_documents`, `mule_accounts`, `cards`, `sim_cards`), with investment/gambling/scam seeds isolated in separate optional profiles.
- **Deep Channel Intelligence Dossiers**: Click any channel to inspect a full forensic dossier: subscriber count, bio, verified/scam warnings, threat score %, detected crime taxonomies, and complete flagged message transcripts with view counts, forward sources, and timestamps.
- **Connecting Nodes & Syndicate Network**: Interactive visual Cytoscape graph showing all connecting nodes linked to a channel—including forwarded source channels, cross-mentions, admin handles, and shared payment instruments (UPI, phone numbers, crypto wallets) connecting multiple channels into coordinated crime syndicates.
- **Forensic PDF Export**: One-click generation of professional forensic reports and intelligence dossiers powered by ReportLab:
  - **Full Threat Scan Report**: Executive summary, threat matrices, high-risk channel rankings, and extracted payment instruments across entire scan runs.
  - **Channel Intelligence Dossier**: In-depth target profile, syndicate links, contact nodes, and intercepted evidence transcripts.
- **Multi-Sector Crime Detection**: Tuned lexicon scorers and hybrid ML classifiers covering 10 major crime categories:
  - Cybercrime & Dark Web (Ransomware, Stealers, Carding, Phishing kits, RAT malware, DB leaks)
  - Financial Fraud & Mule Banking (Mule accounts, ATM card sale, Corporate netbanking, OTP bots)
  - Hawala & Money Laundering (Black money conversion, Flash USDT, Angadia, Shell companies)
  - Narcotics & Controlled Substances (MDMA, Meth, Heroin, Ganja, LSD, Prescription pills)
  - Arms & Ammunition (Desi Katta, Pistols, Tamancha, 9mm ammo, Automatic weapons)
  - Forged Documents & Counterfeit Currency (Fake Aadhaar, PAN, Passports, Degrees, FICN / Fake INR)
  - Extortion & Blackmail (Sextortion, Honey traps, Loan app harassment, Video blackmail)
  - Human Trafficking & Exploitation (Flesh trade, Escort rackets, CSAM signals)
  - Illegal Betting & Gambling Scams (Color trading scams, Satta Matka, Cricket betting IDs)
  - Illicit Trade & Smuggling (Gold smuggling, Stolen mobile devices, IMEI wiping)

---

## Architecture

```
tele/
├── backend/
│   ├── app/
│   │   ├── api/          # REST endpoints (alerts, channels, scan, graph, discovery, search)
│   │   ├── classifiers/  # Lexicon probabilistic scoring + scikit-learn TF-IDF classifier
│   │   ├── collectors/   # Telethon MTProto scanner, continuous collector & discovery engine
│   │   ├── db/           # SQLAlchemy models, SQLite engine & auto-migration
│   │   ├── extractors/   # Regex & Phonenumbers extractors (Phone, UPI, Crypto, Handles, URLs)
│   │   ├── graph/        # NetworkX entity co-occurrence & syndicate cluster builder
│   │   └── reports/      # ReportLab forensic PDF report generator
│   └── tele_monitor.db   # Local persistent database
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios client & typed API interfaces
│   │   ├── components/   # ChannelDetailModal, AlertCard, StatCard
│   │   └── pages/        # Dashboard, Scan, Channels, Alerts, Graph, Search, Import
├── data/
│   ├── lexicons/         # JSON slang dictionaries for 10 crime categories
│   └── models/           # Trained ML classification pipelines (.joblib)
└── scripts/
    └── train_classifier.py
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node 20+
- Dedicated Telegram account and API credentials from [my.telegram.org/apps](https://my.telegram.org/apps)

### 2. Backend Setup

```bash
cd backend
cp .env.example .env
# Fill in TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env

# Virtual environment setup
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Initialize & Start Backend

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

*On the very first launch, Telethon will ask for the Telegram OTP in the terminal to generate `monitor_session.session`. Subsequent starts run completely headless.*

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### 5. Production Docker Deployment

```bash
cp backend/.env.example backend/.env
# Populate real credentials in backend/.env
docker compose up --build
```

---

## API Reference

### Channel & Intelligence Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/channels/` | List all monitored watchlist channels with status & member counts |
| `POST` | `/channels/` | Add a public channel to the continuous monitoring watchlist |
| `DELETE` | `/channels/{id}` | Deactivate a channel from active polling |
| `GET` | `/channels/{id_or_username}/details` | Complete forensic dossier (profile, threat score, categories, all extracted identifiers, sample intercepts) |
| `GET` | `/channels/{id_or_username}/network` | Cytoscape-formatted ego-network graph of all connecting nodes, admins, and shared syndicate channels |
| `GET` | `/channels/{id_or_username}/export/pdf` | Download forensic PDF intelligence dossier for this specific target channel |

### Multi-Crime Public Scanner Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/scan/run` | Launch a public channel scan across crime seeds in background |
| `GET` | `/scan/jobs` | List recent scan runs with progress, channels scanned, and flagged counts |
| `GET` | `/scan/jobs/{id}` | Status and live metrics for a specific scan job |
| `GET` | `/scan/jobs/{id}/results` | Query discovered channels with filters (`risk_level`, `category`, `search`, pagination) |
| `POST` | `/scan/jobs/{id}/add-channel/{result_id}` | Promote a discovered channel directly into the monitored watchlist |
| `GET` | `/scan/jobs/{id}/export/pdf` | Download executive PDF threat scan report for the entire scan run |
| `GET` | `/scan/results/{result_id}/export/pdf` | Download individual channel PDF dossier from a scan result |
| `GET` | `/scan/seeds` | Retrieve the 62 default `illegal_trade` seeds and category distribution |

### Alerts, Graph & Import Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/alerts/` | Filtered list of flagged intercepts (`risk_level`, `reviewed`, pagination) |
| `GET` | `/alerts/stats` | Aggregated threat counts by risk tier (HIGH, MEDIUM, total) |
| `GET` | `/alerts/{id}` | Single alert with matched evidence and entity links |
| `PATCH` | `/alerts/{id}/review` | Mark an alert as reviewed by an analyst |
| `GET` | `/graph/` | Full global entity co-occurrence graph (Cytoscape JSON) |
| `GET` | `/graph/ego/{identifier}` | Sub-network graph centered around a single identifier |
| `GET` | `/search/identifier` | Search any phone, UPI, handle, or crypto wallet across all channels |
| `POST` | `/import/csv` | Ingest external CSV datasets of Telegram messages |
| `POST` | `/import/json` | Ingest external JSON dump files |

Interactive Swagger documentation: `http://localhost:8000/docs`

---

## Intelligence & Forensic Workflows

### 1. Launching a Multi-Crime Reconnaissance Scan
1. Open the **Scanner** tab in the UI.
2. Select **Run Scan** (runs with 60+ built-in multi-domain crime terms) or input custom keywords.
3. As the scanner discovers channels in real-time, view live progress counters (Found, Scanned, Flagged).
4. Filter results by **Risk Level** (HIGH / MEDIUM) or **Crime Category** (Cybercrime, Narcotics, Mules, Weapons, etc.).

### 2. Inspecting Channel Profiles & Connecting Nodes
1. Click on any channel row in the Scan Results, Monitored Watchlist, or Alerts list.
2. The **Intelligence Dossier Modal** appears with three tabs:
   - **Intelligence Dossier**: Overview, bio/description, threat score, verified/scam indicators, and copyable financial instruments (UPI, phone, crypto).
   - **Connecting Nodes & Network**: Interactive Cytoscape visual graph displaying connecting channels (forwards, cross-mentions), admin handles, and shared payment nodes linking multiple channels in a syndicate.
   - **Intercepted Messages**: Full transcripts of flagged messages, view counts, forwards, and matched crime terms.

### 3. Forensic PDF Reports
- **Full Scan Report**: Click **Export Full Scan PDF Report** at the top of any completed scan job to download an executive threat summary with high-risk channel rankings.
- **Single Channel Dossier**: Click **PDF** on any channel row or in the Channel Modal to download a forensic target dossier ready for investigative documentation.

---

## Legal & Operational Security Notice

- **Public Channels Only**: The system exclusively monitors public Telegram channels. It does not access private channels, group chats, or direct messages.
- **Local Sovereignty**: All collected messages, database records, and generated PDF reports reside strictly on your local machine.
- **Operational Security (OPSEC)**: Run the monitor behind a dedicated VPN or SOCKS5 proxy to prevent IP disclosure to hostile channel administrators. Use a dedicated monitor SIM card and Telegram account.

---

## TeleMonitor Intelligence Platform — v2 Features

### Seed Profile Management
Analysts can create normalised seed profiles with auto-generated query variants (spacing, hyphen, transliteration). Each seed tracks performance metrics: variants, executions, channels found.

### Evidence Persistence
Every classified message with a score ≥ 0.3 is persisted as `ScanEvidence` with full classification metadata, normalised text, extracted identifiers, and analyst disposition tracking.

### Pivot Intelligence
Entity pivots (phone numbers, Telegram handles/links, emails, domains) are automatically extracted from high-scoring messages and queued for analyst review. Approved pivots trigger new discovery cycles.

### Composite Channel Scoring
Each channel scan produces a composite risk score (0–1) weighted across: max message score, high-confidence message count, distinct incident tiers, recency, identifier density, valid pivot count, and analyst confirmation signal.

### Analyst Disposition Workflow
Alerts and evidence items can be dispositioned as `confirmed_threat`, `false_positive`, `needs_review`, or `escalated`, with full audit trail.

### Adaptive Poll Tiers
Channels are assigned HIGH (30s), MEDIUM (60s), or LOW (300s) poll tiers with exponential backoff on FloodWait errors and automatic error-state tracking.

### New API Endpoints
- `GET/POST /seeds/` — seed profile management
- `GET /pivots/` + approve/reject — pivot queue
- `GET /evidence/` — scan evidence browser
- `POST /dispositions/alerts/{id}` + `/evidence/{id}` — disposition controls
- `GET /channels/{id}/health` — channel health and poll tier

### New Frontend Pages
- `/seeds` — Seed Performance Page
- `/pivots` — Pivot Queue Page

---

## Running Tests (Windows / Local Development)

Backend tests target **Python 3.12** with pinned `pytest==9.2.0` and `pytest-asyncio==1.5.0` (see `backend/requirements-test.txt` and `backend/pytest.ini`).

1. Activate the project-local virtual environment (or use the Python 3.12 interpreter consistently):
   ```powershell
   cd backend
   .\.venv\Scripts\Activate.ps1
   ```
2. Run the Stage A–D focused tests:
   ```powershell
   python -m pytest tests/unit/test_reclassification.py tests/unit/test_alert_lifecycle.py tests/unit/test_provenance_presentation.py tests/unit/test_access_control.py -q
   ```
3. Run the full backend test suite (isolated from `tele_monitor.db` and Telegram network sessions):
   ```powershell
   python -m pytest -q
   ```
4. Build the frontend production bundle:
   ```powershell
   cd ..\frontend
   npm run build
   ```

---

## PS02 Demo Dataset & Real-Data Switch Protocol

### Importing & Evaluating PS02
```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"
python scripts/import_ps02.py   # builds data/local/ps02_demo/ps02_demo.db (OCR cached in ocr_cache.json)
python scripts/eval_ps02.py     # scores against 99_answer_key and writes eval_report.json
```

### Real-Data vs. PS02 Demo Isolation
- **Live / Docker real-data mode**: `docker-compose.yml` mounts the persistent `telemonitor_db` Docker volume at `/var/lib/telemonitor/tele_monitor.db` (never overwritten by PS02 scripts).
- **PS02 demo mode**: `scripts/import_ps02.py` targets `data/local/ps02_demo/ps02_demo.db` by default (gitignored). To preview the PS02 database in the API locally without touching `backend/tele_monitor.db`, set `DATABASE_URL=sqlite+aiosqlite:///../data/local/ps02_demo/ps02_demo.db` and `DISABLE_BACKGROUND_TASKS=1` before launching `uvicorn`.
- **Never** import PS02 demo records into `tele_monitor.db` or commit `data/local/`.
