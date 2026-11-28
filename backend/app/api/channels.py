"""
Channel management, deep intelligence & network graph endpoints.

POST /channels                 Add a channel to the watchlist
GET  /channels                 List all channels
DELETE /channels/{id}          Deactivate a channel
GET  /channels/{id}/details    Deep intelligence profile & history
GET  /channels/{id}/network    Connecting nodes & syndicate network
GET  /channels/{id}/export/pdf Export PDF intelligence dossier
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.crud import get_active_channels, upsert_channel
from app.db.database import get_db
from app.db.models import Alert, Channel, ChannelScanResult, Identifier, Message
from app.reports.pdf_generator import generate_channel_dossier_pdf
from app.services.retention_service import require_api_token, write_audit_log

router = APIRouter(prefix="/channels", tags=["channels"])


class ChannelCreate(BaseModel):
    username: str  # e.g. "some_public_channel" (without @)


class ChannelOut(BaseModel):
    id: int
    username: str
    title: Optional[str] = None
    description: Optional[str] = None
    telegram_id: Optional[int] = None
    member_count: Optional[int] = None
    is_verified: bool = False
    is_scam: bool = False
    invite_link: Optional[str] = None
    is_active: bool = True
    last_fetched_at: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    channel_status: Optional[str] = None

    model_config = {"from_attributes": True}


@router.post("/", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(
    payload: ChannelCreate,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    username = payload.username.lstrip("@").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Invalid username")
    channel = await upsert_channel(db, username=username)
    return channel


@router.get("/", response_model=List[ChannelOut])
async def list_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Channel).order_by(Channel.added_at.desc()))
    return result.scalars().all()


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_channel(
    channel_id: int,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    channel.is_active = False


async def _resolve_channel(identifier: str, db: AsyncSession):
    """Find channel by ID or username from Channel or ChannelScanResult."""
    clean_id = identifier.lstrip("@").strip()
    ch = None
    scan_res = None

    if clean_id.isdigit():
        ch_res = await db.execute(select(Channel).where(Channel.id == int(clean_id)))
        ch = ch_res.scalar_one_or_none()
        if not ch:
            scan_q = await db.execute(select(ChannelScanResult).where(ChannelScanResult.id == int(clean_id)))
            scan_res = scan_q.scalar_one_or_none()

    if not ch and not scan_res:
        ch_res = await db.execute(select(Channel).where(Channel.username.ilike(clean_id)))
        ch = ch_res.scalar_one_or_none()

    if not scan_res:
        target_user = ch.username if ch else clean_id
        # A channel may have MULTIPLE scan-result rows (re-scans) — always
        # take the latest one instead of raising MultipleResultsFound.
        scan_q = await db.execute(
            select(ChannelScanResult)
            .where(ChannelScanResult.channel_username.ilike(target_user))
            .order_by(ChannelScanResult.scanned_at.desc())
            .limit(1)
        )
        scan_res = scan_q.scalars().first()

    if not ch and not scan_res:
        raise HTTPException(status_code=404, detail=f"Channel @{clean_id} not found")

    return ch, scan_res


@router.get("/{identifier}/details")
async def get_channel_details(
    identifier: str,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Fetch complete forensic profile and threat details for a target channel."""
    ch, scan_res = await _resolve_channel(identifier, db)

    username = ch.username if ch else scan_res.channel_username
    title = (ch.title if ch and ch.title else None) or (scan_res.channel_title if scan_res else None) or username
    desc = (ch.description if ch and ch.description else None) or (getattr(scan_res, "channel_description", None) if scan_res else None)
    tg_id = (ch.telegram_id if ch else None) or (scan_res.telegram_id if scan_res else None)
    members = (ch.member_count if ch and ch.member_count else None) or (scan_res.member_count if scan_res else None)
    is_ver = (ch.is_verified if ch else False) or (getattr(scan_res, "is_verified", False) if scan_res else False)
    is_scam = (ch.is_scam if ch else False) or (getattr(scan_res, "is_scam", False) if scan_res else False)
    invite = (ch.invite_link if ch and ch.invite_link else None) or (getattr(scan_res, "invite_link", None) if scan_res else None) or f"https://t.me/{username}"

    # Stats
    risk_level = scan_res.risk_level if scan_res else "LOW"
    avg_score = scan_res.avg_score if scan_res else 0.0
    messages_scanned = scan_res.messages_scanned if scan_res else 0
    flagged_count = scan_res.flagged_count if scan_res else 0
    high_count = scan_res.high_count if scan_res else 0
    medium_count = scan_res.medium_count if scan_res else 0

    top_categories = json.loads(scan_res.top_categories) if (scan_res and scan_res.top_categories) else []
    top_identifiers = json.loads(scan_res.top_identifiers) if (scan_res and scan_res.top_identifiers) else []
    sample_messages = json.loads(scan_res.sample_messages) if (scan_res and scan_res.sample_messages) else []
    connected_nodes = json.loads(scan_res.connected_nodes) if (scan_res and getattr(scan_res, "connected_nodes", None)) else {}

    # If it's a monitored / imported channel, populate live stats, composite score,
    # identifiers, sample messages, and connected nodes from Message/Alert/Identifier.
    score_components = None
    if ch:
        from collections import Counter
        from sqlalchemy import func
        from sqlalchemy.orm import selectinload
        from app.extractors.identifier_extractor import CONTACT_TYPES
        from app.services.evidence_hashing import provenance_note_for_status
        from app.services.scoring_service import compute_composite_score

        msg_total = (
            await db.execute(select(func.count(Message.id)).where(Message.channel_id == ch.id))
        ).scalar_one() or 0
        if msg_total > messages_scanned:
            messages_scanned = msg_total

        live_alerts_res = await db.execute(
            select(Alert)
            .options(selectinload(Alert.message).selectinload(Message.identifiers))
            .join(Message)
            .where(Message.channel_id == ch.id)
            .order_by(Alert.score.desc())
        )
        live_alerts = live_alerts_res.scalars().all()
        if live_alerts:
            if not scan_res:
                flagged_count = len(live_alerts)
                high_count = sum(1 for a in live_alerts if a.risk_level == "HIGH")
                medium_count = sum(1 for a in live_alerts if a.risk_level == "MEDIUM")
                risk_level = "HIGH" if high_count > 0 else ("MEDIUM" if medium_count > 0 else "LOW")

            ev_list = []
            cat_counts: Counter = Counter()
            confirmed_count = 0
            for a in live_alerts:
                ev = json.loads(a.evidence) if a.evidence else {}
                sev = ev.get("severity_tier") or ("P1" if a.risk_level == "HIGH" else "P3")
                ev_list.append({
                    "classifier_score": float(a.score or 0.0),
                    "risk_level": (a.risk_level or "low").lower(),
                    "severity_tier": sev,
                    "message_timestamp": a.message.created_at if a.message else a.created_at,
                })
                if getattr(a, "disposition", None) in ("confirmed_threat", "escalated"):
                    confirmed_count += 1
                for c in (a.categories or "").split(","):
                    c_clean = c.strip()
                    if c_clean:
                        cat_counts[c_clean] += 1
            distinct_contact_idents = {
                (it.type, it.normalised)
                for a in live_alerts
                if a.message
                for it in (a.message.identifiers or [])
                if it.type in CONTACT_TYPES and it.normalised
            }
            analyst_sig = 1.0 if confirmed_count > 0 else (0.5 if any(a.is_reviewed for a in live_alerts) else 0.0)
            score_components = compute_composite_score(
                ev_list,
                valid_pivot_count=len(distinct_contact_idents),
                analyst_signal=analyst_sig,
            )
            effective_score = float(score_components["composite_score"])
            if high_count > 0:
                alert_avg = sum(float(a.score or 0.0) for a in live_alerts) / len(live_alerts)
                effective_score = max(effective_score, round(alert_avg, 4))
                if score_components["max_message_score"] >= 0.85 or high_count >= 2:
                    effective_score = max(effective_score, 0.75)
            score_components["composite_score"] = round(effective_score, 4)
            if avg_score <= 0.0 or effective_score > avg_score:
                avg_score = round(effective_score, 4)
            if not top_categories and cat_counts:
                top_categories = [c for c, _ in cat_counts.most_common(6)]

            if not sample_messages:
                for a in live_alerts[:40]:
                    m = a.message
                    if not m:
                        continue
                    ev = json.loads(a.evidence) if a.evidence else {}
                    matched_terms = [
                        t.get("term") for t in ev.get("matched_terms", [])
                        if isinstance(t, dict) and t.get("term")
                    ]
                    display_text = (m.text or "").strip() or (f"[OCR] {m.ocr_text}" if m.ocr_text else "")
                    sample_messages.append({
                        "id": m.telegram_msg_id,
                        "date": m.created_at.isoformat() if m.created_at else None,
                        "text": display_text,
                        "score": round(float(a.score or 0.0), 4),
                        "categories": [c.strip() for c in (a.categories or "").split(",") if c.strip()],
                        "risk_level": a.risk_level,
                        "matched_terms": matched_terms,
                        "provenance_status": m.provenance_status,
                        "evidence_hash": m.evidence_hash,
                        "provenance_note": provenance_note_for_status(m.provenance_status),
                        # police-dossier enrichment
                        "ocr_text": m.ocr_text,
                        "media_hash": m.media_hash,
                        "phash": getattr(m, "image_phash", None),
                        "identifiers": [
                            {"type": it.type, "value": it.value}
                            for it in (m.identifiers or [])
                        ],
                    })

        # Populate identifiers and connected nodes from Identifier table when missing
        ident_rows = (
            await db.execute(
                select(Identifier.type, Identifier.value, Identifier.normalised)
                .join(Message, Message.id == Identifier.message_id)
                .where(Message.channel_id == ch.id)
            )
        ).all()
        if ident_rows and not top_identifiers:
            seen_ident = set()
            ident_freq: Counter = Counter()
            for itype, ival, inorm in ident_rows:
                if itype in CONTACT_TYPES:
                    ident_freq[(itype, inorm or ival)] += 1
                    seen_ident.add((itype, inorm or ival))
            top_identifiers = [
                {"type": t, "value": v}
                for (t, v), _ in ident_freq.most_common(25)
            ]
        if ident_rows and not connected_nodes:
            cn: Dict[str, set] = {
                "handles": set(), "phones": set(), "upis": set(),
                "wallets": set(), "urls": set(), "channels": set(),
            }
            norms_for_link = set()
            for itype, ival, inorm in ident_rows:
                val = inorm or ival
                if itype == "handle":
                    cn["handles"].add(val)
                elif itype == "phone":
                    cn["phones"].add(val)
                elif itype == "upi":
                    cn["upis"].add(val)
                elif itype.startswith("wallet"):
                    cn["wallets"].add(val)
                elif itype in ("url", "site"):
                    cn["urls"].add(val)
                if itype in CONTACT_TYPES and val:
                    norms_for_link.add(val)
            if norms_for_link:
                shared_chs = (
                    await db.execute(
                        select(Channel.username)
                        .join(Message, Message.channel_id == Channel.id)
                        .join(Identifier, Identifier.message_id == Message.id)
                        .where(Channel.id != ch.id, Identifier.normalised.in_(list(norms_for_link)))
                        .distinct()
                    )
                ).scalars().all()
                cn["channels"].update(shared_chs)
            connected_nodes = {k: sorted(v) for k, v in cn.items() if v}

    # Enrich sample_messages with Message provenance status/hash where available
    if sample_messages and ch:
        from app.services.evidence_hashing import provenance_note_for_status

        msg_ids = [m.get("id") for m in sample_messages if isinstance(m, dict) and m.get("id") is not None]
        if msg_ids:
            prov_rows = (
                await db.execute(
                    select(Message.telegram_msg_id, Message.provenance_status, Message.evidence_hash)
                    .where(Message.channel_id == ch.id, Message.telegram_msg_id.in_(msg_ids))
                )
            ).all()
            prov_map = {r[0]: (r[1], r[2]) for r in prov_rows}
            for m in sample_messages:
                if isinstance(m, dict) and m.get("id") in prov_map:
                    p_stat, e_hash = prov_map[m["id"]]
                    m["provenance_status"] = p_stat
                    m["evidence_hash"] = e_hash
                    m["provenance_note"] = provenance_note_for_status(p_stat)

    # Cross-channel correlation: identifiers ALSO used by other monitored
    # channels, and identical posts reproduced elsewhere (coordinated posting).
    identifier_correlations: List[Dict[str, Any]] = []
    cross_channel_campaigns: List[Dict[str, Any]] = []
    if ch:
        from app.extractors.identifier_extractor import CONTACT_TYPES as _CT
        own_idents = (
            await db.execute(
                select(Identifier.normalised, Identifier.type)
                .join(Message, Message.id == Identifier.message_id)
                .where(Message.channel_id == ch.id)
                .distinct()
            )
        ).all()
        own_list = [(n, t) for n, t in own_idents if t in _CT and n]
        if own_list:
            norms = [n for n, _t in own_list]
            corr_rows = (
                await db.execute(
                    select(Identifier.normalised, Channel.username)
                    .join(Message, Message.id == Identifier.message_id)
                    .join(Channel, Channel.id == Message.channel_id)
                    .where(Identifier.normalised.in_(norms), Message.channel_id != ch.id)
                    .distinct()
                )
            ).all()
            corr_map: Dict[str, set] = {}
            for norm, other_uname in corr_rows:
                corr_map.setdefault(norm, set()).add(other_uname)
            type_map = {n: t for n, t in own_list}
            identifier_correlations = [
                {"identifier": n, "type": type_map.get(n, ""), "other_channels": sorted(chs)}
                for n, chs in corr_map.items()
            ]
            identifier_correlations.sort(key=lambda c: -len(c["other_channels"]))
            identifier_correlations = identifier_correlations[:15]

        own_hashes = (
            await db.execute(
                select(Message.original_text_hash)
                .join(Alert, Alert.message_id == Message.id)
                .where(Message.channel_id == ch.id, Message.original_text_hash.is_not(None))
            )
        ).all()
        hash_list = [h for (h,) in own_hashes]
        if hash_list:
            camp_rows = (
                await db.execute(
                    select(Message.original_text_hash, Channel.username, Message.created_at)
                    .join(Message, Message.channel_id == Channel.id)
                    .where(Message.original_text_hash.in_(hash_list), Message.channel_id != ch.id)
                    .order_by(Message.created_at)
                )
            ).all()
            camp_map: Dict[str, List[Dict[str, Any]]] = {}
            for h, uname, cdt in camp_rows:
                camp_map.setdefault(h, []).append(
                    {"channel": uname, "date": cdt.isoformat() if cdt else None}
                )
            if camp_map:
                excerpt_rows = (
                    await db.execute(
                        select(Message.original_text_hash, Message.text)
                        .where(Message.channel_id == ch.id, Message.original_text_hash.in_(list(camp_map)))
                    )
                ).all()
                excerpts = {h: (t or "") for h, t in excerpt_rows}
                cross_channel_campaigns = [
                    {
                        "excerpt": excerpts.get(h, "")[:160],
                        "other_postings": camp_map[h][:12],
                    }
                    for h in camp_map
                ][:10]

    return {
        "channel_id": ch.id if ch else None,
        "scan_result_id": scan_res.id if scan_res else None,
        "username": username,
        "title": title,
        "description": desc,
        "telegram_id": tg_id,
        "member_count": members,
        "is_verified": is_ver,
        "is_scam": is_scam,
        "invite_link": invite,
        "is_monitored": ch.is_active if ch else False,
        "risk_level": risk_level,
        "avg_score": avg_score,
        "score_components": score_components,
        "messages_scanned": messages_scanned,
        "flagged_count": flagged_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "top_categories": top_categories,
        "top_identifiers": top_identifiers,
        "sample_messages": sample_messages,
        "connected_nodes": connected_nodes,
        "identifier_correlations": identifier_correlations,
        "cross_channel_campaigns": cross_channel_campaigns,
    }


