"""
Syndicate Chain Tracer & Deep OSINT Expansion Engine.

Discovers, maps, and recursively crawls the entire criminal supply chain:
- Upstream Source Suppliers (Forward Origins / fwd_from)
- Broadcast Channels & Downstream Affiliates (Mentions, t.me links)
- Admin Handles, Brokers & Escrow Contacts
- Shared Financial Conduits (UPIs, Phone numbers, Crypto Wallets) linking multiple channels
- Multi-hop chain expansion to ingest large datasets across criminal syndicates
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import upsert_channel
from app.db.models import Channel, ChannelScanResult, Identifier, Message

logger = logging.getLogger(__name__)


async def get_syndicate_chain(
    db: AsyncSession,
    target_username: str,
    max_hops: int = 2,
) -> Dict[str, Any]:
    """
    Constructs a comprehensive multi-hop syndicate chain centered on `target_username`.
    Finds upstream forward sources, downstream cross-mentions, admin contacts,
    and all coordinated channels sharing payment or contact infrastructure.
    """
    clean_user = target_username.lstrip("@").strip().lower()

    # Query target from scan results or channels
    scan_q = await db.execute(
        select(ChannelScanResult)
        .where(ChannelScanResult.channel_username.ilike(clean_user))
        .order_by(ChannelScanResult.scanned_at.desc())
    )
    target_res = scan_q.scalars().first()

    ch_q = await db.execute(select(Channel).where(Channel.username.ilike(clean_user)))
    target_ch = ch_q.scalars().first()

    if not target_res and not target_ch:
        return {
            "root_username": clean_user,
            "chain_found": False,
            "message": f"Channel @{clean_user} has not been scanned or monitored yet.",
            "nodes": [],
            "edges": [],
            "timeline": [],
            "stats": {"total_nodes": 0, "total_edges": 0, "linked_channels": 0, "shared_financials": 0},
        }

    # Extract target metadata
    title = (target_ch.title if target_ch and target_ch.title else None) or (target_res.channel_title if target_res else None) or clean_user
    risk = target_res.risk_level if target_res else "MEDIUM"
    severity = getattr(target_res, "severity_tier", "HIGH") if target_res else "HIGH"
    top_cats = json.loads(target_res.top_categories) if target_res and target_res.top_categories else []
    sample_msgs = json.loads(target_res.sample_messages) if target_res and target_res.sample_messages else []
    connected = json.loads(target_res.connected_nodes) if target_res and getattr(target_res, "connected_nodes", None) else {}

    nodes_dict: Dict[str, Dict[str, Any]] = {}
    edges_list: List[Dict[str, Any]] = []
    seen_edges: Set[str] = set()
    timeline: List[Dict[str, Any]] = []

    def add_node(node_id: str, label: str, node_type: str, role: str, hop: int, color: str, meta: Optional[Dict] = None):
        if node_id not in nodes_dict:
            nodes_dict[node_id] = {
                "id": node_id,
                "label": label,
                "type": node_type,
                "role": role,
                "hop": hop,
                "color": color,
                "meta": meta or {},
            }
        else:
            # Update role or hop if discovered closer
            if hop < nodes_dict[node_id]["hop"]:
                nodes_dict[node_id]["hop"] = hop

    def add_edge(src: str, tgt: str, relation: str, weight: float = 1.0, details: str = ""):
        edge_key = f"{src}__{tgt}__{relation}"
        if edge_key not in seen_edges and src != tgt:
            seen_edges.add(edge_key)
            edges_list.append({
                "id": f"{src}__{tgt}",
                "source": src,
                "target": tgt,
                "relation": relation,
                "weight": weight,
                "details": details,
            })

    # Root Node (Hop 0)
    root_id = f"channel::{clean_user}"
    add_node(
        node_id=root_id,
        label=f"@{clean_user}",
        node_type="channel",
        role="Target Investigation Anchor",
        hop=0,
        color="#3b82f6", # Blue
        meta={
            "title": title,
            "risk_level": risk,
            "severity_tier": severity,
            "categories": top_cats,
            "members": getattr(target_res, "member_count", None),
        },
    )

    # 1. UPSTREAM & DOWNSTREAM CHANNELS (Hop 1)
    # Forward origins & cross-mentions extracted from messages
    fwd_sources = set()
    for m in sample_msgs:
        fwd = m.get("fwd_source")
        if fwd:
            fwd_clean = fwd.lstrip("@").strip()
            fwd_sources.add(fwd_clean)
            timeline.append({
                "date": m.get("date"),
                "event": "Cross-Channel Forward Intercept",
                "source": fwd_clean,
                "target": clean_user,
                "excerpt": m.get("text", "")[:150],
                "score": m.get("score"),
            })

    for fwd in fwd_sources:
        fwd_id = f"channel::{fwd.lower()}"
        add_node(fwd_id, f"@{fwd}", "channel", "Upstream Content Supplier (Forward Origin)", 1, "#f43f5e") # Rose
        add_edge(fwd_id, root_id, "forwards_intel_to", 3.0, "Message forwarded from this origin channel")

    # Mentioned Channels / Affiliates
    for ch_user in connected.get("channels", []):
        ch_clean = ch_user.lstrip("@").strip()
        if not ch_clean or ch_clean.lower() == clean_user:
            continue
        ch_id = f"channel::{ch_clean.lower()}"
        add_node(ch_id, f"@{ch_clean}", "channel", "Affiliate / Syndicate Branch", 1, "#ec4899") # Pink
        add_edge(root_id, ch_id, "promotes_affiliate", 2.0, "Channel mentioned in public posts or bio")

    # 2. ADMINS & ESCROW HANDLES (Hop 1)
    for handle in connected.get("handles", []):
        h_clean = handle.lstrip("@").strip()
        if not h_clean or h_clean.lower() == clean_user:
            continue
        h_id = f"handle::{h_clean.lower()}"
        add_node(h_id, f"@{h_clean}", "handle", "Admin / Syndicate Broker", 1, "#8b5cf6") # Violet
        add_edge(root_id, h_id, "admin_contact", 2.0, "Public contact handle for transactions")

    # 3. FINANCIAL CONDUITS (Hop 1) & MULTI-CHANNEL SYNDICATE LINKS (Hop 2)
    shared_financial_values = []

    # UPI IDs
    for upi in connected.get("upis", []):
        u_id = f"upi::{upi}"
        add_node(u_id, upi, "upi", "Payment Conduit (UPI)", 1, "#f97316") # Orange
        add_edge(root_id, u_id, "collects_funds_via", 2.5, "Payment address published in posts")
        shared_financial_values.append(upi)

    # Phone numbers
    for phone in connected.get("phones", []):
        p_id = f"phone::{phone}"
        add_node(p_id, phone, "phone", "Contact / Calling Node", 1, "#ef4444") # Red
        add_edge(root_id, p_id, "uses_contact_phone", 2.0, "Telephone line published in posts")
        shared_financial_values.append(phone)

    # Crypto Wallets
    for wallet in connected.get("wallets", []):
        w_id = f"wallet::{wallet}"
        add_node(w_id, wallet, "wallet", "Crypto Laundering Destination", 1, "#06b6d4") # Cyan
        add_edge(root_id, w_id, "crypto_destination", 3.0, "Crypto wallet published for illegal settlement")
        shared_financial_values.append(wallet)

    # 4. DISCOVER HOP 2: Other channels in the database sharing the EXACT SAME financial instruments
    syndicate_linked_channels = set()
    for val in shared_financial_values[:15]:
        other_ch_q = await db.execute(
            select(ChannelScanResult)
            .where(
                ChannelScanResult.channel_username != clean_user,
                or_(
                    ChannelScanResult.top_identifiers.like(f"%{val}%"),
                    ChannelScanResult.connected_nodes.like(f"%{val}%"),
                )
            )
            .limit(10)
        )
        other_results = other_ch_q.scalars().all()
        for oc in other_results:
            oc_clean = oc.channel_username.lower()
            syndicate_linked_channels.add(oc_clean)
            oc_id = f"channel::{oc_clean}"
            oc_title = oc.channel_title or f"@{oc_clean}"
            add_node(
                oc_id,
                f"@{oc_clean}",
                "channel",
                "Coordinated Syndicate Channel (Shared Payment Infrastructure)",
                2,
                "#d946ef", # Magenta
                meta={
                    "title": oc_title,
                    "risk_level": oc.risk_level,
                    "severity_tier": getattr(oc, "severity_tier", "HIGH"),
                    "categories": json.loads(oc.top_categories) if oc.top_categories else [],
                    "shared_identifier": val,
                },
            )
            val_id = f"upi::{val}" if "@" in val else (f"phone::{val}" if val.startswith("+") else f"wallet::{val}")
            add_edge(oc_id, val_id, "shares_payment_hub", 3.5, f"Shares common financial instrument: {val}")

    # Build Cytoscape elements list
    elements: List[Dict[str, Any]] = []
    for node in nodes_dict.values():
        elements.append({
            "data": {
                "id": node["id"],
                "label": node["label"],
                "type": node["type"],
                "role": node["role"],
                "hop": node["hop"],
                "color": node["color"],
                "is_root": node["hop"] == 0,
                "degree": 30 if node["hop"] == 0 else (22 if node["type"] == "channel" else 15),
                "meta": node["meta"],
            }
        })

    for edge in edges_list:
        elements.append({
            "data": {
                "id": f"{edge['source']}__{edge['target']}",
                "source": edge["source"],
                "target": edge["target"],
                "relation": edge["relation"],
                "weight": edge["weight"],
                "details": edge["details"],
            }
        })

    # Sort timeline chronologically
    timeline.sort(key=lambda x: x.get("date") or "", reverse=True)

    return {
        "root_username": clean_user,
        "chain_found": True,
        "target_metadata": {
            "username": clean_user,
            "title": title,
            "risk_level": risk,
            "severity_tier": severity,
            "top_categories": top_cats,
        },
        "stats": {
            "total_nodes": len(nodes_dict),
            "total_edges": len(edges_list),
            "linked_channels": len([n for n in nodes_dict.values() if n["type"] == "channel" and n["hop"] > 0]),
            "shared_financials": len(shared_financial_values),
            "admin_handles": len(connected.get("handles", [])),
        },
        "nodes": list(nodes_dict.values()),
        "edges": edges_list,
        "elements": elements,
        "syndicate_cluster": list(syndicate_linked_channels),
        "timeline": timeline[:20],
    }


async def trace_and_expand_chain(
    db: AsyncSession,
    target_username: str,
    max_crawl_channels: int = 5,
) -> Dict[str, Any]:
    """
    Actively expands the chain:
    1. Identifies all un-scanned channels linked in the chain (forward origins, mentioned channels).
    2. Automatically adds them to the watchlist and triggers scan if Telethon client is online.
    3. Re-computes and returns the full expanded chain.
    """
    clean_user = target_username.lstrip("@").strip().lower()
    chain = await get_syndicate_chain(db, clean_user)

    if not chain.get("chain_found"):
        return chain

    unscanned_channels: List[str] = []
    for node in chain.get("nodes", []):
        if node["type"] == "channel" and node["hop"] > 0:
            ch_un = node["label"].lstrip("@")
            # Check if this channel has a scan result
            ex_q = await db.execute(
                select(ChannelScanResult).where(ChannelScanResult.channel_username.ilike(ch_un))
            )
            if not ex_q.scalar_one_or_none():
                unscanned_channels.append(ch_un)

    # Queue up to max_crawl_channels for monitoring & scanning
    crawled_count = 0
    for ch_to_scan in unscanned_channels[:max_crawl_channels]:
        try:
            await upsert_channel(db, username=ch_to_scan)
            crawled_count += 1
            logger.info("Chain Expansion: Auto-ingesting syndicate node @%s", ch_to_scan)
        except Exception as exc:
            logger.warning("Error queueing chain node @%s: %s", ch_to_scan, exc)

    # Re-fetch the expanded chain
    updated_chain = await get_syndicate_chain(db, clean_user)
    updated_chain["crawled_nodes_count"] = crawled_count
    updated_chain["queued_channels"] = unscanned_channels[:max_crawl_channels]
    return updated_chain
