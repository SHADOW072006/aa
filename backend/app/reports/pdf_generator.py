"""
TeleMonitor PDF Intelligence Report Generator.
Uses ReportLab to produce forensic dossiers for channels, scans, and syndicate networks.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that adds page numbers and confidential footer to every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Header rule & title
        self.setStrokeColor(colors.HexColor("#334155"))
        self.setLineWidth(0.5)
        self.line(40, 805, 555, 805)
        self.drawString(40, 812, "TELEMONITOR — PUBLIC-SOURCE OSINT | AUTOMATED ASSESSMENT")
        self.drawRightString(555, 812, "INVESTIGATIVE LEAD — NOT PROOF OF WRONGDOING")

        # Footer rule & page number
        self.line(40, 45, 555, 45)
        self.setFont("Helvetica", 8)
        self.drawString(40, 32, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} | Public-source lead (not proof)")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(555, 32, page_str)
        self.restoreState()


def _get_styles():
    base = getSampleStyleSheet()

    styles = {
        "DocTitle": ParagraphStyle(
            "DocTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        ),
        "DocSubtitle": ParagraphStyle(
            "DocSubtitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#dc2626"),
            spaceAfter=12,
        ),
        "Heading2": ParagraphStyle(
            "Heading2",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "Heading3": ParagraphStyle(
            "Heading3",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#334155"),
            spaceBefore=6,
            spaceAfter=3,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#334155"),
        ),
        "BodyBold": ParagraphStyle(
            "BodyBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#0f172a"),
        ),
        "MetaLabel": ParagraphStyle(
            "MetaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
        ),
        "MetaValue": ParagraphStyle(
            "MetaValue",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#0f172a"),
        ),
        "TableHeader": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        ),
        "BadgeHigh": ParagraphStyle(
            "BadgeHigh",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#991b1b"),
        ),
        "BadgeMedium": ParagraphStyle(
            "BadgeMedium",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#b45309"),
        ),
        "BadgeLow": ParagraphStyle(
            "BadgeLow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#166534"),
        ),
        "MsgTranscript": ParagraphStyle(
            "MsgTranscript",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#1e293b"),
        ),
    }
    return styles


def generate_scan_job_pdf(job: Dict[str, Any], results: List[Dict[str, Any]]) -> bytes:
    """Generates an executive threat intelligence report for a completed or running scan job."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    # Title & Header
    story.append(Paragraph("THREAT SCAN INTELLIGENCE REPORT", styles["DocTitle"]))
    story.append(Paragraph(f"JOB ID #{job.get('id')} — TELEGRAM NETWORK RECONNAISSANCE", styles["DocSubtitle"]))
    story.append(Spacer(1, 4))

    # Executive Summary Card
    started = job.get("started_at") or job.get("created_at") or "N/A"
    finished = job.get("finished_at") or "Ongoing / In-progress"
    total_found = job.get("total_channels_found", 0)
    total_scanned = job.get("total_channels_scanned", len(results))
    total_flagged = job.get("total_flagged", 0)
    high_count = sum(1 for r in results if r.get("risk_level") == "HIGH")
    medium_count = sum(1 for r in results if r.get("risk_level") == "MEDIUM")

    meta_table_data = [
        [
            Paragraph("Scan Job ID:", styles["MetaLabel"]),
            Paragraph(str(job.get("id")), styles["MetaValue"]),
            Paragraph("Status:", styles["MetaLabel"]),
            Paragraph(str(job.get("status", "")).upper(), styles["MetaValue"]),
        ],
        [
            Paragraph("Scan Started:", styles["MetaLabel"]),
            Paragraph(started[:19].replace("T", " "), styles["MetaValue"]),
            Paragraph("Scan Concluded:", styles["MetaLabel"]),
            Paragraph(finished[:19].replace("T", " "), styles["MetaValue"]),
        ],
        [
            Paragraph("Channels Discovered:", styles["MetaLabel"]),
            Paragraph(str(total_found), styles["MetaValue"]),
            Paragraph("Channels Scanned:", styles["MetaLabel"]),
            Paragraph(str(total_scanned), styles["MetaValue"]),
        ],
        [
            Paragraph("Flagged Messages:", styles["MetaLabel"]),
            Paragraph(f"<font color='#dc2626'><b>{total_flagged}</b></font>", styles["MetaValue"]),
            Paragraph("High Risk Channels:", styles["MetaLabel"]),
            Paragraph(f"<font color='#dc2626'><b>{high_count} HIGH</b></font> | <font color='#d97706'><b>{medium_count} MED</b></font>", styles["MetaValue"]),
        ],
    ]

    t_meta = Table(meta_table_data, colWidths=[110, 140, 110, 155])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_meta)
    story.append(Spacer(1, 10))

    # Seeds Used
    seeds = job.get("seed_terms", [])
    if seeds:
        seed_str = ", ".join(seeds[:18]) + ("..." if len(seeds) > 18 else "")
        story.append(Paragraph(f"<b>Crime Seeds Queried ({len(seeds)}):</b> {seed_str}", styles["Body"]))
        story.append(Spacer(1, 10))

    # Channel Findings Table
    story.append(Paragraph("DISCOVERED TARGET CHANNELS", styles["Heading2"]))

    # Table Header
    headers = [
        Paragraph("Risk", styles["TableHeader"]),
        Paragraph("Channel / Username", styles["TableHeader"]),
        Paragraph("Members", styles["TableHeader"]),
        Paragraph("Msgs", styles["TableHeader"]),
        Paragraph("Flags", styles["TableHeader"]),
        Paragraph("Threat Score", styles["TableHeader"]),
        Paragraph("Top Crime Categories", styles["TableHeader"]),
    ]
    table_rows = [headers]

    # Sort results: HIGH first, then MEDIUM, then LOW
    sorted_res = sorted(results, key=lambda x: (0 if x.get("risk_level") == "HIGH" else (1 if x.get("risk_level") == "MEDIUM" else 2), -x.get("avg_score", 0)))

    for r in sorted_res[:60]:
        risk = r.get("risk_level", "LOW")
        risk_style = styles["BadgeHigh"] if risk == "HIGH" else (styles["BadgeMedium"] if risk == "MEDIUM" else styles["BadgeLow"])

        ch_name = f"@{r.get('channel_username', '')}"
        if r.get("channel_title"):
            ch_name += f"<br/><font size=6.5 color='#64748b'>{r.get('channel_title')[:30]}</font>"

        cats = r.get("top_categories", [])
        cats_str = ", ".join([c.replace("_", " ") for c in cats[:3]]) if cats else "—"

        table_rows.append([
            Paragraph(risk, risk_style),
            Paragraph(ch_name, styles["BodyBold"]),
            Paragraph(f"{r.get('member_count', 0):,}" if r.get("member_count") else "—", styles["Body"]),
            Paragraph(str(r.get("messages_scanned", 0)), styles["Body"]),
            Paragraph(f"<b>{r.get('flagged_count', 0)}</b>", styles["Body"]),
            Paragraph(f"{r.get('avg_score', 0)*100:.0f}%", styles["BodyBold"]),
            Paragraph(cats_str, styles["Body"]),
        ])

    ch_table = Table(table_rows, colWidths=[45, 140, 50, 40, 40, 60, 140])
    ch_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ])
    )
    story.append(ch_table)
    story.append(Spacer(1, 14))

    # Top High-Risk Target Dossier Section
    high_risk_channels = [r for r in sorted_res if r.get("risk_level") == "HIGH"][:5]
    if high_risk_channels:
        story.append(Paragraph("HIGH PRIORITY THREAT DOSSIERS (TOP TARGETS)", styles["Heading2"]))

        for ch in high_risk_channels:
            box_content = []
            box_content.append(Paragraph(f"<b>TARGET: @{ch.get('channel_username')}</b> — {ch.get('channel_title') or 'Untitled Channel'}", styles["DocSubtitle"]))

            # Identifiers extracted
            idents = ch.get("top_identifiers", [])
            ident_summary = []
            for item in idents[:8]:
                t = item.get("type", "").upper()
                v = item.get("value", "")
                ident_summary.append(f"<b>[{t}]</b> {v}")
            ident_text = " | ".join(ident_summary) if ident_summary else "No financial/contact identifiers parsed yet."
            box_content.append(Paragraph(f"<b>Extracted Identifiers:</b> {ident_text}", styles["Body"]))
            box_content.append(Spacer(1, 4))

            # Sample messages
            msgs = ch.get("sample_messages", [])
            if msgs:
                box_content.append(Paragraph("<b>Flagged Intercepts / Evidence:</b>", styles["Heading3"]))
                for m in msgs[:2]:
                    txt = m.get("text", "").replace("\n", " ")[:250]
                    sc = m.get("score", 0)
                    terms = ", ".join(m.get("matched_terms", []))
                    msg_line = f"• [Score: {sc*100:.0f}%] \"{txt}\" (Terms: {terms})"
                    box_content.append(Paragraph(msg_line, styles["MsgTranscript"]))
                    box_content.append(Spacer(1, 2))

            box_table = Table([[box_content]], colWidths=[515])
            box_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff1f2")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fda4af")),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(box_table))
            story.append(Spacer(1, 8))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_identifier_search_pdf(search_data: Dict[str, Any]) -> bytes:
    """Generates a detailed, expressive forensic PDF dossier for an identifier search."""
    from collections import Counter, defaultdict
    import html as _html

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    query = str(search_data.get("query") or "")
    results = search_data.get("results") or []
    count = int(search_data.get("count") or len(results))

    channel_counts: Counter = Counter()
    channel_sources: Dict[str, str] = {}
    channel_max_score: Dict[str, float] = {}
    channel_high: Counter = Counter()
    channel_med: Counter = Counter()
    channel_cats: Dict[str, set] = defaultdict(set)
    ident_types: Counter = Counter()
    risk_counts: Counter = Counter()
    all_categories: Counter = Counter()
    linked_pivots: Counter = Counter()
    timestamps: List[str] = []

    for r in results:
        ident = r.get("identifier") or {}
        msg = r.get("message") or {}
        alert = r.get("alert") or {}
        ch = msg.get("channel") or "unknown"
        src = msg.get("source") or "unknown"
        risk = alert.get("risk_level") or "UNFLAGGED"
        sc = float(alert.get("score") or 0.0)
        cats = alert.get("categories") or []

        channel_counts[ch] += 1
        channel_sources[ch] = src
        channel_max_score[ch] = max(channel_max_score.get(ch, 0.0), sc)
        if risk == "HIGH":
            channel_high[ch] += 1
        elif risk == "MEDIUM":
            channel_med[ch] += 1
        risk_counts[risk] += 1

        for c in cats:
            channel_cats[ch].add(c)
            all_categories[c] += 1

        if ident.get("type"):
            ident_types[ident["type"]] += 1
        if msg.get("created_at"):
            timestamps.append(str(msg["created_at"])[:19])
        for lk in (r.get("linked_identifiers") or []):
            if lk.get("type") and lk.get("value"):
                linked_pivots[(lk["type"], lk["value"])] += 1

    first_seen = min(timestamps) if timestamps else "N/A"
    last_seen = max(timestamps) if timestamps else "N/A"
    risk_summary = f"HIGH: {risk_counts.get('HIGH', 0)} | MED: {risk_counts.get('MEDIUM', 0)} | Other: {risk_counts.get('UNFLAGGED', 0)}"
    cat_summary = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in all_categories.most_common(6)) or "None recorded"

    story.append(Paragraph("IDENTIFIER INTELLIGENCE DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"CROSS-CHANNEL USAGE &amp; PIVOT REPORT: {_html.escape(query)}", styles["DocSubtitle"]))
    story.append(Spacer(1, 6))

    meta_data = [
        [
            Paragraph("Queried Identifier:", styles["MetaLabel"]),
            Paragraph(f"<b>{_html.escape(query)}</b>", styles["MetaValue"]),
            Paragraph("Total Occurrences:", styles["MetaLabel"]),
            Paragraph(f"<b>{count}</b> matched posts", styles["MetaValue"]),
        ],
        [
            Paragraph("Distinct Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(channel_counts)}</b> channels/accounts", styles["MetaValue"]),
            Paragraph("Risk Breakdown:", styles["MetaLabel"]),
            Paragraph(f"<b>{risk_summary}</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Identifier Types:", styles["MetaLabel"]),
            Paragraph(", ".join(f"{k} ({v})" for k, v in ident_types.items()) or "N/A", styles["MetaValue"]),
            Paragraph("Activity Window:", styles["MetaLabel"]),
            Paragraph(f"{first_seen} to {last_seen}", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Categories:", styles["MetaLabel"]),
            Paragraph(_html.escape(cat_summary), styles["MetaValue"]),
            Paragraph("Linked Pivots:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(linked_pivots)}</b> co-occurring identifiers", styles["MetaValue"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[110, 150, 105, 150])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_meta)
    story.append(Spacer(1, 12))

    if channel_counts:
        story.append(Paragraph("1. CHANNELS &amp; ACCOUNTS WHERE IDENTIFIER IS USED", styles["Heading2"]))
        ch_rows = [[
            Paragraph("Channel / Account", styles["TableHeader"]),
            Paragraph("Source", styles["TableHeader"]),
            Paragraph("Hits (H/M)", styles["TableHeader"]),
            Paragraph("Categories", styles["TableHeader"]),
            Paragraph("Peak Score", styles["TableHeader"]),
        ]]
        for ch, cnt in channel_counts.most_common(30):
            cats_txt = ", ".join(sorted(channel_cats[ch])) or "—"
            ch_rows.append([
                Paragraph(f"@{_html.escape(ch)}", styles["Body"]),
                Paragraph(_html.escape(channel_sources.get(ch, "unknown")), styles["Body"]),
                Paragraph(f"{cnt} ({channel_high[ch]}H / {channel_med[ch]}M)", styles["Body"]),
                Paragraph(_html.escape(cats_txt[:45]), styles["Body"]),
                Paragraph(f"<b>{channel_max_score.get(ch, 0.0)*100:.0f}%</b>", styles["Body"]),
            ])
        t_chs = Table(ch_rows, colWidths=[150, 80, 75, 145, 65])
        t_chs.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_chs)
        story.append(Spacer(1, 12))

    if linked_pivots:
        story.append(Paragraph("2. CO-OCCURRING / LINKED IDENTIFIERS (NETWORK PIVOTS)", styles["Heading2"]))
        pv_rows = [[
            Paragraph("Identifier Type", styles["TableHeader"]),
            Paragraph("Value", styles["TableHeader"]),
            Paragraph("Co-Occurrences", styles["TableHeader"]),
        ]]
        for (ltype, lval), lcnt in linked_pivots.most_common(25):
            pv_rows.append([
                Paragraph(_html.escape(ltype), styles["Body"]),
                Paragraph(f"<font face='Courier'>{_html.escape(str(lval)[:60])}</font>", styles["Body"]),
                Paragraph(str(lcnt), styles["Body"]),
            ])
        t_pv = Table(pv_rows, colWidths=[115, 315, 85])
        t_pv.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_pv)
        story.append(Spacer(1, 12))

    if results:
        story.append(Paragraph("3. DETAILED MATCHED POSTS &amp; EVIDENCE TRANSCRIPTS", styles["Heading2"]))
        for idx, r in enumerate(results[:25], 1):
            ident = r.get("identifier") or {}
            msg = r.get("message") or {}
            alert = r.get("alert") or {}
            ch = _html.escape(str(msg.get("channel") or "unknown"))
            src = _html.escape(str(msg.get("source") or "unknown"))
            ts = _html.escape(str((msg.get("created_at") or "")[:19]))
            risk = alert.get("risk_level") or "UNFLAGGED"
            sc = float(alert.get("score") or 0.0)
            cats = ", ".join(alert.get("categories") or []) or "none"
            prov = _html.escape(str(msg.get("provenance_status") or "not_recorded"))
            ev_h = msg.get("evidence_hash")
            prov_str = f"Provenance: <b>{prov}</b>" + (f" | SHA-256: <font face='Courier'>{str(ev_h)[:16]}...</font>" if ev_h else "")
            linked_str = ", ".join(
                f"{lk.get('type')}: {lk.get('value')}"
                for lk in (r.get("linked_identifiers") or [])[:6]
            )
            txt = _html.escape((msg.get("text") or "[no text]").replace("\n", " ")[:500])
            risk_color = "#dc2626" if risk == "HIGH" else ("#d97706" if risk == "MEDIUM" else "#64748b")

            card = [
                Paragraph(
                    f"<b>EVIDENCE #{idx}</b> — @{ch} ({src}) | "
                    f"<font color='{risk_color}'><b>{risk} ({sc*100:.0f}%)</b></font> | {ts}",
                    styles["MetaLabel"],
                ),
                Spacer(1, 2),
                Paragraph(
                    f"Matched: <b>{_html.escape(str(ident.get('type')))} = {_html.escape(str(ident.get('value')))}</b> | "
                    f"Categories: <b>{_html.escape(cats)}</b>",
                    styles["Body"],
                ),
                Paragraph(prov_str, styles["MetaLabel"]),
            ]
            if linked_str:
                card.append(Paragraph(f"Linked Identifiers: {_html.escape(linked_str)}", styles["MetaLabel"]))
            card.extend([
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ])
            t_card = Table([[card]], colWidths=[515])
            t_card.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor(risk_color)),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(t_card))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_chain_investigation_pdf(chain: Dict[str, Any]) -> bytes:
    """Generates an in-depth forensic investigation report for an entire organized crime syndicate chain."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    root_user = chain.get("root_username", "unknown")
    meta = chain.get("target_metadata", {})
    stats = chain.get("stats", {})

    # Title
    story.append(Paragraph("ORGANIZED CRIME SYNDICATE CHAIN DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"MULTI-HOP CHAIN RECONNAISSANCE AROUND TARGET @{root_user.upper()}", styles["DocSubtitle"]))
    story.append(Spacer(1, 4))

    # Executive Stats Table
    stats_data = [
        [
            Paragraph("Investigation Target:", styles["MetaLabel"]),
            Paragraph(f"<b>@{root_user}</b>", styles["MetaValue"]),
            Paragraph("Chain Nodes Discovered:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('total_nodes', 0)} entities</b> ({stats.get('total_edges', 0)} links)", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Tier:", styles["MetaLabel"]),
            Paragraph(f"<font color='#dc2626'><b>{meta.get('severity_tier', 'HIGH')}</b></font>", styles["MetaValue"]),
            Paragraph("Coordinated Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('linked_channels', 0)} channels in syndicate</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Primary Crime Vectors:", styles["MetaLabel"]),
            Paragraph(", ".join(meta.get("top_categories", [])) or "N/A", styles["MetaValue"]),
            Paragraph("Shared Financial Hubs:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('shared_financials', 0)}</b> UPI / Crypto / Phone nodes", styles["MetaValue"]),
        ],
    ]

    t_stats = Table(stats_data, colWidths=[120, 140, 120, 135])
    t_stats.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_stats)
    story.append(Spacer(1, 10))

    # Multi-Hop Chain Nodes Table
    story.append(Paragraph("DISCOVERED CHAIN NODES & ROLES", styles["Heading2"]))

    nodes = chain.get("nodes", [])
    node_rows = [[
        Paragraph("Hop", styles["TableHeader"]),
        Paragraph("Identifier / Label", styles["TableHeader"]),
        Paragraph("Type", styles["TableHeader"]),
        Paragraph("Syndicate Supply Chain Role", styles["TableHeader"]),
    ]]

    # Sort nodes by hop, then type
    sorted_nodes = sorted(nodes, key=lambda x: (x.get("hop", 0), x.get("type", "")))

    for n in sorted_nodes[:35]:
        hop = f"Hop {n.get('hop', 0)}" if n.get("hop", 0) > 0 else "Anchor (0)"
        lbl = n.get("label", "")
        ntype = n.get("type", "").upper()
        role = n.get("role", "Node")

        node_rows.append([
            Paragraph(f"<b>{hop}</b>", styles["Body"]),
            Paragraph(lbl, styles["BodyBold"]),
            Paragraph(ntype, styles["Body"]),
            Paragraph(role, styles["Body"]),
        ])

    t_nodes = Table(node_rows, colWidths=[55, 140, 70, 250])
    t_nodes.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ])
    )
    story.append(t_nodes)
    story.append(Spacer(1, 12))

    # Syndicate Linkage Details
    cluster = chain.get("syndicate_cluster", [])
    if cluster:
        story.append(Paragraph("COORDINATED SYNDICATE CHANNELS (SHARED INFRASTRUCTURE)", styles["Heading2"]))
        story.append(Paragraph(
            "The following public Telegram channels operate in coordination with the target, sharing the exact same "
            "financial payment destinations, admin brokers, or forward sourcing lines:",
            styles["Body"],
        ))
        story.append(Spacer(1, 4))

        cluster_chips = "  •  ".join([f"<b>@{c}</b>" for c in cluster[:12]])
        story.append(Paragraph(cluster_chips, styles["BodyBold"]))
        story.append(Spacer(1, 10))

    # Cross-Channel Intercept Timeline
    timeline = chain.get("timeline", [])
    if timeline:
        story.append(Paragraph("CHRONOLOGICAL CROSS-CHANNEL INTERCEPT TIMELINE", styles["Heading2"]))

        for t in timeline[:6]:
            dt = t.get("date") or "Unknown Timestamp"
            src = t.get("source") or "Unknown Source"
            sc = t.get("score") or 0.0
            txt = t.get("excerpt", "").replace("\n", " ")

            ev_content = [
                Paragraph(f"<b>{t.get('event', 'Forward')}</b> — Source: <b>@{src}</b> ➔ Target: <b>@{root_user}</b> | Date: {dt[:19]} | Threat: {sc*100:.0f}%", styles["MetaLabel"]),
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ]

            ev_table = Table([[ev_content]], colWidths=[515])
            ev_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor("#ec4899")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(ev_table))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_identifier_search_pdf(search_data: Dict[str, Any]) -> bytes:
    """Generates a detailed, expressive forensic PDF dossier for an identifier search."""
    from collections import Counter, defaultdict
    import html as _html

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    query = str(search_data.get("query") or "")
    results = search_data.get("results") or []
    count = int(search_data.get("count") or len(results))

    channel_counts: Counter = Counter()
    channel_sources: Dict[str, str] = {}
    channel_max_score: Dict[str, float] = {}
    channel_high: Counter = Counter()
    channel_med: Counter = Counter()
    channel_cats: Dict[str, set] = defaultdict(set)
    ident_types: Counter = Counter()
    risk_counts: Counter = Counter()
    all_categories: Counter = Counter()
    linked_pivots: Counter = Counter()
    timestamps: List[str] = []

    for r in results:
        ident = r.get("identifier") or {}
        msg = r.get("message") or {}
        alert = r.get("alert") or {}
        ch = msg.get("channel") or "unknown"
        src = msg.get("source") or "unknown"
        risk = alert.get("risk_level") or "UNFLAGGED"
        sc = float(alert.get("score") or 0.0)
        cats = alert.get("categories") or []

        channel_counts[ch] += 1
        channel_sources[ch] = src
        channel_max_score[ch] = max(channel_max_score.get(ch, 0.0), sc)
        if risk == "HIGH":
            channel_high[ch] += 1
        elif risk == "MEDIUM":
            channel_med[ch] += 1
        risk_counts[risk] += 1

        for c in cats:
            channel_cats[ch].add(c)
            all_categories[c] += 1

        if ident.get("type"):
            ident_types[ident["type"]] += 1
        if msg.get("created_at"):
            timestamps.append(str(msg["created_at"])[:19])
        for lk in (r.get("linked_identifiers") or []):
            if lk.get("type") and lk.get("value"):
                linked_pivots[(lk["type"], lk["value"])] += 1

    first_seen = min(timestamps) if timestamps else "N/A"
    last_seen = max(timestamps) if timestamps else "N/A"
    risk_summary = f"HIGH: {risk_counts.get('HIGH', 0)} | MED: {risk_counts.get('MEDIUM', 0)} | Other: {risk_counts.get('UNFLAGGED', 0)}"
    cat_summary = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in all_categories.most_common(6)) or "None recorded"

    story.append(Paragraph("IDENTIFIER INTELLIGENCE DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"CROSS-CHANNEL USAGE &amp; PIVOT REPORT: {_html.escape(query)}", styles["DocSubtitle"]))
    story.append(Spacer(1, 6))

    meta_data = [
        [
            Paragraph("Queried Identifier:", styles["MetaLabel"]),
            Paragraph(f"<b>{_html.escape(query)}</b>", styles["MetaValue"]),
            Paragraph("Total Occurrences:", styles["MetaLabel"]),
            Paragraph(f"<b>{count}</b> matched posts", styles["MetaValue"]),
        ],
        [
            Paragraph("Distinct Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(channel_counts)}</b> channels/accounts", styles["MetaValue"]),
            Paragraph("Risk Breakdown:", styles["MetaLabel"]),
            Paragraph(f"<b>{risk_summary}</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Identifier Types:", styles["MetaLabel"]),
            Paragraph(", ".join(f"{k} ({v})" for k, v in ident_types.items()) or "N/A", styles["MetaValue"]),
            Paragraph("Activity Window:", styles["MetaLabel"]),
            Paragraph(f"{first_seen} to {last_seen}", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Categories:", styles["MetaLabel"]),
            Paragraph(_html.escape(cat_summary), styles["MetaValue"]),
            Paragraph("Linked Pivots:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(linked_pivots)}</b> co-occurring identifiers", styles["MetaValue"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[110, 150, 105, 150])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_meta)
    story.append(Spacer(1, 12))

    if channel_counts:
        story.append(Paragraph("1. CHANNELS &amp; ACCOUNTS WHERE IDENTIFIER IS USED", styles["Heading2"]))
        ch_rows = [[
            Paragraph("Channel / Account", styles["TableHeader"]),
            Paragraph("Source", styles["TableHeader"]),
            Paragraph("Hits (H/M)", styles["TableHeader"]),
            Paragraph("Categories", styles["TableHeader"]),
            Paragraph("Peak Score", styles["TableHeader"]),
        ]]
        for ch, cnt in channel_counts.most_common(30):
            cats_txt = ", ".join(sorted(channel_cats[ch])) or "—"
            ch_rows.append([
                Paragraph(f"@{_html.escape(ch)}", styles["Body"]),
                Paragraph(_html.escape(channel_sources.get(ch, "unknown")), styles["Body"]),
                Paragraph(f"{cnt} ({channel_high[ch]}H / {channel_med[ch]}M)", styles["Body"]),
                Paragraph(_html.escape(cats_txt[:45]), styles["Body"]),
                Paragraph(f"<b>{channel_max_score.get(ch, 0.0)*100:.0f}%</b>", styles["Body"]),
            ])
        t_chs = Table(ch_rows, colWidths=[150, 80, 75, 145, 65])
        t_chs.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_chs)
        story.append(Spacer(1, 12))

    if linked_pivots:
        story.append(Paragraph("2. CO-OCCURRING / LINKED IDENTIFIERS (NETWORK PIVOTS)", styles["Heading2"]))
        pv_rows = [[
            Paragraph("Identifier Type", styles["TableHeader"]),
            Paragraph("Value", styles["TableHeader"]),
            Paragraph("Co-Occurrences", styles["TableHeader"]),
        ]]
        for (ltype, lval), lcnt in linked_pivots.most_common(25):
            pv_rows.append([
                Paragraph(_html.escape(ltype), styles["Body"]),
                Paragraph(f"<font face='Courier'>{_html.escape(str(lval)[:60])}</font>", styles["Body"]),
                Paragraph(str(lcnt), styles["Body"]),
            ])
        t_pv = Table(pv_rows, colWidths=[115, 315, 85])
        t_pv.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_pv)
        story.append(Spacer(1, 12))

    if results:
        story.append(Paragraph("3. DETAILED MATCHED POSTS &amp; EVIDENCE TRANSCRIPTS", styles["Heading2"]))
        for idx, r in enumerate(results[:25], 1):
            ident = r.get("identifier") or {}
            msg = r.get("message") or {}
            alert = r.get("alert") or {}
            ch = _html.escape(str(msg.get("channel") or "unknown"))
            src = _html.escape(str(msg.get("source") or "unknown"))
            ts = _html.escape(str((msg.get("created_at") or "")[:19]))
            risk = alert.get("risk_level") or "UNFLAGGED"
            sc = float(alert.get("score") or 0.0)
            cats = ", ".join(alert.get("categories") or []) or "none"
            prov = _html.escape(str(msg.get("provenance_status") or "not_recorded"))
            ev_h = msg.get("evidence_hash")
            prov_str = f"Provenance: <b>{prov}</b>" + (f" | SHA-256: <font face='Courier'>{str(ev_h)[:16]}...</font>" if ev_h else "")
            linked_str = ", ".join(
                f"{lk.get('type')}: {lk.get('value')}"
                for lk in (r.get("linked_identifiers") or [])[:6]
            )
            txt = _html.escape((msg.get("text") or "[no text]").replace("\n", " ")[:500])
            risk_color = "#dc2626" if risk == "HIGH" else ("#d97706" if risk == "MEDIUM" else "#64748b")

            card = [
                Paragraph(
                    f"<b>EVIDENCE #{idx}</b> — @{ch} ({src}) | "
                    f"<font color='{risk_color}'><b>{risk} ({sc*100:.0f}%)</b></font> | {ts}",
                    styles["MetaLabel"],
                ),
                Spacer(1, 2),
                Paragraph(
                    f"Matched: <b>{_html.escape(str(ident.get('type')))} = {_html.escape(str(ident.get('value')))}</b> | "
                    f"Categories: <b>{_html.escape(cats)}</b>",
                    styles["Body"],
                ),
                Paragraph(prov_str, styles["MetaLabel"]),
            ]
            if linked_str:
                card.append(Paragraph(f"Linked Identifiers: {_html.escape(linked_str)}", styles["MetaLabel"]))
            card.extend([
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ])
            t_card = Table([[card]], colWidths=[515])
            t_card.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor(risk_color)),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(t_card))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()



def generate_channel_dossier_pdf(channel: Dict[str, Any], network: Optional[Dict[str, Any]] = None) -> bytes:
    """Generates an in-depth forensic intelligence dossier for a single target channel."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    username = channel.get("channel_username") or channel.get("username", "unknown")
    title = channel.get("channel_title") or channel.get("title") or f"Channel @{username}"
    risk = channel.get("risk_level", "MEDIUM")

    # Title
    story.append(Paragraph(f"CHANNEL INTELLIGENCE DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"TARGET: @{username} — {title.upper()}", styles["DocSubtitle"]))
    story.append(Spacer(1, 4))

    # Profile Table
    risk_style = styles["BadgeHigh"] if risk == "HIGH" else (styles["BadgeMedium"] if risk == "MEDIUM" else styles["BadgeLow"])

    profile_data = [
        [
            Paragraph("Telegram Handle:", styles["MetaLabel"]),
            Paragraph(f"<b>@{username}</b>", styles["MetaValue"]),
            Paragraph("Threat Assessment:", styles["MetaLabel"]),
            Paragraph(f"<b>{risk} RISK</b>", risk_style),
        ],
        [
            Paragraph("Channel Title:", styles["MetaLabel"]),
            Paragraph(title, styles["MetaValue"]),
            Paragraph("Threat Score:", styles["MetaLabel"]),
            Paragraph(f"<b>{channel.get('avg_score', 0)*100:.1f}%</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Subscribers / Members:", styles["MetaLabel"]),
            Paragraph(f"{channel.get('member_count', 0):,}" if channel.get("member_count") else "Unknown", styles["MetaValue"]),
            Paragraph("Telegram ID:", styles["MetaLabel"]),
            Paragraph(str(channel.get("telegram_id") or "Unresolved"), styles["MetaValue"]),
        ],
        [
            Paragraph("Verified Status:", styles["MetaLabel"]),
            Paragraph("YES (Verified)" if channel.get("is_verified") else "No", styles["MetaValue"]),
            Paragraph("Scam/Fake Flags:", styles["MetaLabel"]),
            Paragraph("<font color='#dc2626'>FLAGGED SCAM</font>" if channel.get("is_scam") else "None", styles["MetaValue"]),
        ],
        [
            Paragraph("Invite Link:", styles["MetaLabel"]),
            Paragraph(f"<font color='#2563eb'>{channel.get('invite_link') or f'https://t.me/{username}'}</font>", styles["MetaValue"]),
            Paragraph("Messages Scanned:", styles["MetaLabel"]),
            Paragraph(f"{channel.get('messages_scanned', 0)} total ({channel.get('flagged_count', 0)} flagged)", styles["MetaValue"]),
        ],
    ]

    t_prof = Table(profile_data, colWidths=[110, 150, 110, 145])
    t_prof.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_prof)
    story.append(Spacer(1, 10))

    # Channel Bio / Description
    desc = channel.get("channel_description") or channel.get("description")
    if desc:
        story.append(Paragraph("CHANNEL BIO / ABOUT TEXT", styles["Heading3"]))
        story.append(Paragraph(desc, styles["Body"]))
        story.append(Spacer(1, 8))

    # Matched Crime Categories
    cats = channel.get("top_categories", [])
    if cats:
        story.append(Paragraph("PRIMARY DETECTED CRIME CATEGORIES", styles["Heading2"]))
        cat_chips = "  •  ".join([f"<b>{c.replace('_', ' ').upper()}</b>" for c in cats])
        story.append(Paragraph(cat_chips, styles["BodyBold"]))
        story.append(Spacer(1, 8))

    # Extracted Financial & Contact Identifiers
    idents = channel.get("top_identifiers", [])
    story.append(Paragraph("EXTRACTED IDENTIFIERS & FINANCIAL INSTRUMENTS", styles["Heading2"]))

    if idents:
        ident_rows = [[
            Paragraph("Type", styles["TableHeader"]),
            Paragraph("Identifier Value", styles["TableHeader"]),
            Paragraph("Action / Relevance", styles["TableHeader"]),
        ]]
        for it in idents:
            typ = it.get("type", "").upper()
            val = it.get("value", "")
            action = "Payment Destination" if "WALLET" in typ or "UPI" in typ else ("Contact Node" if "PHONE" in typ or "HANDLE" in typ else "Domain Link")
            ident_rows.append([
                Paragraph(typ, styles["BodyBold"]),
                Paragraph(val, styles["Body"]),
                Paragraph(action, styles["Body"]),
            ])

        t_ident = Table(ident_rows, colWidths=[90, 260, 165])
        t_ident.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ])
        )
        story.append(t_ident)
    else:
        story.append(Paragraph("No phone, UPI, or crypto identifiers extracted from public posts yet.", styles["Body"]))

    story.append(Spacer(1, 12))

    # Connected Nodes & Network Syndicates
    connected = channel.get("connected_nodes") or {}
    if isinstance(connected, str):
        try:
            connected = __import__("json").loads(connected)
        except Exception:
            connected = {}

    story.append(Paragraph("CONNECTING NODES & SYNDICATE LINKS", styles["Heading2"]))

    conn_channels = connected.get("channels", [])
    conn_handles = connected.get("handles", [])
    conn_upis = connected.get("upis", [])
    conn_phones = connected.get("phones", [])
    conn_wallets = connected.get("wallets", [])

    net_rows = [
        [
            Paragraph("Linked Channels / Forwards:", styles["MetaLabel"]),
            Paragraph(", ".join([f"@{c}" for c in conn_channels[:10]]) if conn_channels else "None observed", styles["MetaValue"]),
        ],
        [
            Paragraph("Admin / Contact Handles:", styles["MetaLabel"]),
            Paragraph(", ".join([f"@{h}" for h in conn_handles[:10]]) if conn_handles else "None observed", styles["MetaValue"]),
        ],
        [
            Paragraph("Shared / Used UPIs:", styles["MetaLabel"]),
            Paragraph(", ".join(conn_upis[:8]) if conn_upis else "None", styles["MetaValue"]),
        ],
        [
            Paragraph("Associated Phone Numbers:", styles["MetaLabel"]),
            Paragraph(", ".join(conn_phones[:8]) if conn_phones else "None", styles["MetaValue"]),
        ],
    ]
    t_net = Table(net_rows, colWidths=[140, 375])
    t_net.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_net)
    story.append(Spacer(1, 14))

    # Flagged Evidence Transcripts
    sample_msgs = channel.get("sample_messages", [])
    if sample_msgs:
        story.append(Paragraph("FLAGGED MESSAGE TRANSCRIPTS & EVIDENCE", styles["Heading2"]))

        for idx, m in enumerate(sample_msgs[:8], 1):
            m_score = m.get("score", 0)
            m_risk = m.get("risk_level", "HIGH")
            m_date = m.get("date") or "Unknown Date"
            m_views = m.get("views")
            m_terms = ", ".join(m.get("matched_terms", []))
            m_text = m.get("text", "").replace("\n", " ")
            m_prov = m.get("provenance_status") or "not_recorded"
            m_prov_note = m.get("provenance_note")
            if m_prov == "unverifiable_media" and not m_prov_note:
                m_prov_note = "Original media unavailable; provenance cannot be fully recomputed."
            m_ev_hash = m.get("evidence_hash")
            prov_line = f"Provenance: <b>{m_prov}</b>"
            if m_ev_hash:
                prov_line += f" | SHA-256: <font face='Courier'>{str(m_ev_hash)[:16]}...</font>"

            ev_content = [
                Paragraph(f"<b>INTERCEPT #{idx}</b> — Risk: <font color='#dc2626'><b>{m_risk} ({m_score*100:.0f}%)</b></font> | Date: {m_date[:19]} | Views: {m_views or 'N/A'}", styles["MetaLabel"]),
                Spacer(1, 2),
                Paragraph(prov_line, styles["MetaLabel"]),
            ]
            if m_prov_note:
                ev_content.append(Paragraph(f"<font color='#b45309'><b>Provenance Notice:</b> {m_prov_note}</font>", styles["MetaLabel"]))
            ev_content.extend([
                Spacer(1, 2),
                Paragraph(f"Matched Keywords: <b>{m_terms or 'Slang Pattern'}</b>", styles["BodyBold"]),
                Spacer(1, 2),
                Paragraph(f"\"{m_text}\"", styles["MsgTranscript"]),
            ])

            ev_table = Table([[ev_content]], colWidths=[515])
            ev_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor("#dc2626") if m_risk == "HIGH" else colors.HexColor("#f59e0b")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(ev_table))
            story.append(Spacer(1, 6))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_identifier_search_pdf(search_data: Dict[str, Any]) -> bytes:
    """Generates a detailed, expressive forensic PDF dossier for an identifier search."""
    from collections import Counter, defaultdict
    import html as _html

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    query = str(search_data.get("query") or "")
    results = search_data.get("results") or []
    count = int(search_data.get("count") or len(results))

    channel_counts: Counter = Counter()
    channel_sources: Dict[str, str] = {}
    channel_max_score: Dict[str, float] = {}
    channel_high: Counter = Counter()
    channel_med: Counter = Counter()
    channel_cats: Dict[str, set] = defaultdict(set)
    ident_types: Counter = Counter()
    risk_counts: Counter = Counter()
    all_categories: Counter = Counter()
    linked_pivots: Counter = Counter()
    timestamps: List[str] = []

    for r in results:
        ident = r.get("identifier") or {}
        msg = r.get("message") or {}
        alert = r.get("alert") or {}
        ch = msg.get("channel") or "unknown"
        src = msg.get("source") or "unknown"
        risk = alert.get("risk_level") or "UNFLAGGED"
        sc = float(alert.get("score") or 0.0)
        cats = alert.get("categories") or []

        channel_counts[ch] += 1
        channel_sources[ch] = src
        channel_max_score[ch] = max(channel_max_score.get(ch, 0.0), sc)
        if risk == "HIGH":
            channel_high[ch] += 1
        elif risk == "MEDIUM":
            channel_med[ch] += 1
        risk_counts[risk] += 1

        for c in cats:
            channel_cats[ch].add(c)
            all_categories[c] += 1

        if ident.get("type"):
            ident_types[ident["type"]] += 1
        if msg.get("created_at"):
            timestamps.append(str(msg["created_at"])[:19])
        for lk in (r.get("linked_identifiers") or []):
            if lk.get("type") and lk.get("value"):
                linked_pivots[(lk["type"], lk["value"])] += 1

    first_seen = min(timestamps) if timestamps else "N/A"
    last_seen = max(timestamps) if timestamps else "N/A"
    risk_summary = f"HIGH: {risk_counts.get('HIGH', 0)} | MED: {risk_counts.get('MEDIUM', 0)} | Other: {risk_counts.get('UNFLAGGED', 0)}"
    cat_summary = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in all_categories.most_common(6)) or "None recorded"

    story.append(Paragraph("IDENTIFIER INTELLIGENCE DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"CROSS-CHANNEL USAGE &amp; PIVOT REPORT: {_html.escape(query)}", styles["DocSubtitle"]))
    story.append(Spacer(1, 6))

    meta_data = [
        [
            Paragraph("Queried Identifier:", styles["MetaLabel"]),
            Paragraph(f"<b>{_html.escape(query)}</b>", styles["MetaValue"]),
            Paragraph("Total Occurrences:", styles["MetaLabel"]),
            Paragraph(f"<b>{count}</b> matched posts", styles["MetaValue"]),
        ],
        [
            Paragraph("Distinct Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(channel_counts)}</b> channels/accounts", styles["MetaValue"]),
            Paragraph("Risk Breakdown:", styles["MetaLabel"]),
            Paragraph(f"<b>{risk_summary}</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Identifier Types:", styles["MetaLabel"]),
            Paragraph(", ".join(f"{k} ({v})" for k, v in ident_types.items()) or "N/A", styles["MetaValue"]),
            Paragraph("Activity Window:", styles["MetaLabel"]),
            Paragraph(f"{first_seen} to {last_seen}", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Categories:", styles["MetaLabel"]),
            Paragraph(_html.escape(cat_summary), styles["MetaValue"]),
            Paragraph("Linked Pivots:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(linked_pivots)}</b> co-occurring identifiers", styles["MetaValue"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[110, 150, 105, 150])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_meta)
    story.append(Spacer(1, 12))

    if channel_counts:
        story.append(Paragraph("1. CHANNELS &amp; ACCOUNTS WHERE IDENTIFIER IS USED", styles["Heading2"]))
        ch_rows = [[
            Paragraph("Channel / Account", styles["TableHeader"]),
            Paragraph("Source", styles["TableHeader"]),
            Paragraph("Hits (H/M)", styles["TableHeader"]),
            Paragraph("Categories", styles["TableHeader"]),
            Paragraph("Peak Score", styles["TableHeader"]),
        ]]
        for ch, cnt in channel_counts.most_common(30):
            cats_txt = ", ".join(sorted(channel_cats[ch])) or "—"
            ch_rows.append([
                Paragraph(f"@{_html.escape(ch)}", styles["Body"]),
                Paragraph(_html.escape(channel_sources.get(ch, "unknown")), styles["Body"]),
                Paragraph(f"{cnt} ({channel_high[ch]}H / {channel_med[ch]}M)", styles["Body"]),
                Paragraph(_html.escape(cats_txt[:45]), styles["Body"]),
                Paragraph(f"<b>{channel_max_score.get(ch, 0.0)*100:.0f}%</b>", styles["Body"]),
            ])
        t_chs = Table(ch_rows, colWidths=[150, 80, 75, 145, 65])
        t_chs.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_chs)
        story.append(Spacer(1, 12))

    if linked_pivots:
        story.append(Paragraph("2. CO-OCCURRING / LINKED IDENTIFIERS (NETWORK PIVOTS)", styles["Heading2"]))
        pv_rows = [[
            Paragraph("Identifier Type", styles["TableHeader"]),
            Paragraph("Value", styles["TableHeader"]),
            Paragraph("Co-Occurrences", styles["TableHeader"]),
        ]]
        for (ltype, lval), lcnt in linked_pivots.most_common(25):
            pv_rows.append([
                Paragraph(_html.escape(ltype), styles["Body"]),
                Paragraph(f"<font face='Courier'>{_html.escape(str(lval)[:60])}</font>", styles["Body"]),
                Paragraph(str(lcnt), styles["Body"]),
            ])
        t_pv = Table(pv_rows, colWidths=[115, 315, 85])
        t_pv.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_pv)
        story.append(Spacer(1, 12))

    if results:
        story.append(Paragraph("3. DETAILED MATCHED POSTS &amp; EVIDENCE TRANSCRIPTS", styles["Heading2"]))
        for idx, r in enumerate(results[:25], 1):
            ident = r.get("identifier") or {}
            msg = r.get("message") or {}
            alert = r.get("alert") or {}
            ch = _html.escape(str(msg.get("channel") or "unknown"))
            src = _html.escape(str(msg.get("source") or "unknown"))
            ts = _html.escape(str((msg.get("created_at") or "")[:19]))
            risk = alert.get("risk_level") or "UNFLAGGED"
            sc = float(alert.get("score") or 0.0)
            cats = ", ".join(alert.get("categories") or []) or "none"
            prov = _html.escape(str(msg.get("provenance_status") or "not_recorded"))
            ev_h = msg.get("evidence_hash")
            prov_str = f"Provenance: <b>{prov}</b>" + (f" | SHA-256: <font face='Courier'>{str(ev_h)[:16]}...</font>" if ev_h else "")
            linked_str = ", ".join(
                f"{lk.get('type')}: {lk.get('value')}"
                for lk in (r.get("linked_identifiers") or [])[:6]
            )
            txt = _html.escape((msg.get("text") or "[no text]").replace("\n", " ")[:500])
            risk_color = "#dc2626" if risk == "HIGH" else ("#d97706" if risk == "MEDIUM" else "#64748b")

            card = [
                Paragraph(
                    f"<b>EVIDENCE #{idx}</b> — @{ch} ({src}) | "
                    f"<font color='{risk_color}'><b>{risk} ({sc*100:.0f}%)</b></font> | {ts}",
                    styles["MetaLabel"],
                ),
                Spacer(1, 2),
                Paragraph(
                    f"Matched: <b>{_html.escape(str(ident.get('type')))} = {_html.escape(str(ident.get('value')))}</b> | "
                    f"Categories: <b>{_html.escape(cats)}</b>",
                    styles["Body"],
                ),
                Paragraph(prov_str, styles["MetaLabel"]),
            ]
            if linked_str:
                card.append(Paragraph(f"Linked Identifiers: {_html.escape(linked_str)}", styles["MetaLabel"]))
            card.extend([
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ])
            t_card = Table([[card]], colWidths=[515])
            t_card.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor(risk_color)),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(t_card))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_chain_investigation_pdf(chain: Dict[str, Any]) -> bytes:
    """Generates an in-depth forensic investigation report for an entire organized crime syndicate chain."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    root_user = chain.get("root_username", "unknown")
    meta = chain.get("target_metadata", {})
    stats = chain.get("stats", {})

    # Title
    story.append(Paragraph("ORGANIZED CRIME SYNDICATE CHAIN DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"MULTI-HOP CHAIN RECONNAISSANCE AROUND TARGET @{root_user.upper()}", styles["DocSubtitle"]))
    story.append(Spacer(1, 4))

    # Executive Stats Table
    stats_data = [
        [
            Paragraph("Investigation Target:", styles["MetaLabel"]),
            Paragraph(f"<b>@{root_user}</b>", styles["MetaValue"]),
            Paragraph("Chain Nodes Discovered:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('total_nodes', 0)} entities</b> ({stats.get('total_edges', 0)} links)", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Tier:", styles["MetaLabel"]),
            Paragraph(f"<font color='#dc2626'><b>{meta.get('severity_tier', 'HIGH')}</b></font>", styles["MetaValue"]),
            Paragraph("Coordinated Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('linked_channels', 0)} channels in syndicate</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Primary Crime Vectors:", styles["MetaLabel"]),
            Paragraph(", ".join(meta.get("top_categories", [])) or "N/A", styles["MetaValue"]),
            Paragraph("Shared Financial Hubs:", styles["MetaLabel"]),
            Paragraph(f"<b>{stats.get('shared_financials', 0)}</b> UPI / Crypto / Phone nodes", styles["MetaValue"]),
        ],
    ]

    t_stats = Table(stats_data, colWidths=[120, 140, 120, 135])
    t_stats.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_stats)
    story.append(Spacer(1, 10))

    # Multi-Hop Chain Nodes Table
    story.append(Paragraph("DISCOVERED CHAIN NODES & ROLES", styles["Heading2"]))

    nodes = chain.get("nodes", [])
    node_rows = [[
        Paragraph("Hop", styles["TableHeader"]),
        Paragraph("Identifier / Label", styles["TableHeader"]),
        Paragraph("Type", styles["TableHeader"]),
        Paragraph("Syndicate Supply Chain Role", styles["TableHeader"]),
    ]]

    # Sort nodes by hop, then type
    sorted_nodes = sorted(nodes, key=lambda x: (x.get("hop", 0), x.get("type", "")))

    for n in sorted_nodes[:35]:
        hop = f"Hop {n.get('hop', 0)}" if n.get("hop", 0) > 0 else "Anchor (0)"
        lbl = n.get("label", "")
        ntype = n.get("type", "").upper()
        role = n.get("role", "Node")

        node_rows.append([
            Paragraph(f"<b>{hop}</b>", styles["Body"]),
            Paragraph(lbl, styles["BodyBold"]),
            Paragraph(ntype, styles["Body"]),
            Paragraph(role, styles["Body"]),
        ])

    t_nodes = Table(node_rows, colWidths=[55, 140, 70, 250])
    t_nodes.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ])
    )
    story.append(t_nodes)
    story.append(Spacer(1, 12))

    # Syndicate Linkage Details
    cluster = chain.get("syndicate_cluster", [])
    if cluster:
        story.append(Paragraph("COORDINATED SYNDICATE CHANNELS (SHARED INFRASTRUCTURE)", styles["Heading2"]))
        story.append(Paragraph(
            "The following public Telegram channels operate in coordination with the target, sharing the exact same "
            "financial payment destinations, admin brokers, or forward sourcing lines:",
            styles["Body"],
        ))
        story.append(Spacer(1, 4))

        cluster_chips = "  •  ".join([f"<b>@{c}</b>" for c in cluster[:12]])
        story.append(Paragraph(cluster_chips, styles["BodyBold"]))
        story.append(Spacer(1, 10))

    # Cross-Channel Intercept Timeline
    timeline = chain.get("timeline", [])
    if timeline:
        story.append(Paragraph("CHRONOLOGICAL CROSS-CHANNEL INTERCEPT TIMELINE", styles["Heading2"]))

        for t in timeline[:6]:
            dt = t.get("date") or "Unknown Timestamp"
            src = t.get("source") or "Unknown Source"
            sc = t.get("score") or 0.0
            txt = t.get("excerpt", "").replace("\n", " ")

            ev_content = [
                Paragraph(f"<b>{t.get('event', 'Forward')}</b> — Source: <b>@{src}</b> ➔ Target: <b>@{root_user}</b> | Date: {dt[:19]} | Threat: {sc*100:.0f}%", styles["MetaLabel"]),
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ]

            ev_table = Table([[ev_content]], colWidths=[515])
            ev_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor("#ec4899")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(ev_table))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def generate_identifier_search_pdf(search_data: Dict[str, Any]) -> bytes:
    """Generates a detailed, expressive forensic PDF dossier for an identifier search."""
    from collections import Counter, defaultdict
    import html as _html

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=55,
    )

    styles = _get_styles()
    story = []

    query = str(search_data.get("query") or "")
    results = search_data.get("results") or []
    count = int(search_data.get("count") or len(results))

    channel_counts: Counter = Counter()
    channel_sources: Dict[str, str] = {}
    channel_max_score: Dict[str, float] = {}
    channel_high: Counter = Counter()
    channel_med: Counter = Counter()
    channel_cats: Dict[str, set] = defaultdict(set)
    ident_types: Counter = Counter()
    risk_counts: Counter = Counter()
    all_categories: Counter = Counter()
    linked_pivots: Counter = Counter()
    timestamps: List[str] = []

    for r in results:
        ident = r.get("identifier") or {}
        msg = r.get("message") or {}
        alert = r.get("alert") or {}
        ch = msg.get("channel") or "unknown"
        src = msg.get("source") or "unknown"
        risk = alert.get("risk_level") or "UNFLAGGED"
        sc = float(alert.get("score") or 0.0)
        cats = alert.get("categories") or []

        channel_counts[ch] += 1
        channel_sources[ch] = src
        channel_max_score[ch] = max(channel_max_score.get(ch, 0.0), sc)
        if risk == "HIGH":
            channel_high[ch] += 1
        elif risk == "MEDIUM":
            channel_med[ch] += 1
        risk_counts[risk] += 1

        for c in cats:
            channel_cats[ch].add(c)
            all_categories[c] += 1

        if ident.get("type"):
            ident_types[ident["type"]] += 1
        if msg.get("created_at"):
            timestamps.append(str(msg["created_at"])[:19])
        for lk in (r.get("linked_identifiers") or []):
            if lk.get("type") and lk.get("value"):
                linked_pivots[(lk["type"], lk["value"])] += 1

    first_seen = min(timestamps) if timestamps else "N/A"
    last_seen = max(timestamps) if timestamps else "N/A"
    risk_summary = f"HIGH: {risk_counts.get('HIGH', 0)} | MED: {risk_counts.get('MEDIUM', 0)} | Other: {risk_counts.get('UNFLAGGED', 0)}"
    cat_summary = ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in all_categories.most_common(6)) or "None recorded"

    story.append(Paragraph("IDENTIFIER INTELLIGENCE DOSSIER", styles["DocTitle"]))
    story.append(Paragraph(f"CROSS-CHANNEL USAGE &amp; PIVOT REPORT: {_html.escape(query)}", styles["DocSubtitle"]))
    story.append(Spacer(1, 6))

    meta_data = [
        [
            Paragraph("Queried Identifier:", styles["MetaLabel"]),
            Paragraph(f"<b>{_html.escape(query)}</b>", styles["MetaValue"]),
            Paragraph("Total Occurrences:", styles["MetaLabel"]),
            Paragraph(f"<b>{count}</b> matched posts", styles["MetaValue"]),
        ],
        [
            Paragraph("Distinct Channels:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(channel_counts)}</b> channels/accounts", styles["MetaValue"]),
            Paragraph("Risk Breakdown:", styles["MetaLabel"]),
            Paragraph(f"<b>{risk_summary}</b>", styles["MetaValue"]),
        ],
        [
            Paragraph("Identifier Types:", styles["MetaLabel"]),
            Paragraph(", ".join(f"{k} ({v})" for k, v in ident_types.items()) or "N/A", styles["MetaValue"]),
            Paragraph("Activity Window:", styles["MetaLabel"]),
            Paragraph(f"{first_seen} to {last_seen}", styles["MetaValue"]),
        ],
        [
            Paragraph("Threat Categories:", styles["MetaLabel"]),
            Paragraph(_html.escape(cat_summary), styles["MetaValue"]),
            Paragraph("Linked Pivots:", styles["MetaLabel"]),
            Paragraph(f"<b>{len(linked_pivots)}</b> co-occurring identifiers", styles["MetaValue"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[110, 150, 105, 150])
    t_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(t_meta)
    story.append(Spacer(1, 12))

    if channel_counts:
        story.append(Paragraph("1. CHANNELS &amp; ACCOUNTS WHERE IDENTIFIER IS USED", styles["Heading2"]))
        ch_rows = [[
            Paragraph("Channel / Account", styles["TableHeader"]),
            Paragraph("Source", styles["TableHeader"]),
            Paragraph("Hits (H/M)", styles["TableHeader"]),
            Paragraph("Categories", styles["TableHeader"]),
            Paragraph("Peak Score", styles["TableHeader"]),
        ]]
        for ch, cnt in channel_counts.most_common(30):
            cats_txt = ", ".join(sorted(channel_cats[ch])) or "—"
            ch_rows.append([
                Paragraph(f"@{_html.escape(ch)}", styles["Body"]),
                Paragraph(_html.escape(channel_sources.get(ch, "unknown")), styles["Body"]),
                Paragraph(f"{cnt} ({channel_high[ch]}H / {channel_med[ch]}M)", styles["Body"]),
                Paragraph(_html.escape(cats_txt[:45]), styles["Body"]),
                Paragraph(f"<b>{channel_max_score.get(ch, 0.0)*100:.0f}%</b>", styles["Body"]),
            ])
        t_chs = Table(ch_rows, colWidths=[150, 80, 75, 145, 65])
        t_chs.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_chs)
        story.append(Spacer(1, 12))

    if linked_pivots:
        story.append(Paragraph("2. CO-OCCURRING / LINKED IDENTIFIERS (NETWORK PIVOTS)", styles["Heading2"]))
        pv_rows = [[
            Paragraph("Identifier Type", styles["TableHeader"]),
            Paragraph("Value", styles["TableHeader"]),
            Paragraph("Co-Occurrences", styles["TableHeader"]),
        ]]
        for (ltype, lval), lcnt in linked_pivots.most_common(25):
            pv_rows.append([
                Paragraph(_html.escape(ltype), styles["Body"]),
                Paragraph(f"<font face='Courier'>{_html.escape(str(lval)[:60])}</font>", styles["Body"]),
                Paragraph(str(lcnt), styles["Body"]),
            ])
        t_pv = Table(pv_rows, colWidths=[115, 315, 85])
        t_pv.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(t_pv)
        story.append(Spacer(1, 12))

    if results:
        story.append(Paragraph("3. DETAILED MATCHED POSTS &amp; EVIDENCE TRANSCRIPTS", styles["Heading2"]))
        for idx, r in enumerate(results[:25], 1):
            ident = r.get("identifier") or {}
            msg = r.get("message") or {}
            alert = r.get("alert") or {}
            ch = _html.escape(str(msg.get("channel") or "unknown"))
            src = _html.escape(str(msg.get("source") or "unknown"))
            ts = _html.escape(str((msg.get("created_at") or "")[:19]))
            risk = alert.get("risk_level") or "UNFLAGGED"
            sc = float(alert.get("score") or 0.0)
            cats = ", ".join(alert.get("categories") or []) or "none"
            prov = _html.escape(str(msg.get("provenance_status") or "not_recorded"))
            ev_h = msg.get("evidence_hash")
            prov_str = f"Provenance: <b>{prov}</b>" + (f" | SHA-256: <font face='Courier'>{str(ev_h)[:16]}...</font>" if ev_h else "")
            linked_str = ", ".join(
                f"{lk.get('type')}: {lk.get('value')}"
                for lk in (r.get("linked_identifiers") or [])[:6]
            )
            txt = _html.escape((msg.get("text") or "[no text]").replace("\n", " ")[:500])
            risk_color = "#dc2626" if risk == "HIGH" else ("#d97706" if risk == "MEDIUM" else "#64748b")

            card = [
                Paragraph(
                    f"<b>EVIDENCE #{idx}</b> — @{ch} ({src}) | "
                    f"<font color='{risk_color}'><b>{risk} ({sc*100:.0f}%)</b></font> | {ts}",
                    styles["MetaLabel"],
                ),
                Spacer(1, 2),
                Paragraph(
                    f"Matched: <b>{_html.escape(str(ident.get('type')))} = {_html.escape(str(ident.get('value')))}</b> | "
                    f"Categories: <b>{_html.escape(cats)}</b>",
                    styles["Body"],
                ),
                Paragraph(prov_str, styles["MetaLabel"]),
            ]
            if linked_str:
                card.append(Paragraph(f"Linked Identifiers: {_html.escape(linked_str)}", styles["MetaLabel"]))
            card.extend([
                Spacer(1, 2),
                Paragraph(f"\"{txt}\"", styles["MsgTranscript"]),
            ])
            t_card = Table([[card]], colWidths=[515])
            t_card.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
                    ("LINELEFT", (0, 0), (0, 0), 3, colors.HexColor(risk_color)),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(KeepTogether(t_card))
            story.append(Spacer(1, 5))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