@router.get("/{identifier}/network")
async def get_channel_network(
    identifier: str,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Constructs an interactive Cytoscape ego-network graph showing all connecting
    nodes (forwarded sources, mentioned channels, admins, phones, UPIs, crypto wallets)
    as well as syndicate linkages (other channels sharing these identifiers).
    """
    ch, scan_res = await _resolve_channel(identifier, db)
    username = ch.username if ch else scan_res.channel_username
    title = (ch.title if ch and ch.title else None) or (scan_res.channel_title if scan_res else None) or username

    # Color definitions
    colors = {
        "root_channel": "#3b82f6",     # Blue
        "syndicate_ch": "#ec4899",     # Pink (connected channel)
        "phone": "#ef4444",            # Red
        "upi": "#f97316",              # Orange
        "handle": "#8b5cf6",           # Violet (admin/contact)
        "wallet": "#06b6d4",           # Cyan (crypto)
        "url": "#64748b",              # Slate
    }

    elements: List[Dict[str, Any]] = []
    root_node_id = f"channel::{username.lower()}"

    # Central Root Node
    elements.append({
        "data": {
            "id": root_node_id,
            "label": f"@{username}",
            "sublabel": title[:20],
            "type": "channel",
            "is_root": True,
            "color": colors["root_channel"],
            "degree": 30,
        }
    })

    connected_nodes = json.loads(scan_res.connected_nodes) if (scan_res and getattr(scan_res, "connected_nodes", None)) else {}
    top_identifiers = json.loads(scan_res.top_identifiers) if (scan_res and scan_res.top_identifiers) else []

    if ch and not top_identifiers:
        from app.extractors.identifier_extractor import CONTACT_TYPES
        ident_rows = (
            await db.execute(
                select(Identifier.type, Identifier.normalised)
                .join(Message, Message.id == Identifier.message_id)
                .where(Message.channel_id == ch.id)
                .distinct()
            )
        ).all()
        top_identifiers = [{"type": t, "value": v} for t, v in ident_rows if t in CONTACT_TYPES and v][:30]
        if not connected_nodes:
            connected_nodes = {
                "handles": [v for t, v in ident_rows if t == "handle" and v][:15],
                "phones": [v for t, v in ident_rows if t == "phone" and v][:15],
                "upis": [v for t, v in ident_rows if t == "upi" and v][:15],
                "wallets": [v for t, v in ident_rows if t.startswith("wallet") and v][:15],
                "channels": [],
            }

    added_nodes = {root_node_id}
    added_edges = set()

    def add_edge(src: str, tgt: str, rel: str, weight: float = 1.0):
        edge_key = f"{src}__{tgt}"
        if edge_key not in added_edges and src != tgt:
            added_edges.add(edge_key)
            elements.append({
                "data": {
                    "id": edge_key,
                    "source": src,
                    "target": tgt,
                    "relationship": rel,
                    "weight": weight,
                }
            })

    # 1. Connected Channels (Mentioned / Forwarded)
    for c_user in connected_nodes.get("channels", []):
        c_clean = c_user.lstrip("@").strip()
        if not c_clean:
            continue
        c_id = f"channel::{c_clean.lower()}"
        if c_id not in added_nodes:
            added_nodes.add(c_id)
            elements.append({
                "data": {
                    "id": c_id,
                    "label": f"@{c_clean}",
                    "type": "channel",
                    "color": colors["syndicate_ch"],
                    "degree": 18,
                }
            })
        add_edge(root_node_id, c_id, "mentions_channel", 2.0)

    # 2. Handles (Admins / Contacts)
    for handle in connected_nodes.get("handles", []):
        h_clean = handle.lstrip("@").strip()
        if not h_clean:
            continue
        h_id = f"handle::{h_clean.lower()}"
        if h_id not in added_nodes:
            added_nodes.add(h_id)
            elements.append({
                "data": {
                    "id": h_id,
                    "label": f"@{h_clean}",
                    "type": "handle",
                    "color": colors["handle"],
                    "degree": 15,
                }
            })
        add_edge(root_node_id, h_id, "contact_admin", 1.5)

    # 3. Financial Instruments (UPIs, Phones, Wallets)
    for item in top_identifiers:
        itype = item.get("type", "unknown")
        ival = item.get("value", "")
        if not ival:
            continue
        color_key = "wallet" if "wallet" in itype else (itype if itype in colors else "url")
        node_id = f"{itype}::{ival}"
        if node_id not in added_nodes:
            added_nodes.add(node_id)
            elements.append({
                "data": {
                    "id": node_id,
                    "label": ival[:24] + ("…" if len(ival) > 24 else ""),
                    "full_value": ival,
                    "type": itype,
                    "color": colors.get(color_key, "#94a3b8"),
                    "degree": 14,
                }
            })
        add_edge(root_node_id, node_id, f"uses_{itype}", 1.5)

        # 4. Find Syndicate links: other channels in Channel/Identifier OR scan_results sharing this identifier!
        other_db_chs = (
            await db.execute(
                select(Channel.username, Channel.title)
                .join(Message, Message.channel_id == Channel.id)
                .join(Identifier, Identifier.message_id == Message.id)
                .where(Channel.username != username, Identifier.normalised == ival)
                .distinct()
                .limit(8)
            )
        ).all()
        for o_uname, o_title in other_db_chs:
            other_id = f"channel::{o_uname.lower()}"
            if other_id not in added_nodes:
                added_nodes.add(other_id)
                elements.append({
                    "data": {
                        "id": other_id,
                        "label": f"@{o_uname}",
                        "sublabel": (o_title or "")[:20],
                        "type": "channel",
                        "color": colors["syndicate_ch"],
                        "degree": 20,
                    }
                })
            add_edge(node_id, other_id, "shared_identifier", 2.0)

        other_results = await db.execute(
            select(ChannelScanResult)
            .where(
                ChannelScanResult.channel_username != username,
                ChannelScanResult.top_identifiers.like(f"%{ival}%"),
            )
            .limit(5)
        )
        for other_ch in other_results.scalars().all():
            other_id = f"channel::{other_ch.channel_username.lower()}"
            if other_id not in added_nodes:
                added_nodes.add(other_id)
                elements.append({
                    "data": {
                        "id": other_id,
                        "label": f"@{other_ch.channel_username}",
                        "sublabel": (other_ch.channel_title or "")[:20],
                        "type": "channel",
                        "color": colors["syndicate_ch"],
                        "degree": 20,
                    }
                })
            add_edge(node_id, other_id, "shared_payment_entity", 3.0)

    return {
        "root_username": username,
        "node_count": len(elements) - len(added_edges),
        "edge_count": len(added_edges),
        "elements": elements,
        "categories": {
            "channels": connected_nodes.get("channels", []),
            "handles": connected_nodes.get("handles", []),
            "upis": connected_nodes.get("upis", []),
            "phones": connected_nodes.get("phones", []),
            "wallets": connected_nodes.get("wallets", []),
        },
    }


@router.get("/{identifier}/export/pdf")
async def export_channel_pdf(
    identifier: str,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Generate and export a complete PDF intelligence dossier for this channel."""
    ch, scan_res = await _resolve_channel(identifier, db)
    username = ch.username if ch else scan_res.channel_username

    details = await get_channel_details(identifier, _actor=actor, db=db)
    pdf_bytes = generate_channel_dossier_pdf(details)
    await write_audit_log(db, actor=actor, action="pdf_export", target_type="channel", details={"channel": username})
    await db.commit()

    filename = f"telemonitor_{__import__('re').sub(r'[^A-Za-z0-9_-]', '_', username)[:48]}_dossier.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{identifier}/chain")
