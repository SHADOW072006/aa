"""
Entity graph builder and analyser.

Nodes  → unique normalised identifier values (phone, UPI, handle, wallet…)
Edges  → co-occurrence in the same message; edge weight = co-occurrence count

Provides
--------
build_graph()          Build a NetworkX graph from the database
detect_clusters()      Connected components (each = one actor / network)
get_graph_json()       Cytoscape-compatible JSON for the React frontend
get_identifier_ego()   Sub-graph centred on a single identifier (for drill-down)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import get_all_identifiers_for_graph, get_entity_links
from app.db.models import Channel, Identifier, Message
from app.extractors.identifier_extractor import CONTACT_TYPES
from app.services.minhash_service import get_minhash_index
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Risk-level colour mapping for the UI
_RISK_COLORS = {
    "phone": "#ef4444",       # red
    "upi": "#f97316",         # orange
    "handle": "#8b5cf6",      # violet
    "wallet_btc": "#eab308",  # yellow
    "wallet_eth": "#6366f1",  # indigo
    "wallet_usdt": "#06b6d4", # cyan
    "bank_account": "#f59e0b",# amber
    "site": "#ec4899",        # pink
    "channel": "#3b82f6",     # blue
    "email": "#10b981",       # emerald
    "url": "#64748b",         # slate
    "ifsc": "#a16207",        # dark amber
    "bank_card": "#dc2626",   # red-600
    "imei": "#0d9488",        # teal
    "location": "#475569",    # slate-600
}


async def build_graph(db: AsyncSession) -> nx.Graph:
    # Only actor identifiers (phone/UPI/handle/wallet/...) become graph nodes;
    # urls and locations are evidence and would fuse unrelated channels.
    identifiers = [
        ident for ident in await get_all_identifiers_for_graph(db)
        if ident.type in CONTACT_TYPES
    ]
    links = await get_entity_links(db)

    G = nx.Graph()

    id_map: Dict[int, Identifier] = {ident.id: ident for ident in identifiers}

    for ident in identifiers:
        G.add_node(
            ident.normalised,
            type=ident.type,
            raw=ident.value,
            db_id=ident.id,
            color=_RISK_COLORS.get(ident.type, "#94a3b8"),
        )

    for link in links:
        src_ident = id_map.get(link.source_id)
        tgt_ident = id_map.get(link.target_id)
        if src_ident and tgt_ident:
            reason = "shared_handle" if ("handle" in (src_ident.type, tgt_ident.type)) else "shared_identifier"
            confidence = min(1.0, 0.5 + 0.1 * (link.weight or 1))
            if G.has_edge(src_ident.normalised, tgt_ident.normalised):
                G[src_ident.normalised][tgt_ident.normalised]["weight"] += link.weight
                G[src_ident.normalised][tgt_ident.normalised]["confidence"] = min(
                    1.0, 0.5 + 0.1 * G[src_ident.normalised][tgt_ident.normalised]["weight"]
                )
            else:
                G.add_edge(
                    src_ident.normalised,
                    tgt_ident.normalised,
                    weight=link.weight,
                    reason=reason,
                    confidence=round(confidence, 3),
                )

    # Stage 5: Channel nodes + cross-channel coordination edges
    # 1) shared_identifier edges between channels (actor identifiers only)
    msg_idents = (
        await db.execute(
            select(Channel.id, Channel.username, Identifier.normalised, Identifier.type)
            .join(Message, Message.channel_id == Channel.id)
            .join(Identifier, Identifier.message_id == Message.id)
        )
    ).all()
    ident_channels: Dict[str, set] = defaultdict(set)
    ch_names: Dict[int, str] = {}
    for cid, uname, norm, itype in msg_idents:
        ch_names[cid] = uname
        if itype in CONTACT_TYPES:
            ident_channels[norm].add(cid)

    for norm, cids in ident_channels.items():
        if len(cids) > 1:
            cid_list = sorted(cids)
            for c in cid_list:
                node_id = f"ch:{ch_names[c]}"
                if not G.has_node(node_id):
                    G.add_node(node_id, type="channel", raw=ch_names[c], color="#3b82f6")
            for i in range(len(cid_list)):
                for j in range(i + 1, len(cid_list)):
                    n1 = f"ch:{ch_names[cid_list[i]]}"
                    n2 = f"ch:{ch_names[cid_list[j]]}"
                    if not G.has_edge(n1, n2):
                        G.add_edge(n1, n2, weight=1.0, reason="shared_identifier", confidence=0.85)

    # 2) near_duplicate_text edges between channels via MinHash LSH
    mh_rows = (
        await db.execute(
            select(Message.channel_id, Channel.username, Message.minhash_sig)
            .join(Channel, Channel.id == Message.channel_id)
            .where(Message.minhash_sig.is_not(None))
        )
    ).all()
    idx = get_minhash_index()
    for cid, uname, sig in mh_rows:
        ch_names[cid] = uname
        similar_cids = idx.query_similar_channels(sig, cid)
        for other_cid in similar_cids:
            other_name = ch_names.get(other_cid)
            if not other_name:
                continue
            n1, n2 = f"ch:{uname}", f"ch:{other_name}"
            if not G.has_node(n1):
                G.add_node(n1, type="channel", raw=uname, color="#3b82f6")
            if not G.has_node(n2):
                G.add_node(n2, type="channel", raw=other_name, color="#3b82f6")
            if not G.has_edge(n1, n2):
                G.add_edge(n1, n2, weight=1.0, reason="near_duplicate_text", reasons=["near_duplicate_text"], confidence=0.75)
            else:
                edge = G[n1][n2]
                reasons = set(edge.get("reasons") or ([edge["reason"]] if edge.get("reason") else []))
                reasons.add("near_duplicate_text")
                edge["reasons"] = sorted(reasons)
                edge["reason"] = ",".join(edge["reasons"])

    # 3) near_duplicate_image edges between channels via perceptual hash (phash)
    ph_rows = (
        await db.execute(
            select(Message.channel_id, Channel.username, Message.image_phash)
            .join(Channel, Channel.id == Message.channel_id)
            .where(Message.image_phash.is_not(None))
        )
    ).all()
    unique_ph: Dict[tuple[int, str], str] = {}
    for cid, uname, ph in ph_rows:
        ch_names[cid] = uname
        if ph:
            unique_ph[(cid, ph)] = uname
    ph_items = list(unique_ph.items())
    for i in range(len(ph_items)):
        (cid1, ph1), uname1 = ph_items[i]
        try:
            v1 = int(ph1, 16)
        except ValueError:
            continue
        for j in range(i + 1, len(ph_items)):
            (cid2, ph2), uname2 = ph_items[j]
            if cid1 == cid2:
                continue
            try:
                dist = (v1 ^ int(ph2, 16)).bit_count()
            except ValueError:
                continue
            if dist <= 10:
                n1, n2 = f"ch:{uname1}", f"ch:{uname2}"
                if not G.has_node(n1):
                    G.add_node(n1, type="channel", raw=uname1, color="#3b82f6")
                if not G.has_node(n2):
                    G.add_node(n2, type="channel", raw=uname2, color="#3b82f6")
                if not G.has_edge(n1, n2):
                    G.add_edge(n1, n2, weight=1.0, reason="near_duplicate_image", reasons=["near_duplicate_image"], confidence=0.85)
                else:
                    edge = G[n1][n2]
                    reasons = set(edge.get("reasons") or ([edge["reason"]] if edge.get("reason") else []))
                    reasons.add("near_duplicate_image")
                    edge["reasons"] = sorted(reasons)
                    edge["reason"] = ",".join(edge["reasons"])

    # 4) forwarded_from edges between channels
    fwd_rows = (
        await db.execute(
            select(Channel.username, Message.forwarded_from)
            .join(Message, Message.channel_id == Channel.id)
            .where(Message.forwarded_from.is_not(None))
        )
    ).all()
    for uname, fwd in fwd_rows:
        src_name = (fwd or "").strip().lstrip("@")
        if not src_name or src_name.lower() == uname.lower():
            continue
        n1, n2 = f"ch:{uname}", f"ch:{src_name}"
        if not G.has_node(n1):
            G.add_node(n1, type="channel", raw=uname, color="#3b82f6")
        if not G.has_node(n2):
            G.add_node(n2, type="channel", raw=src_name, color="#3b82f6")
        if not G.has_edge(n1, n2):
            G.add_edge(n1, n2, weight=1.0, reason="forwarded_from", reasons=["forwarded_from"], confidence=0.90)
        else:
            edge = G[n1][n2]
            reasons = set(edge.get("reasons") or ([edge["reason"]] if edge.get("reason") else []))
            reasons.add("forwarded_from")
            edge["reasons"] = sorted(reasons)
            edge["reason"] = ",".join(edge["reasons"])

    logger.debug("Graph built: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges())
    return G


def detect_clusters(G: nx.Graph) -> List[List[str]]:
    """Return connected components sorted by size descending."""
    components = sorted(nx.connected_components(G), key=len, reverse=True)
    return [list(comp) for comp in components]


def get_graph_json(G: nx.Graph, limit_nodes: int = 500) -> Dict[str, Any]:
    """
    Returns Cytoscape.js-compatible element list.
    Limits output to the N highest-degree nodes to keep the UI responsive.
    """
    if G.number_of_nodes() > limit_nodes:
        # Keep top-degree nodes
        top_nodes = sorted(G.nodes, key=lambda n: G.degree(n), reverse=True)[:limit_nodes]
        sub = G.subgraph(top_nodes)
    else:
        sub = G

    elements: List[Dict] = []

    for node, data in sub.nodes(data=True):
        elements.append({
            "data": {
                "id": node,
                "label": node[:30] + ("…" if len(node) > 30 else ""),
                "raw": data.get("raw", node),
                "type": data.get("type", "unknown"),
                "color": data.get("color", "#94a3b8"),
                "degree": sub.degree(node),
            }
        })

    for src, tgt, data in sub.edges(data=True):
        elements.append({
            "data": {
                "id": f"{src}__{tgt}",
                "source": src,
                "target": tgt,
                "weight": data.get("weight", 1.0),
                "reason": data.get("reason", "shared_identifier"),
                "confidence": data.get("confidence", 0.6),
            }
        })

    return {
        "elements": elements,
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "cluster_count": nx.number_connected_components(G),
    }


def get_identifier_ego(G: nx.Graph, identifier: str, radius: int = 2) -> Dict[str, Any]:
    """Sub-graph centred on one identifier node, up to `radius` hops."""
    if identifier not in G:
        return {"elements": [], "node_count": 0, "edge_count": 0, "cluster_count": 0}
    ego = nx.ego_graph(G, identifier, radius=radius)
    return get_graph_json(ego, limit_nodes=200)
