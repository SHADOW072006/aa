import os

OUT_DIR = r"C:\Users\khowa\OneDrive\Documents\deepseek-harness\default-workspace\tele\deliverables"
os.makedirs(OUT_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PART 1: PRESENTATION (HTML slides — open in browser, press F11 for fullscreen)
# ═══════════════════════════════════════════════════════════════════════════════

presentation_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TeleMonitor — Presentation</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Segoe UI',system-ui,sans-serif; background:#0a0a0a; color:#e0e0e0; overflow:hidden; }
  .slide { display:none; width:100vw; height:100vh; padding:60px 80px; flex-direction:column; justify-content:center; position:absolute; top:0; left:0; }
  .slide.active { display:flex; }
  .slide h1 { font-size:48px; margin-bottom:20px; line-height:1.2; }
  .slide h2 { font-size:36px; margin-bottom:16px; color:#60a5fa; }
  .slide h3 { font-size:24px; margin-bottom:12px; color:#fbbf24; }
  .slide p { font-size:20px; line-height:1.6; margin-bottom:12px; color:#b0b0b0; }
  .slide ul { list-style:none; margin-left:0; }
  .slide li { font-size:20px; line-height:1.8; color:#b0b0b0; padding-left:30px; position:relative; }
  .slide li:before { content:"\u25B8"; position:absolute; left:0; color:#60a5fa; }
  .slide li b { color:#e0e0e0; }
  .slide .highlight { color:#60a5fa; font-weight:600; }
  .slide .accent { color:#fbbf24; }
  .slide .danger { color:#f87171; }
  .slide .grid { display:grid; gap:20px; margin-top:20px; }
  .slide .card { background:#1a1a2e; border:1px solid #333; border-radius:12px; padding:24px; }
  .slide .card h3 { margin-bottom:8px; }
  .slide .card p { font-size:16px; }
  .slide .stat { font-size:56px; font-weight:700; color:#60a5fa; }
  .slide .stat-label { font-size:16px; color:#666; margin-top:4px; }
  .slide .tag { display:inline-block; background:#1e3a5f; color:#60a5fa; padding:4px 12px; border-radius:20px; font-size:14px; margin:4px 4px 4px 0; border:1px solid #2a4a6f; }
  .slide .tag-red { background:#3a1a1a; color:#f87171; border-color:#5a2a2a; }
  .slide .tag-green { background:#1a3a1a; color:#4ade80; border-color:#2a5a2a; }
  .slide .tag-yellow { background:#3a3a1a; color:#fbbf24; border-color:#5a5a2a; }
  .slide-nav { position:fixed; bottom:20px; right:30px; font-size:14px; color:#444; z-index:100; }
  .slide-title-bar { position:fixed; top:20px; left:30px; font-size:14px; color:#333; z-index:100; }
  .arrow-hint { position:fixed; bottom:20px; left:30px; font-size:14px; color:#333; z-index:100; }
  .logo { display:flex; align-items:center; gap:12px; margin-bottom:30px; }
  .logo-icon { width:48px; height:48px; background:#1e3a5f; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:24px; }
  table { width:100%; border-collapse:collapse; margin-top:16px; }
  th { text-align:left; padding:10px 16px; background:#1a1a2e; color:#60a5fa; font-size:16px; border-bottom:2px solid #333; }
  td { padding:10px 16px; font-size:16px; border-bottom:1px solid #222; color:#b0b0b0; }
  .arch-box { background:#1a1a2e; border:1px solid #444; border-radius:8px; padding:14px 18px; text-align:center; font-size:15px; margin:6px 0; }
  .arch-arrow { text-align:center; color:#555; font-size:18px; margin:2px 0; }
  .pipeline { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:20px; }
  .pipeline-step { background:#1a1a2e; border:1px solid #444; border-radius:8px; padding:12px 20px; font-size:16px; text-align:center; }
  .pipeline-arrow { color:#555; font-size:20px; }
</style>
</head>
<body>

<!-- Slide 1: Title -->
<div class="slide active" id="s1">
  <div class="logo">
    <div class="logo-icon">\u{1F6E1}\u{FE0F}</div>
    <div>
      <h1 style="margin:0; font-size:42px;">TeleMonitor</h1>
      <p style="margin:0; font-size:20px; color:#666;">OSINT Intelligence Platform for Illegal Trade Detection</p>
    </div>
  </div>
  <h2 style="margin-top:40px;">Telegram &amp; Social Media Illegal Trade Monitor</h2>
  <p style="font-size:22px; margin-top:8px;">Drugs \u00B7 Arms \u00B7 Bank Accounts &amp; ATM Cards \u00B7 Fake Documents</p>
  <div style="margin-top:30px;">
    <span class="tag tag-red">Drug Sale Detection</span>
    <span class="tag tag-red">Arms Trafficking</span>
    <span class="tag tag-yellow">Mule Account Recruitment</span>
    <span class="tag tag-yellow">Financial Crime</span>
    <span class="tag tag-green">Identifier Extraction</span>
    <span class="tag">Entity Graph Analysis</span>
    <span class="tag">OCR &amp; Hindi/Hinglish</span>
  </div>
  <p style="margin-top:40px; font-size:18px; color:#555;">Round 1 Submission \u00B7 Hackathon Presentation &amp; Wireframe</p>
</div>

<!-- Slide 2: Problem Statement -->
<div class="slide" id="s2">
  <h2>The Problem</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr;">
    <div class="card">
      <h3 class="danger">\u{1F534} The Threat Landscape</h3>
      <p>Drug peddlers and mule-account recruiters operate through <b>public Telegram channels</b> and social media, using:</p>
      <ul style="margin-top:12px;">
        <li><b>Coded slang</b> and regional language (Hindi/Hinglish)</li>
        <li><b>Emojis</b> as visual shorthand for products</li>
        <li><b>Cross-channel coordination</b> \u2014 same seller across 5+ channels</li>
        <li><b>Image-based ads</b> (posters) bypassing text filters</li>
      </ul>
    </div>
    <div class="card">
      <h3 class="accent">\u{1F4CB} Manual Monitoring Fails</h3>
      <ul style="margin-top:12px;">
        <li>Police manually browse channels \u2014 <b>slow and inconsistent</b></li>
        <li>Seller identifiers (phone, UPI, handles) <b>never collated</b> across channels</li>
        <li>No <b>forensic evidence chain</b> for prosecution</li>
        <li>Scale is <b>impossible</b> \u2014 thousands of channels, millions of posts</li>
      </ul>
    </div>
  </div>
  <div style="margin-top:30px; padding:20px; background:#1a1a2e; border-left:4px solid #f87171; border-radius:8px;">
    <p style="font-size:22px; color:#f87171;"><b>"We need automated, slang-aware monitoring that extracts actionable identifiers and preserves evidence for prosecution."</b></p>
  </div>
</div>

<!-- Slide 3: Solution Overview -->
<div class="slide" id="s3">
  <h2>Our Solution: TeleMonitor</h2>
  <p style="font-size:22px; margin-bottom:30px;">An end-to-end OSINT intelligence platform that <span class="highlight">collects, classifies, extracts, links, and alerts</span> on illegal trade across public Telegram channels.</p>
  <div class="pipeline">
    <div class="pipeline-step">\u{1F4E1}<br><b>Collect</b><br><span style="font-size:13px;color:#888;">Telegram + CSV/JSON Import</span></div>
    <div class="pipeline-arrow">\u2192</div>
    <div class="pipeline-step">\u{1F50D}<br><b>Classify</b><br><span style="font-size:13px;color:#888;">Slang Lexicon + ML</span></div>
    <div class="pipeline-arrow">\u2192</div>
    <div class="pipeline-step">\u{1F3F7}\u{FE0F}<br><b>Extract</b><br><span style="font-size:13px;color:#888;">Identifiers + OCR</span></div>
    <div class="pipeline-arrow">\u2192</div>
    <div class="pipeline-step">\u{1F578}\u{FE0F}<br><b>Link</b><br><span style="font-size:13px;color:#888;">Entity Graph</span></div>
    <div class="pipeline-arrow">\u2192</div>
    <div class="pipeline-step">\u{1F6A8}<br><b>Alert</b><br><span style="font-size:13px;color:#888;">Dashboard + PDF</span></div>
  </div>
  <div class="grid" style="grid-template-columns:1fr 1fr 1fr; margin-top:40px;">
    <div class="card">
      <h3 style="color:#4ade80;">Must Have</h3>
      <ul>
        <li>Import sample dataset &amp; classify posts</li>
        <li>Extract identifiers &amp; link across channels</li>
        <li>Alert dashboard with evidence snapshots</li>
      </ul>
    </div>
    <div class="card">
      <h3 class="accent">Good to Have</h3>
      <ul>
        <li>OCR of images and posters</li>
        <li>Hindi / Hinglish slang support</li>
        <li>Automatic evidence report (PDF)</li>
      </ul>
    </div>
    <div class="card">
      <h3 class="danger">Out of Scope</h3>
      <ul>
        <li>Joining private groups</li>
        <li>Interacting with sellers</li>
        <li>Private account access</li>
      </ul>
    </div>
  </div>
</div>

<!-- Slide 4: Architecture -->
<div class="slide" id="s4">
  <h2>System Architecture</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr; gap:30px;">
    <div>
      <h3>Backend (FastAPI + SQLAlchemy)</h3>
      <div class="arch-box" style="border-color:#60a5fa; color:#60a5fa;"><b>Telegram Collector</b><br><span style="font-size:13px;color:#888;">Telethon MTProto \u00B7 Public channels only</span></div>
      <div class="arch-arrow">\u2193</div>
      <div class="arch-box" style="border-color:#fbbf24; color:#fbbf24;"><b>Classifier</b><br><span style="font-size:13px;color:#888;">Lexicon scorer + ML (TF-IDF + LogisticRegression)</span></div>
      <div class="arch-arrow">\u2193</div>
      <div class="arch-box" style="border-color:#4ade80; color:#4ade80;"><b>Identifier Extractor</b><br><span style="font-size:13px;color:#888;">Phone \u00B7 UPI \u00B7 Handle \u00B7 Wallet \u00B7 Email \u00B7 URL</span></div>
      <div class="arch-arrow">\u2193</div>
      <div class="arch-box" style="border-color:#a78bfa; color:#a78bfa;"><b>Entity Graph</b><br><span style="font-size:13px;color:#888;">Co-occurrence linking + NetworkX visualisation</span></div>
      <div class="arch-arrow">\u2193</div>
      <div class="arch-box" style="border-color:#f87171; color:#f87171;"><b>Alert Engine + PDF Reports</b><br><span style="font-size:13px;color:#888;">ReportLab forensic evidence dossiers</span></div>
    </div>
    <div>
      <h3>Frontend (React + Vite + Tailwind)</h3>
      <div class="arch-box"><b>Dashboard</b><br><span style="font-size:13px;color:#888;">Live stats \u00B7 Risk overview \u00B7 Recent alerts</span></div>
      <div class="arch-box"><b>Alerts Page</b><br><span style="font-size:13px;color:#888;">Evidence snapshots \u00B7 Disposition workflow</span></div>
      <div class="arch-box"><b>Scanner</b><br><span style="font-size:13px;color:#888;">Multi-seed search \u00B7 Channel scoring \u00B7 PDF export</span></div>
      <div class="arch-box"><b>Entity Graph</b><br><span style="font-size:13px;color:#888;">Cytoscape.js interactive network</span></div>
      <div class="arch-box"><b>Channel Intelligence</b><br><span style="font-size:13px;color:#888;">Deep dossier \u00B7 Connected nodes \u00B7 Identifiers</span></div>
      <div class="arch-box"><b>Seed Management</b><br><span style="font-size:13px;color:#888;">Analyst-configurable search terms \u00B7 Variants</span></div>
    </div>
  </div>
</div>

<!-- Slide 5: Key Features Detail -->
<div class="slide" id="s5">
  <h2>Key Features in Detail</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr; gap:20px; margin-top:20px;">
    <div class="card">
      <h3 style="color:#60a5fa;">\u{1F50D} Slang-Aware Classifier</h3>
      <ul>
        <li><b>5 lexicons</b>: drugs, financial crime, arms, scams, extended crime</li>
        <li><b>200+ terms</b> with category and weight (0\u20131)</li>
        <li><b>Emoji recognition</b> (\u{1F33F} cannabis, \u{1F489} injection, \u{1F9CA} meth)</li>
        <li><b>Context guard</b>: ambiguous terms need co-signal</li>
        <li><b>Word-boundary matching</b>: "ice" \u2260 "price"</li>
        <li><b>Hindi/Hinglish</b>: "ganja", "charas", "kyc chahiye"</li>
      </ul>
    </div>
    <div class="card">
      <h3 class="accent">\u{1F3F7}\u{FE0F} Identifier Extraction</h3>
      <ul>
        <li><b>Phone</b>: E.164, local Indian formats</li>
        <li><b>UPI IDs</b>: name@bank pattern</li>
        <li><b>Crypto wallets</b>: BTC, ETH, USDT addresses</li>
        <li><b>Telegram handles</b>: @username extraction</li>
        <li><b>Telegram links</b>: t.me/channel detection</li>
        <li><b>Email + URLs</b> for contact tracking</li>
      </ul>
    </div>
    <div class="card">
      <h3 style="color:#4ade80;">\u{1F578}\u{FE0F} Entity Graph &amp; Link Analysis</h3>
      <ul>
        <li><b>Co-occurrence edges</b>: identifiers in same message are linked</li>
        <li><b>Cross-channel mapping</b>: same phone appears in 5 channels</li>
        <li><b>Interactive visualisation</b> with Cytoscape.js</li>
        <li><b>Ego graph</b>: trace one identifier's network</li>
      </ul>
    </div>
    <div class="card">
      <h3 class="danger">\u{1F6A8} Alert Dashboard</h3>
      <ul>
        <li><b>Evidence snapshot</b>: text, time, channel, score, matched terms</li>
        <li><b>Risk levels</b>: HIGH (\u22650.75) / MEDIUM (\u22650.45)</li>
        <li><b>Disposition workflow</b>: confirmed / false-positive / escalated</li>
        <li><b>PDF dossier</b> export for each alert/channel</li>
      </ul>
    </div>
  </div>
</div>

<!-- Slide 6: Financial Ad Detection -->
<div class="slide" id="s6">
  <h2>Financial Crime Detection</h2>
  <p style="font-size:22px; margin-bottom:24px;">Specialised detection for <span class="accent">mule-account recruitment</span> and <span class="accent">banking instrument sales</span>.</p>
  <table>
    <tr><th>Category</th><th>Example Terms Detected</th><th>Risk Weight</th></tr>
    <tr><td><b>Account Sale</b></td><td>"bank account for sale", "account chahiye", "kyc verified account"</td><td style="color:#f87171;">0.90\u20130.98</td></tr>
    <tr><td><b>Account Rent</b></td><td>"account on rent", "rent account", "use karne do"</td><td style="color:#f87171;">0.95</td></tr>
    <tr><td><b>Card Sale</b></td><td>"atm card sale", "debit card sale", "credit card sale"</td><td style="color:#f87171;">0.98</td></tr>
    <tr><td><b>Sim Card Sale</b></td><td>"sim card for sale", "bulk sim", "registered sim"</td><td style="color:#fbbf24;">0.85\u20130.98</td></tr>
    <tr><td><b>NetBanking Kit</b></td><td>"netbanking kit", "login id password", "internet banking id"</td><td style="color:#f87171;">0.95</td></tr>
    <tr><td><b>Mule Recruitment</b></td><td>"mule account", "paisa transfer karo", "commission milegi"</td><td style="color:#f87171;">0.90\u20130.98</td></tr>
    <tr><td><b>Fake Documents</b></td><td>"fake aadhar", "fake pan", "novelty id", "scan copy"</td><td style="color:#fbbf24;">0.85\u20130.98</td></tr>
  </table>
  <div style="margin-top:20px; padding:16px; background:#1a1a2e; border-radius:8px; border-left:4px solid #fbbf24;">
    <p style="font-size:18px;"><b class="accent">Evidence provided per alert:</b> matched term, category, weight, lexicon source, risk level, extracted identifiers (phone/UPI/handle), channel name, timestamp, message hash.</p>
  </div>
</div>

<!-- Slide 7: Data Flow -->
<div class="slide" id="s7">
  <h2>Data Collection &amp; Processing Flow</h2>
  <div style="margin-top:20px;">
    <div class="arch-box" style="border-color:#60a5fa;">
      <b style="color:#60a5fa;">1. Data Collection</b><br>
      <span style="font-size:15px; color:#888;">Telegram MTProto (Telethon) \u00B7 CSV/JSON import for external datasets \u00B7 Public channels only \u00B7 No joining, no DMs</span>
    </div>
    <div class="arch-arrow">\u2193</div>
    <div class="arch-box" style="border-color:#fbbf24;">
      <b style="color:#fbbf24;">2. Normalisation &amp; Classification</b><br>
      <span style="font-size:15px; color:#888;">7-step text normaliser (NFC, zero-width removal, confusable map, lowercase) \u2192 Lexicon scorer (weighted OR) \u2192 optional ML blend</span>
    </div>
    <div class="arch-arrow">\u2193</div>
    <div class="arch-box" style="border-color:#4ade80;">
      <b style="color:#4ade80;">3. Identifier Extraction</b><br>
      <span style="font-size:15px; color:#888;">Regex-based: phone, UPI, handle, wallet, email, URL \u00B7 OCR for image-based ads (EasyOCR) \u00B7 Dedup by hash</span>
    </div>
    <div class="arch-arrow">\u2193</div>
    <div class="arch-box" style="border-color:#a78bfa;">
      <b style="color:#a78bfa;">4. Link Analysis &amp; Graph</b><br>
      <span style="font-size:15px; color:#888;">Entity co-occurrence edges \u00B7 Cross-channel identifier mapping \u00B7 MinHash near-duplicate detection \u00B7 NetworkX + Cytoscape.js</span>
    </div>
    <div class="arch-arrow">\u2193</div>
    <div class="arch-box" style="border-color:#f87171;">
      <b style="color:#f87171;">5. Alert Generation &amp; Evidence</b><br>
      <span style="font-size:15px; color:#888;">Risk-level assignment \u00B7 Evidence JSON (matched terms, score, categories) \u00B7 SQLite persistence \u00B7 PDF dossier export</span>
    </div>
  </div>
</div>

<!-- Slide 8: Tech Stack -->
<div class="slide" id="s8">
  <h2>Technology Stack</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr; gap:30px; margin-top:20px;">
    <div>
      <h3 style="color:#60a5fa;">Backend</h3>
      <table>
        <tr><td><b>Framework</b></td><td>FastAPI (async)</td></tr>
        <tr><td><b>ORM</b></td><td>SQLAlchemy 2.0 async</td></tr>
        <tr><td><b>Database</b></td><td>SQLite (PostgreSQL ready)</td></tr>
        <tr><td><b>Telegram API</b></td><td>Telethon (MTProto)</td></tr>
        <tr><td><b>NLP / ML</b></td><td>scikit-learn, joblib</td></tr>
        <tr><td><b>OCR</b></td><td>EasyOCR</td></tr>
        <tr><td><b>Graph</b></td><td>NetworkX</td></tr>
        <tr><td><b>Reports</b></td><td>ReportLab (PDF)</td></tr>
        <tr><td><b>Dedup</b></td><td>datasketch (MinHash LSH)</td></tr>
      </table>
    </div>
    <div>
      <h3 class="accent">Frontend</h3>
      <table>
        <tr><td><b>Framework</b></td><td>React 18 + Vite</td></tr>
        <tr><td><b>Styling</b></td><td>Tailwind CSS (dark theme)</td></tr>
        <tr><td><b>Graph Viz</b></td><td>Cytoscape.js</td></tr>
        <tr><td><b>Icons</b></td><td>lucide-react</td></tr>
        <tr><td><b>HTTP</b></td><td>Axios</td></tr>
        <tr><td><b>Routing</b></td><td>React Router</td></tr>
        <tr><td><b>Dates</b></td><td>date-fns</td></tr>
      </table>
      <h3 style="color:#4ade80; margin-top:20px;">Deployment</h3>
      <table>
        <tr><td><b>Container</b></td><td>Docker Compose</td></tr>
        <tr><td><b>Frontend serve</b></td><td>Nginx (production)</td></tr>
      </table>
    </div>
  </div>
</div>

<!-- Slide 9: Wireframe Preview -->
<div class="slide" id="s9">
  <h2>Application Wireframe</h2>
  <p style="font-size:18px; margin-bottom:20px;">The full interactive wireframe is provided as a separate HTML file. Key screens:</p>
  <div class="grid" style="grid-template-columns:1fr 1fr 1fr; gap:16px;">
    <div class="card" style="text-align:center;">
      <h3 style="color:#60a5fa;">\u{1F4CA} Dashboard</h3>
      <p>Live stats \u00B7 Risk overview \u00B7 Recent alerts feed \u00B7 Quick actions</p>
    </div>
    <div class="card" style="text-align:center;">
      <h3 class="danger">\u{1F6A8} Alerts</h3>
      <p>Evidence cards \u00B7 Risk badges \u00B7 Disposition controls \u00B7 Filter by risk/reviewed</p>
    </div>
    <div class="card" style="text-align:center;">
      <h3 class="accent">\u{1F50D} Scanner</h3>
      <p>Multi-seed search \u00B7 Channel results \u00B7 Score breakdown \u00B7 PDF export</p>
    </div>
    <div class="card" style="text-align:center;">
      <h3 style="color:#a78bfa;">\u{1F578}\u{FE0F} Entity Graph</h3>
      <p>Interactive network \u00B7 Identifier nodes \u00B7 Cross-channel links \u00B7 Ego graph</p>
    </div>
    <div class="card" style="text-align:center;">
      <h3 style="color:#4ade80;">\u{1F4CB} Channels</h3>
      <p>Watchlist \u00B7 Health status \u00B7 Poll tiers \u00B7 Intelligence dossier</p>
    </div>
    <div class="card" style="text-align:center;">
      <h3 style="color:#fbbf24;">\u{1F4E5} Import</h3>
      <p>CSV upload \u00B7 JSON import \u00B7 Bulk classification \u00B7 External datasets</p>
    </div>
  </div>
  <div style="margin-top:30px; padding:16px; background:#1a1a2e; border-radius:8px; text-align:center;">
    <p style="font-size:18px;">\u{1F4C4} Open <b style="color:#60a5fa;">wireframe.html</b> in your browser for the full interactive wireframe</p>
  </div>
</div>

<!-- Slide 10: Impact & Conclusion -->
<div class="slide" id="s10">
  <h2>Impact &amp; Conclusion</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr; gap:30px;">
    <div>
      <h3 style="color:#4ade80;">What We Deliver</h3>
      <ul>
        <li><b>Automated detection</b> of drug, arms, and financial crime ads</li>
        <li><b>Identifier collation</b> across channels \u2014 phone, UPI, wallet, handle</li>
        <li><b>Forensic evidence chain</b> with PDF dossiers for prosecution</li>
        <li><b>Scalable</b> to thousands of channels with priority scheduling</li>
        <li><b>Analyst-configurable</b> seeds and lexicons \u2014 no code changes needed</li>
        <li><b>Hindi/Hinglish</b> slang support for Indian context</li>
      </ul>
    </div>
    <div>
      <h3 class="accent">Why TeleMonitor Wins</h3>
      <ul>
        <li><b>Not just keywords</b> \u2014 context guard prevents false positives</li>
        <li><b>Not just alerts</b> \u2014 entity graph reveals coordinated networks</li>
        <li><b>Not just monitoring</b> \u2014 evidence preserved for legal action</li>
        <li><b>Public data only</b> \u2014 no ethical or legal privacy concerns</li>
        <li><b>End-to-end</b> \u2014 collection to prosecution-ready reports</li>
      </ul>
    </div>
  </div>
  <div style="margin-top:40px; text-align:center; padding:30px; background:#1a1a2e; border-radius:12px;">
    <h2 style="margin:0; color:#60a5fa;">TeleMonitor</h2>
    <p style="font-size:20px; margin-top:8px;">From scattered posts to prosecutable evidence.</p>
    <p style="font-size:16px; color:#555; margin-top:12px;">Thank you \u00B7 Questions welcome</p>
  </div>
</div>

<div class="slide-title-bar" id="titleBar">Slide 1 of 10</div>
<div class="slide-nav" id="slideNav">1 / 10</div>
<div class="arrow-hint">Use \u2190 \u2192 or click to navigate</div>

<script>
  let current = 1;
  const total = 10;
  function show(n) {
    document.querySelectorAll(".slide").forEach(s => s.classList.remove("active"));
    document.getElementById("s" + n).classList.add("active");
    document.getElementById("slideNav").textContent = n + " / " + total;
    document.getElementById("titleBar").textContent = "Slide " + n + " of " + total;
    current = n;
  }
  document.addEventListener("keydown", e => {
    if (e.key === "ArrowRight" || e.key === " ") { if (current < total) show(current + 1); }
    if (e.key === "ArrowLeft") { if (current > 1) show(current - 1); }
  });
  document.addEventListener("click", e => {
    if (e.clientX > window.innerWidth / 2) { if (current < total) show(current + 1); }
    else { if (current > 1) show(current - 1); }
  });
</script>
</body>
</html>"""

with open(os.path.join(OUT_DIR, "presentation.html"), "w", encoding="utf-8") as f:
    f.write(presentation_html)
print("presentation.html written")