async def get_channel_chain(
    identifier: str,
    max_hops: int = Query(2, ge=1, le=4),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the complete multi-hop syndicate chain around this channel:
    upstream forward sources, cross-mentions, admin handles, and shared payment hubs.
    """
    from app.graph.chain_tracer import get_syndicate_chain
    clean_id = identifier.lstrip("@").strip()
    return await get_syndicate_chain(db, clean_id, max_hops=max_hops)


@router.post("/{identifier}/trace-chain")
async def trace_and_expand_channel_chain(
    identifier: str,
    max_crawl: int = Query(5, ge=1, le=15),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Actively expand the syndicate chain by discovering and queueing
    linked unscanned channels for ingestion, pulling massive amounts of structured intel.
    """
    from app.graph.chain_tracer import trace_and_expand_chain
    clean_id = identifier.lstrip("@").strip()
    return await trace_and_expand_chain(db, clean_id, max_crawl_channels=max_crawl)


@router.get("/{identifier}/chain/export/pdf")
async def export_channel_chain_pdf(
    identifier: str,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Generate and export a complete Syndicate Chain Investigation Dossier in PDF format."""
    from app.graph.chain_tracer import get_syndicate_chain
    from app.reports.pdf_generator import generate_chain_investigation_pdf

    clean_id = identifier.lstrip("@").strip()
    chain = await get_syndicate_chain(db, clean_id)
    pdf_bytes = generate_chain_investigation_pdf(chain)

    filename = f"telemonitor_{__import__('re').sub(r'[^A-Za-z0-9_-]', '_', clean_id)[:48]}_syndicate_chain.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.get("/{channel_id}/health")
async def get_channel_health(channel_id: int, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Return recent health events and current status for a channel."""
    from app.db.crud import get_health_events
    from app.db.models import Channel

    result = await db.execute(select(Channel).where(Channel.id == channel_id))
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    events = await get_health_events(db, channel_id, limit=limit)

    return {
        "channel_id": channel_id,
        "channel_username": channel.username,
        "poll_tier": channel.poll_tier,
        "channel_status": channel.channel_status,
        "error_state": channel.error_state,
        "consecutive_error_count": channel.consecutive_error_count,
        "last_poll_attempted_at": channel.last_poll_attempted_at.isoformat() if channel.last_poll_attempted_at else None,
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "error_message": e.error_message,
                "occurred_at": e.occurred_at.isoformat(),
            }
            for e in events
        ],
    }


