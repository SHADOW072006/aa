"""
TeleMonitor Solution Report — clean, readable, no overlapping text.
Uses ReportLab with careful spacing, proper table wrapping, and visual interest.
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether, Image
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deliverables", "TeleMonitor_Solution_Document.pdf")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

# ── Colors ──
NAVY = HexColor("#1a1a3e")
BLUE = HexColor("#2563eb")
LIGHT_BLUE = HexColor("#e8eef6")
RED = HexColor("#dc2626")
GREEN = HexColor("#059669")
YELLOW = HexColor("#d97706")
GRAY = HexColor("#6b7280")
DARK = HexColor("#1f2937")
LIGHT = HexColor("#f9fafb")
ROW_ALT = HexColor("#f3f4f6")
BORDER = HexColor("#d1d5db")

# ── Styles ──
ss = getSampleStyleSheet()

s_title = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=32, textColor=BLUE, leading=38, spaceAfter=4)
s_sub = ParagraphStyle("S", fontName="Helvetica", fontSize=14, textColor=GRAY, leading=18, spaceAfter=20)
s_h1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=22, textColor=BLUE, leading=26, spaceBefore=28, spaceAfter=6)
s_h2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=14, textColor=NAVY, leading=18, spaceBefore=14, spaceAfter=4)
s_body = ParagraphStyle("B", fontName="Helvetica", fontSize=11, textColor=DARK, leading=16, alignment=TA_JUSTIFY, spaceAfter=8)
s_bullet = ParagraphStyle("Bu", fontName="Helvetica", fontSize=11, textColor=DARK, leading=15, spaceAfter=3, leftIndent=20, bulletIndent=6)
s_small = ParagraphStyle("Sm", fontName="Helvetica", fontSize=9, textColor=GRAY, leading=12, alignment=TA_CENTER)
s_tag = ParagraphStyle("Tag", fontName="Helvetica-Bold", fontSize=10, textColor=white, alignment=TA_CENTER, leading=14)
s_cover_desc = ParagraphStyle("CD", fontName="Helvetica", fontSize=12, textColor=GRAY, leading=18, alignment=TA_LEFT, spaceAfter=6)
s_quote = ParagraphStyle("Q", fontName="Helvetica-Oblique", fontSize=12, textColor=RED, alignment=TA_CENTER, leading=18, spaceBefore=10, spaceAfter=14)

# ── Table cell paragraph styles ──
s_th = ParagraphStyle("TH", fontName="Helvetica-Bold", fontSize=9.5, textColor=white, leading=12)
s_td = ParagraphStyle("TD", fontName="Helvetica", fontSize=9.5, textColor=DARK, leading=13)
s_td_bold = ParagraphStyle("TDB", fontName="Helvetica-Bold", fontSize=9.5, textColor=DARK, leading=13)

def make_table(headers, rows, col_widths):
    """Build a clean table with wrapped text in every cell."""
    data = []
    # Header row
    data.append([Paragraph(h, s_th) for h in headers])
    # Body rows
    for row in rows:
        data.append([Paragraph(str(c), s_td) for c in row])

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        # Body
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]
    t.setStyle(TableStyle(style))
    return t

def callout(title, text, color=BLUE):
    """A colored box with a title and text — visual interest."""
    inner = [
        [Paragraph(title, ParagraphStyle("CT", fontName="Helvetica-Bold", fontSize=11, textColor=color, leading=14))],
        [Paragraph(text, ParagraphStyle("CB", fontName="Helvetica", fontSize=10, textColor=DARK, leading=14, spaceBefore=4))],
    ]
    page_w = A4[0] - 56 * mm
    t = Table(inner, colWidths=[page_w])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t

def bullet_list(items):
    """Render a list of bullet points."""
    flowables = []
    for item in items:
        flowables.append(Paragraph(item, s_bullet, bulletText="\u25B8"))
    return flowables

# ── Page template with footer ──
def add_footer(canvas_obj, doc_obj):
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(GRAY)
    page_num = canvas_obj.getPageNumber()
    canvas_obj.drawCentredString(A4[0] / 2, 12 * mm, f"TeleMonitor Solution Document  -  Page {page_num}")
    # Top accent line
    canvas_obj.setStrokeColor(BLUE)
    canvas_obj.setLineWidth(2)
    canvas_obj.line(28 * mm, A4[1] - 18 * mm, A4[0] - 28 * mm, A4[1] - 18 * mm)
    canvas_obj.restoreState()

# ── Build ──
doc = SimpleDocTemplate(
    OUT,
    pagesize=A4,
    leftMargin=28 * mm,
    rightMargin=28 * mm,
    topMargin=24 * mm,
    bottomMargin=20 * mm,
    title="TeleMonitor Solution Document",
    author="TeleMonitor Team",
)
W = A4[0] - 56 * mm  # usable width

story = []

# ═══════════════════════════════════════════════════════════════
# COVER PAGE
# ═══════════════════════════════════════════════════════════════
story.append(Spacer(1, 50 * mm))
story.append(Paragraph("TeleMonitor", s_title))
story.append(Paragraph("OSNT Intelligence Platform for Illegal Trade Detection", s_sub))
story.append(HRFlowable(width="100%", thickness=3, color=BLUE))
story.append(Spacer(1, 15 * mm))

story.append(Paragraph("Solution Document", ParagraphStyle("DocT", fontName="Helvetica-Bold", fontSize=20, textColor=NAVY, leading=24)))
story.append(Paragraph("How We Solve the Problem", ParagraphStyle("DocS", fontName="Helvetica", fontSize=14, textColor=GRAY, leading=18, spaceAfter=16)))
story.append(Spacer(1, 6 * mm))

story.append(Paragraph(
    "This document explains how TeleMonitor addresses every requirement in the problem statement: "
    "collecting posts from public Telegram channels, detecting illegal sales using slang-aware NLP, "
    "extracting actionable identifiers, linking sellers across channels in an entity graph, and "
    "presenting everything in an alert dashboard with forensic evidence for prosecution.",
    s_cover_desc
))
story.append(Spacer(1, 12 * mm))

# Feature tags
tags = [
    ["Drug Sale Detection", "Arms Trafficking", "Mule Recruitment"],
    ["Financial Crime", "Identifier Extraction", "Entity Graph"],
    ["OCR & Hindi/Hinglish", "Forensic PDF Reports", "Link Analysis"],
]
tag_data = []
for row in tags:
    tag_data.append([Paragraph(t, s_tag) for t in row])
tag_t = Table(tag_data, colWidths=[W / 3] * 3)
tag_t.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), BLUE),
    ("TEXTCOLOR", (0, 0), (-1, -1), white),
    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 8),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ("BOX", (0, 0), (-1, -1), 0, white),
    ("INNERGRID", (0, 0), (-1, -1), 2, white),
]))
story.append(tag_t)
story.append(Spacer(1, 20 * mm))
story.append(Paragraph("Round 1 Submission  -  Hackathon", s_small))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 1. PROBLEM STATEMENT
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("1. Problem Statement &amp; Our Approach", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "Drug peddlers and mule-account recruiters operate through <b>public Telegram channels</b> and social media, "
    "using coded slang, regional language (Hindi/Hinglish), and emojis to advertise illegal products. "
    "Manual monitoring by police is slow, inconsistent, and cannot scale. Seller identifiers posted in these ads "
    "are rarely collated across channels, making it impossible to build a complete picture of a seller's network.",
    s_body
))

story.append(Spacer(1, 4))
story.append(callout(
    "The Challenge",
    "Build a monitoring system that collects posts from public channels, detects illegal sales, "
    "extracts actionable identifiers, links them across channels, and presents evidence in an alert dashboard.",
    RED
))
story.append(Spacer(1, 10))

story.append(Paragraph("1.1 How We Address Each Requirement", s_h2))
story.append(Spacer(1, 4))

req_rows = [
    ["1", "Data collection from public Telegram channels + CSV/JSON import",
     "Telethon MTProto collector for live Telegram + CSV/JSON import for external datasets"],
    ["2", "Illegal-sale classifier with slang and emoji lexicon + ML",
     "5 lexicons (200+ terms), weighted scoring, context guard, optional TF-IDF + LogisticRegression"],
    ["3", "Financial-ad detector for bank accounts, ATM cards, SIM cards",
     "Dedicated financial crime lexicon: account sale, card sale, SIM sale, mule recruitment, netbanking kit"],
    ["4", "Identifier extraction (phone, UPI, handle, wallet, location)",
     "Regex extraction: phone (E.164), UPI IDs, BTC/ETH/USDT wallets, Telegram handles, email, URLs"],
    ["5", "Link analysis: repeated ads + same identifier across channels",
     "Entity co-occurrence graph (NetworkX), MinHash near-duplicate detection, cross-channel mapping"],
    ["6", "Alert dashboard with evidence snapshots",
     "Real-time dashboard: text, timestamp, channel, score, matched terms, risk level, PDF dossier export"],
    ["7", "OCR of images and posters (good to have)",
     "EasyOCR integration for image-based ads, OCR gating by poll tier, outcome tracking"],
    ["8", "Hindi/Hinglish slang support (good to have)",
     "Hindi terms in lexicons (ganja, charas, kyc chahiye), normaliser handles Devanagari script"],
    ["9", "Automatic evidence report / PDF (good to have)",
     "ReportLab-based PDF dossier generator per alert, channel, and scan job"],
]
story.append(make_table(["#", "Requirement", "How TeleMonitor Solves It"], req_rows, [10*mm, 65*mm, 81*mm]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 2. SOLUTION ARCHITECTURE
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("2. Solution Architecture", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "TeleMonitor is a full-stack application. The backend (FastAPI + SQLAlchemy) handles Telegram collection, "
    "classification, identifier extraction, entity graphing, and PDF report generation. The frontend (React + Vite + "
    "Tailwind) provides a real-time alert dashboard, scanner, entity graph visualisation, and channel intelligence.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("2.1 Processing Pipeline", s_h2))
story.append(Spacer(1, 4))

pipe_rows = [
    ["1. Collect", "Telegram Collector", "Telethon (MTProto)", "Collect messages from public channels; no joining, no DMs"],
    ["2. Normalise", "Text Normaliser", "Python (unicodedata)", "7-step: NFC, zero-width removal, confusable map, lowercase, whitespace"],
    ["3. Classify", "Classifier", "scikit-learn + lexicon", "Weighted lexicon scoring + optional ML blend; context guard for ambiguous terms"],
    ["4. Extract", "Identifier Extractor", "Python (regex)", "Extract phone, UPI, crypto wallet, handle, email, URL from classified text"],
    ["5. Link", "Entity Graph", "NetworkX + datasketch", "Co-occurrence edges; MinHash LSH for near-duplicate text; cross-channel mapping"],
    ["6. Alert", "Alert Engine", "FastAPI + SQLAlchemy", "Risk-level assignment, evidence JSON, SQLite persistence, disposition workflow"],
    ["7. Report", "PDF Generator", "ReportLab", "Forensic evidence dossiers per alert, channel, and scan job"],
]
story.append(make_table(["Stage", "Component", "Technology", "Purpose"], pipe_rows, [18*mm, 32*mm, 35*mm, 71*mm]))
story.append(Spacer(1, 12))

story.append(Paragraph("2.2 Frontend Screens", s_h2))
story.append(Spacer(1, 4))

fe_rows = [
    ["Dashboard", "React + Tailwind", "Live stats, risk overview, recent alerts feed, quick actions"],
    ["Alerts Page", "React + Tailwind", "Evidence cards with risk badges, disposition controls, filters"],
    ["Scanner", "React + Tailwind", "Multi-seed search, channel scoring, Review/Auto-Add mode, PDF export"],
    ["Entity Graph", "Cytoscape.js", "Interactive network of identifier co-occurrences across channels"],
    ["Channel Intel", "React + Cytoscape", "Deep dossier: identifiers, connected nodes, network graph, PDF export"],
    ["Seed Manager", "React + Tailwind", "Analyst-configurable search terms with auto-generated query variants"],
    ["Import", "React + upload", "CSV/JSON upload for bulk classification of external datasets"],
]
story.append(make_table(["Screen", "Technology", "Function"], fe_rows, [35*mm, 35*mm, 86*mm]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 3. CLASSIFIER DESIGN
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("3. Illegal-Sale Classifier", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "The classifier is the brain of the system. It uses a <b>two-stage approach</b>: a lexicon scorer that matches "
    "slang terms and emojis with weighted scores, optionally blended with a machine learning model. "
    "This means even without training data, the system can detect illegal trade ads from day one.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("3.1 Five Lexicons, 200+ Terms", s_h2))
story.append(Spacer(1, 4))

lex_rows = [
    ["Drug Slang", "~85", "heroin, cocaine, cannabis, mdma, opioid, drug_sale", "brown sugar (0.90), ganja (0.80), discreet delivery (0.90)"],
    ["Financial Crime", "~60", "account_sale, card_sale, sim_sale, mule_recruitment, fake_docs", "bank account for sale (0.98), atm card sale (0.98), mule account (0.98)"],
    ["Arms", "~20", "arms_sale, military_arms", "desi katta (0.95), pistol sale (0.95), ak-47 (0.98)"],
    ["Scams", "~100", "colour_trading_scam, task_scam, investment_fraud, gambling", "colour prediction (0.98), task karo paisa pao (0.98)"],
    ["Extended Crime", "~80", "national_breach, ransomware, human_trafficking, arms_explosives", "aadhaar database leak (0.99), kidney donor buyer (0.99)"],
]
story.append(make_table(
    ["Lexicon", "Terms", "Categories", "Example Terms"],
    lex_rows,
    [28*mm, 14*mm, 55*mm, 59*mm]
))
story.append(Spacer(1, 10))

story.append(callout(
    "Context Guard — Preventing False Positives",
    "Ambiguous words like \"ice\", \"brown\", \"white\", \"crack\" only count if a high-weight term "
    "(>= 0.80) from the same lexicon is also present. So \"ice\" in \"price\" or \"brown\" in a name "
    "will NOT trigger a drug alert. Word-boundary matching ensures \"ice\" does not match inside \"price\".",
    GREEN
))
story.append(Spacer(1, 10))

story.append(Paragraph("3.2 Risk Levels", s_h2))
story.append(Spacer(1, 4))

risk_rows = [
    [">= 0.75", "HIGH", "Stored as alert, shown on dashboard, eligible for watchlist promotion (Auto mode)"],
    [">= 0.45", "MEDIUM", "Stored as alert, shown on dashboard, analyst review recommended"],
    ["< 0.45", "LOW", "Classified but not flagged as alert"],
]
story.append(make_table(["Score", "Risk Level", "What Happens"], risk_rows, [22*mm, 25*mm, 109*mm]))
story.append(Spacer(1, 10))

story.append(Paragraph("3.3 Channel-Level Scoring (prevents misleading labels)", s_h2))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "A channel is not labelled HIGH just because one drug term appeared. The risk level requires "
    "<b>both</b> a category match <b>and</b> a minimum average score across scanned messages. "
    "This prevents the confusing \"HIGH risk at 20% score\" problem.",
    s_body
))

chan_rows = [
    ["Critical category + avg >= 0.40", "HIGH", "CRITICAL"],
    ["High category + avg >= 0.55 + 2+ HIGH msgs", "HIGH", "HIGH"],
    ["High category + avg >= 0.40 + some flagged", "MEDIUM", "HIGH"],
    ["Petty categories only (scam, gambling, task)", "LOW", "PETTY"],
    ["avg >= 0.55 + 2+ HIGH msgs (no high category)", "HIGH", "MEDIUM"],
    ["avg >= 0.40 + some flagged", "MEDIUM", "MEDIUM"],
    ["Otherwise", "LOW", "LOW"],
]
story.append(make_table(["Condition", "Risk", "Severity"], chan_rows, [80*mm, 25*mm, 51*mm]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 4. FINANCIAL CRIME
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("4. Financial Crime Detection", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "A specialised financial crime lexicon detects posts offering to buy, sell, or rent <b>bank accounts</b>, "
    "<b>ATM/debit cards</b>, <b>SIM cards</b>, <b>netbanking kits</b>, and <b>mule account recruitment</b>. "
    "Each detected term produces evidence: the matched term, its category, weight, and lexicon source.",
    s_body
))
story.append(Spacer(1, 8))

fin_rows = [
    ["Account Sale", "\"bank account for sale\", \"account chahiye\", \"kyc verified account\"", "0.90 - 0.98"],
    ["Account Rent", "\"account on rent\", \"rent account\", \"use karne do\"", "0.95"],
    ["ATM / Card Sale", "\"atm card sale\", \"debit card sale\", \"credit card sale\"", "0.98"],
    ["SIM Card Sale", "\"sim card for sale\", \"bulk sim\", \"registered sim\"", "0.85 - 0.98"],
    ["NetBanking Kit", "\"netbanking kit\", \"login id password\", \"internet banking id\"", "0.95"],
    ["Mule Recruitment", "\"mule account\", \"paisa transfer karo\", \"commission milegi\"", "0.90 - 0.98"],
    ["Fake Documents", "\"fake aadhar\", \"fake pan\", \"novelty id\", \"scan copy\"", "0.85 - 0.98"],
]
story.append(make_table(["Category", "Example Terms Detected", "Risk Weight"], fin_rows, [38*mm, 90*mm, 28*mm]))
story.append(Spacer(1, 10))

story.append(callout(
    "Evidence Per Alert",
    "Every financial crime alert records: matched term, category, weight, lexicon source, risk level, "
    "extracted identifiers (phone/UPI/handle), channel name, timestamp, and message hash. "
    "This is a complete evidence chain for prosecution.",
    YELLOW
))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 5. IDENTIFIER EXTRACTION
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("5. Identifier Extraction", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "Once a post is classified as HIGH or MEDIUM, the system extracts <b>actionable identifiers</b> — "
    "the phone numbers, payment IDs, and handles that let investigators trace the seller.",
    s_body
))
story.append(Spacer(1, 8))

id_rows = [
    ["Phone Number", "E.164 or local Indian (+91XXXXXXXXXX)", "+919876543210", "Contact seller, trace across channels"],
    ["UPI ID", "name@bank pattern", "dealer@okaxis", "Payment trail, account identification"],
    ["Crypto Wallet", "BTC (bc1...), ETH (0x...), USDT", "bc1qxy2kgdygjrsqtzq...", "Money laundering trail"],
    ["Telegram Handle", "@username (4-30 chars)", "@drug_seller_007", "Cross-channel seller mapping"],
    ["Telegram Link", "t.me/channelname", "t.me/darknet_market", "Pivot to new channel discovery"],
    ["Email", "Standard email pattern", "seller@mail.com", "Contact method tracking"],
    ["URL", "http(s)://domain", "https://darkshop.example.com", "External platform linking"],
]
story.append(make_table(["Identifier", "Pattern", "Example", "Investigative Use"], id_rows, [28*mm, 45*mm, 40*mm, 43*mm]))
story.append(Spacer(1, 12))

story.append(Paragraph("5.1 OCR for Image-Based Ads", s_h2))
story.append(Paragraph(
    "Many illegal trade posts use <b>images or posters</b> with embedded text instead of plain text messages. "
    "TeleMonitor integrates <b>EasyOCR</b> to extract text from downloaded images. OCR is gated by the channel's "
    "poll tier: it only runs for HIGH and MEDIUM tier channels to conserve resources. The outcome is tracked "
    "(not_applicable, skipped, success, failed) for each message.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("5.2 Hindi / Hinglish Slang Support", s_h2))
story.append(Paragraph(
    "The lexicons include Hindi and Hinglish slang commonly used in Indian illegal trade channels: "
    "<b>\"ganja\"</b> (cannabis), <b>\"charas\"</b> (hashish), <b>\"kyc chahiye\"</b> (need KYC), "
    "<b>\"account dena hai\"</b> (want to sell account), <b>\"paisa transfer karo\"</b> (transfer money), "
    "<b>\"commission milegi\"</b> (commission will be given). "
    "The text normaliser also handles Devanagari script via transliteration.",
    s_body
))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 6. ENTITY GRAPH
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("6. Entity Graph &amp; Link Analysis", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "The entity graph is the key investigative tool. It connects identifiers that appear together in the same "
    "message (co-occurrence edges) and maps the same identifier across different channels. This reveals "
    "<b>coordinated networks</b> that manual monitoring simply cannot detect.",
    s_body
))
story.append(Spacer(1, 10))

story.append(Paragraph("6.1 How It Works", s_h2))
story.append(Spacer(1, 4))

graph_items = [
    "<b>Co-occurrence edges:</b> When a phone number and a UPI ID appear in the same message, they are linked. "
    "The edge weight increases each time the pair co-occurs, strengthening the connection.",
    "<b>Cross-channel mapping:</b> If the same phone number appears in 5 different Telegram channels, "
    "the graph shows all 5 channels connected to that phone — revealing a multi-channel seller operation.",
    "<b>Near-duplicate detection:</b> MinHash LSH (datasketch) detects the same advertisement posted across "
    "multiple channels (copy-paste campaigns). Image pHash catches duplicate images.",
    "<b>Interactive visualisation:</b> Cytoscape.js renders the graph interactively. Analysts can explore "
    "the full network, search for a specific identifier (ego graph), and filter by identifier type.",
]
for item in graph_items:
    story.append(Paragraph(item, s_bullet, bulletText="\u25B8"))
story.append(Spacer(1, 10))

story.append(callout(
    "Example Investigation",
    "A phone number +91XXXXXXXXXX appears in @darknet_pharma_deals, @bank_accounts_sale, and "
    "@weapons_store_tg. The entity graph immediately shows all three channels connected through this "
    "single phone number — revealing a seller who deals in drugs, financial crime, AND arms.",
    PURPLE if False else BLUE
))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 7. EVIDENCE & ALERTS
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("7. Evidence Preservation &amp; Alerts", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph(
    "Every flagged message is preserved as a <b>forensic evidence record</b>. The system uses a two-level "
    "model to ensure evidence is never lost during re-scans.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("7.1 Two-Level Evidence Model", s_h2))
story.append(Spacer(1, 4))

ev_rows = [
    ["Canonical Message", "evidence_messages", "One row per real Telegram message. Never deleted or overwritten. Stores raw text, OCR text, identifiers, media, and disposition.", "(channel, message_id)"],
    ["Classification Observation", "evidence_observations", "One row per classification event. Always inserts new — never updates. Stores scan job, variant, score, risk level, matched terms.", "(message_id, classified_at)"],
]
story.append(make_table(["Level", "Table", "Purpose", "Unique Key"], ev_rows, [30*mm, 38*mm, 64*mm, 24*mm]))
story.append(Spacer(1, 10))

story.append(Paragraph(
    "This means re-scanning a message creates a new observation without losing the original or any prior "
    "classification. The analyst's disposition on the canonical message <b>survives re-scans</b>.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("7.2 What the Analyst Sees", s_h2))
story.append(Spacer(1, 4))

alert_items = [
    "<b>Full message text</b> with timestamp and channel name",
    "<b>Classifier score</b> and risk level (HIGH / MEDIUM)",
    "<b>Matched terms</b> with categories and weights — so the analyst knows exactly what triggered the alert",
    "<b>Extracted identifiers</b> — phone numbers, UPI IDs, handles, wallets found in the text",
    "<b>Disposition controls</b> — confirmed_threat, false_positive, needs_review, escalated (with audit trail)",
    "<b>PDF dossier export</b> — prosecution-ready document with full evidence and network analysis",
]
for item in alert_items:
    story.append(Paragraph(item, s_bullet, bulletText="\u25B8"))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 8. DATA COLLECTION & SAFETY
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("8. Data Collection &amp; Safety", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(callout(
    "Public Data Only",
    "TeleMonitor accesses ONLY public Telegram channels with public usernames. "
    "It does NOT join private groups, access DMs, use fake identities, interact with sellers, "
    "or bypass Telegram's access controls. All data is from publicly accessible content.",
    GREEN
))
story.append(Spacer(1, 10))

story.append(Paragraph("8.1 Collection Methods", s_h2))
story.append(Spacer(1, 4))

coll_rows = [
    ["Telegram MTProto", "Live public channels", "Messages from channels in watchlist", "Continuous monitoring"],
    ["Telegram Search", "Telegram global search", "Public channels matching seed terms", "Channel discovery / scanning"],
    ["CSV Import", "External datasets", "Posts from other platforms (Instagram, etc.)", "Offline classification"],
    ["JSON Import", "External datasets", "Structured post data", "Bulk import and classification"],
]
story.append(make_table(["Method", "Source", "Scope", "Use Case"], coll_rows, [32*mm, 38*mm, 50*mm, 36*mm]))
story.append(Spacer(1, 10))

story.append(Paragraph("8.2 Priority Polling Scheduler", s_h2))
story.append(Paragraph(
    "The collector uses a priority-based scheduler: HIGH tier channels polled every 30s, MEDIUM every 60s, "
    "LOW every 300s. Up to 3 channels polled concurrently. FloodWait errors defer with exponential backoff. "
    "After 3 consecutive errors, the channel is marked error_state. This ensures the watchlist is monitored "
    "at scale without overwhelming the Telegram API.",
    s_body
))
story.append(Spacer(1, 8))

story.append(Paragraph("8.3 Analyst Review Workflow", s_h2))
story.append(Paragraph(
    "All detections are <b>leads requiring analyst review</b>, not proof of criminal activity. "
    "The default scan mode is <b>Review Only</b>: results appear on the dashboard without auto-adding "
    "channels to the watchlist. Analysts review evidence, set dispositions, and manually promote channels. "
    "The <b>Auto-Add</b> mode is opt-in and only promotes channels with 3+ HIGH-scored messages.",
    s_body
))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 9. TECHNOLOGY STACK
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("9. Technology Stack", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

tech_rows = [
    ["Backend Framework", "FastAPI", "Async, auto-docs (Swagger), high performance"],
    ["ORM", "SQLAlchemy 2.0", "Async sessions, supports SQLite and PostgreSQL"],
    ["Database", "SQLite (aiosqlite)", "Portable, zero-config; PostgreSQL-ready for production"],
    ["Telegram API", "Telethon", "MTProto client, public channel access only"],
    ["NLP / ML", "scikit-learn + joblib", "TF-IDF + LogisticRegression, optional blend with lexicon"],
    ["OCR", "EasyOCR", "Image text extraction, gated by poll tier"],
    ["Graph Analysis", "NetworkX + datasketch", "Co-occurrence graph, MinHash LSH dedup"],
    ["Graph Visualisation", "Cytoscape.js", "Interactive network rendering in browser"],
    ["PDF Reports", "ReportLab", "Forensic evidence dossiers, channel intelligence reports"],
    ["Frontend", "React 18 + Vite", "Fast dev server, production build optimisation"],
    ["CSS Framework", "Tailwind CSS", "Dark theme, utility-first, responsive"],
    ["HTTP Client", "Axios", "API calls to backend"],
    ["Deployment", "Docker Compose", "Backend + Frontend containers, Nginx for frontend"],
]
story.append(make_table(["Layer", "Technology", "Purpose"], tech_rows, [38*mm, 38*mm, 80*mm]))
story.append(PageBreak())

# ═══════════════════════════════════════════════════════════════
# 10. IMPACT & CONCLUSION
# ═══════════════════════════════════════════════════════════════
story.append(Paragraph("10. Impact &amp; Conclusion", s_h1))
story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
story.append(Spacer(1, 6))

story.append(Paragraph("10.1 What TeleMonitor Delivers", s_h2))
story.append(Spacer(1, 4))

deliverables = [
    "<b>Automated detection</b> of drug, arms, financial crime, and fake document advertisements",
    "<b>Identifier collation</b> across channels: phone, UPI, wallet, handle linked in a graph",
    "<b>Forensic evidence chain</b>: every alert preserves raw text, timestamp, score, matched terms",
    "<b>PDF dossier export</b> for prosecution: channel intelligence with full evidence and network",
    "<b>Scalable monitoring</b>: priority scheduler handles thousands of channels concurrently",
    "<b>Analyst-configurable</b>: seeds, lexicons, and scan modes configurable without code changes",
    "<b>Hindi/Hinglish support</b>: lexicons include regional slang for the Indian threat landscape",
    "<b>OCR for image ads</b>: text extracted from poster images that bypass text-based filters",
]
for item in deliverables:
    story.append(Paragraph(item, s_bullet, bulletText="\u25B8"))

story.append(Spacer(1, 14))
story.append(Paragraph("10.2 Why TeleMonitor Stands Out", s_h2))
story.append(Spacer(1, 4))

differentiators = [
    "<b>Not just keywords</b> — context guard prevents false positives from ambiguous terms",
    "<b>Not just alerts</b> — entity graph reveals coordinated seller networks across channels",
    "<b>Not just monitoring</b> — forensic evidence preserved with full audit trail for legal action",
    "<b>Public data only</b> — no ethical or legal privacy concerns; no private group access",
    "<b>End-to-end pipeline</b> — from Telegram collection to prosecution-ready PDF reports",
]
for item in differentiators:
    story.append(Paragraph(item, s_bullet, bulletText="\u25B8"))

story.append(Spacer(1, 24))
story.append(HRFlowable(width="100%", thickness=2, color=BLUE))
story.append(Spacer(1, 12))
story.append(Paragraph("TeleMonitor", ParagraphStyle("EndT", fontName="Helvetica-Bold", fontSize=24, textColor=BLUE, alignment=TA_CENTER, leading=28)))
story.append(Paragraph("From scattered posts to prosecutable evidence.", ParagraphStyle("EndS", fontName="Helvetica-Oblique", fontSize=14, textColor=GRAY, alignment=TA_CENTER, leading=18, spaceBefore=4)))

# ── Build PDF ──
doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
print(f"PDF generated: {OUT}")
print(f"Size: {os.path.getsize(OUT):,} bytes")