@router.patch("/{channel_id}/poll-tier")
async def set_poll_tier(
    channel_id: int,
    tier: str,
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Update the poll tier for a channel."""
    from app.services.feedback_service import update_poll_tier

    try:
        channel = await update_poll_tier(db, channel_id, tier.upper())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Reset next_poll_at so the channel is immediately re-queued at the new tier
    channel.next_poll_at = None
    await db.commit()

    return {"channel_id": channel_id, "poll_tier": channel.poll_tier}


@router.get("/{identifier}/chain/export/json")
async def export_channel_chain_json(
    identifier: str,
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Export the complete raw syndicate chain dataset in JSON for i2 / Maltego / Gephi."""
    from app.graph.chain_tracer import get_syndicate_chain

    clean_id = identifier.lstrip("@").strip()
    chain = await get_syndicate_chain(db, clean_id)
    json_bytes = json.dumps(chain, indent=2).encode("utf-8")

    filename = f"telemonitor_{clean_id}_syndicate_dataset.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


class ExpandRequest(BaseModel):
    max_hops: int = 2
    limit: int = 25
    persist: bool = False
    verify: bool = False


@router.get("/{identifier}/expand")
async def preview_channel_expansion(
    identifier: str,
    max_hops: int = Query(2, ge=1, le=3),
    limit: int = Query(25, ge=1, le=100),
    verify: bool = Query(False),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run BFS network expansion from stored channel intelligence."""
    from app.services.network_expansion import expand_channel_network

    try:
        return await expand_channel_network(
            db, identifier, max_hops=max_hops, limit=limit, persist=False, verify=verify
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{identifier}/expand")
async def expand_channel(
    identifier: str,
    payload: Optional[ExpandRequest] = None,
    max_hops: Optional[int] = Query(None, ge=1, le=3),
    limit: Optional[int] = Query(None, ge=1, le=100),
    persist: Optional[bool] = Query(None),
    verify: Optional[bool] = Query(None),
    actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    """BFS network expansion from stored data, with optional persist and Telegram verification."""
    from app.services.network_expansion import expand_channel_network

    eff_hops = max_hops if max_hops is not None else (payload.max_hops if payload else 2)
    eff_limit = limit if limit is not None else (payload.limit if payload else 25)
    eff_persist = persist if persist is not None else (payload.persist if payload else False)
    eff_verify = verify if verify is not None else (payload.verify if payload else False)

    try:
        res = await expand_channel_network(
            db,
            identifier,
            max_hops=eff_hops,
            limit=eff_limit,
            persist=eff_persist,
            verify=eff_verify,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if eff_persist:
        await write_audit_log(
            db,
            actor=actor,
            action="network_expand",
            target_type="channel",
            details={"channel": res["root_username"], "persisted": res["persisted_count"]},
        )
        await db.commit()
    return res
