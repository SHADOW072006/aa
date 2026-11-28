"""
Offline & optionally Telegram-verified network expansion (BFS) from a known channel.

Default path (`verify=False`, `persist=False`) uses ONLY stored DB data:
- ChannelScanResult.connected_nodes & top_identifiers
- Message.forwarded_from & t.me/<username> links in stored messages
- Shared contact identifiers across channels in the identifiers table

When `verify=True`, performs a cheap rate-limited `get_entity` check on public
usernames (never joins, messages, or iterates private chats).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, Channel, ChannelScanResult, Identifier, Message, ScanJob
from app.extractors.identifier_extractor import CONTACT_TYPES

logger = logging.getLogger(__name__)

_TME_LINK_RE = re.compile(r"t\.me/([a-zA-Z0-9_]{4,32})", re.IGNORECASE)
_VALID_TG_USERNAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{3,31}$")
_CONTACT_LINK_TYPES = frozenset(t for t in CONTACT_TYPES if t not in ("location", "url"))
_VERIFY_RATE_LIMIT_SECONDS = 1.5


async def _default_verify_entity(username: str) -> Dict[str, Any]:
    """Perform a single cheap get_entity lookup via the active Telethon session."""
    from telethon.errors import FloodWaitError, UsernameInvalidError, UsernameNotOccupiedError
    from telethon.tl.types import Channel as TgChannel, Chat as TgChat
    from app.collectors.telegram_collector import get_collector

    collector = get_collector()
    client = collector.client
    if not client.is_connected():
        await asyncio.wait_for(client.connect(), timeout=15)
    if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
        return {"status": "skipped_unauthorised"}

    try:
        entity = await asyncio.wait_for(client.get_entity(username), timeout=15)
        if isinstance(entity, (TgChannel, TgChat)):
            return {
                "status": "verified",
                "telegram_id": getattr(entity, "id", None),
                "title": getattr(entity, "title", None),
                "member_count": getattr(entity, "participants_count", None),
            }
        return {"status": "not_channel"}
    except FloodWaitError as fwe:
        logger.warning("FloodWait verifying @%s (%ds)", username, fwe.seconds)
        return {"status": "flood_wait", "wait_seconds": fwe.seconds}
    except (UsernameInvalidError, UsernameNotOccupiedError, ValueError):
        return {"status": "not_found"}
    except Exception as exc:
        logger.warning("Entity verification error for @%s: %s", username, exc)
        return {"status": "error", "detail": str(exc)}


async def expand_channel_network(
    db: AsyncSession,
    identifier: str,
    *,
    max_hops: int = 2,
    limit: int = 25,
    persist: bool = False,
    verify: bool = False,
    verify_fn: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    BFS network expansion starting from `identifier` using stored intelligence.
    """
    clean_id = identifier.lstrip("@").strip()
    root_ch: Optional[Channel] = None
    root_scan: Optional[ChannelScanResult] = None

    if clean_id.isdigit():
        root_ch = (await db.execute(select(Channel).where(Channel.id == int(clean_id)))).scalar_one_or_none()
        if not root_ch:
            root_scan = (
                await db.execute(select(ChannelScanResult).where(ChannelScanResult.id == int(clean_id)))
            ).scalar_one_or_none()
    if not root_ch and not root_scan:
        root_ch = (await db.execute(select(Channel).where(Channel.username.ilike(clean_id)))).scalar_one_or_none()
    if not root_scan:
        target_name = root_ch.username if root_ch else clean_id
        root_scan = (
            await db.execute(
                select(ChannelScanResult)
                .where(ChannelScanResult.channel_username.ilike(target_name))
                .order_by(ChannelScanResult.scanned_at.desc())
            )
        ).scalar_one_or_none()

    if not root_ch and not root_scan:
        raise ValueError(f"Channel @{clean_id} not found")

    root_username = root_ch.username if root_ch else root_scan.channel_username
    visited: Set[str] = {root_username.lower()}
    frontier: Dict[str, Dict[str, Any]] = {}
    queue: deque[Tuple[str, int]] = deque([(root_username, 0)])

    def _record_candidate(
        cand_name: str,
        *,
        hop: int,
        discovered_from: str,
        reason: str,
        evidence_item: str,
        channel_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> bool:
        clean_cand = cand_name.lstrip("@").strip()
        if not clean_cand:
            return False
        key = clean_cand.lower()
        if key == root_username.lower():
            return False
        if key in frontier:
            entry = frontier[key]
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            if evidence_item and evidence_item not in entry["evidence"] and len(entry["evidence"]) < 8:
                entry["evidence"].append(evidence_item)
            if channel_id and not entry["channel_id"]:
                entry["channel_id"] = channel_id
            return False
        if len(frontier) >= limit:
            return False
        frontier[key] = {
            "username": clean_cand,
            "title": title or clean_cand,
            "channel_id": channel_id,
            "hop": hop,
            "discovered_from": discovered_from,
            "reasons": [reason],
            "evidence": [evidence_item] if evidence_item else [],
            "verification_status": "unverified",
            "telegram_id": None,
            "member_count": None,
        }
        return True

    while queue and len(frontier) < limit:
        curr_name, hop = queue.popleft()
        if hop >= max_hops:
            continue

        ch_obj = (
            await db.execute(select(Channel).where(Channel.username.ilike(curr_name)))
        ).scalar_one_or_none()
        scan_obj = (
            await db.execute(
                select(ChannelScanResult)
                .where(ChannelScanResult.channel_username.ilike(curr_name))
                .order_by(ChannelScanResult.scanned_at.desc())
            )
        ).scalars().first()

        newly_added: List[str] = []

        # 1. ChannelScanResult connected_nodes
        if scan_obj and scan_obj.connected_nodes:
            try:
                cn = json.loads(scan_obj.connected_nodes)
            except Exception:
                cn = {}
            for linked_ch in cn.get("channels", []):
                if _record_candidate(
                    linked_ch,
                    hop=hop + 1,
                    discovered_from=curr_name,
                    reason="connected_node_channel",
                    evidence_item=f"connected_nodes:{curr_name}",
                ):
                    newly_added.append(linked_ch.lstrip("@").strip())

        # 2. Stored messages: forwarded_from & t.me links + shared identifiers
        if ch_obj:
            msg_rows = (
                await db.execute(
                    select(Message.forwarded_from, Message.text)
                    .where(Message.channel_id == ch_obj.id)
                )
            ).all()
            for fwd_from, msg_text in msg_rows:
                if fwd_from:
                    fwd_clean = fwd_from.lstrip("@").strip()
                    if fwd_clean and not fwd_clean.lower().startswith("channel_"):
                        if _record_candidate(
                            fwd_clean,
                            hop=hop + 1,
                            discovered_from=curr_name,
                            reason="forwarded_from",
                            evidence_item=f"forwarded_from:{fwd_clean}",
                        ):
                            newly_added.append(fwd_clean)
                if msg_text:
                    for m in _TME_LINK_RE.finditer(msg_text):
                        tme_user = m.group(1)
                        if tme_user.lower() in ("joinchat", "s", "c"):
                            continue
                        if _record_candidate(
                            tme_user,
                            hop=hop + 1,
                            discovered_from=curr_name,
                            reason="tme_link",
                            evidence_item=f"t.me/{tme_user}",
                        ):
                            newly_added.append(tme_user)

            # 3. Shared contact identifiers across channels
            ident_rows = (
                await db.execute(
                    select(Identifier.type, Identifier.normalised)
                    .join(Message, Message.id == Identifier.message_id)
                    .where(Message.channel_id == ch_obj.id)
                    .distinct()
                )
            ).all()
            norm_vals = [
                inorm for itype, inorm in ident_rows
                if itype in _CONTACT_LINK_TYPES and inorm
            ]
            if norm_vals:
                shared_rows = (
                    await db.execute(
                        select(Channel.id, Channel.username, Channel.title, Identifier.type, Identifier.normalised)
                        .join(Message, Message.channel_id == Channel.id)
                        .join(Identifier, Identifier.message_id == Message.id)
                        .where(Channel.id != ch_obj.id, Identifier.normalised.in_(norm_vals))
                        .distinct()
                    )
                ).all()
                for o_id, o_uname, o_title, itype, inorm in shared_rows:
                    if _record_candidate(
                        o_uname,
                        hop=hop + 1,
                        discovered_from=curr_name,
                        reason="shared_identifier",
                        evidence_item=f"{itype}:{inorm}",
                        channel_id=o_id,
                        title=o_title,
                    ):
                        newly_added.append(o_uname)

        for nxt in newly_added:
            nkey = nxt.lower()
            if nkey not in visited and len(frontier) < limit:
                visited.add(nkey)
                queue.append((nxt, hop + 1))

    # 4. Optional Telegram entity verification (cheap get_entity, rate-limited)
    if verify and frontier:
        checker = verify_fn or _default_verify_entity
        for idx, entry in enumerate(frontier.values()):
            uname = entry["username"]
            if not _VALID_TG_USERNAME_RE.match(uname):
                entry["verification_status"] = "non_telegram_handle"
                continue
            if idx > 0 and verify_fn is None:
                await asyncio.sleep(_VERIFY_RATE_LIMIT_SECONDS)
            res = await checker(uname)
            entry["verification_status"] = res.get("status", "unverified")
            if res.get("telegram_id"):
                entry["telegram_id"] = res["telegram_id"]
            if res.get("title"):
                entry["title"] = res["title"]
            if res.get("member_count") is not None:
                entry["member_count"] = res["member_count"]

    # 5. Optional persistence into ChannelScanResult
    persisted_count = 0
    if persist and frontier:
        job = ScanJob(
            seed_terms=json.dumps([f"expand:{root_username}"]),
            status="done",
            total_channels_found=len(frontier),
            total_channels_scanned=0,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        db.add(job)
        await db.flush()

        for entry in frontier.values():
            existing_sr = (
                await db.execute(
                    select(ChannelScanResult)
                    .where(ChannelScanResult.channel_username.ilike(entry["username"]))
                    .order_by(ChannelScanResult.scanned_at.desc())
                )
            ).scalars().first()
            if existing_sr:
                continue

            # Pull alert stats if channel is already in DB
            flagged_c = 0
            high_c = 0
            med_c = 0
            avg_s = 0.0
            msg_c = 0
            risk_lvl = "LOW"
            if entry["channel_id"]:
                msg_c = (
                    await db.execute(
                        select(func.count(Message.id)).where(Message.channel_id == entry["channel_id"])
                    )
                ).scalar_one() or 0
                al_rows = (
                    await db.execute(
                        select(Alert.risk_level, Alert.score)
                        .join(Message, Message.id == Alert.message_id)
                        .where(Message.channel_id == entry["channel_id"])
                    )
                ).all()
                if al_rows:
                    flagged_c = len(al_rows)
                    high_c = sum(1 for r, _ in al_rows if r == "HIGH")
                    med_c = sum(1 for r, _ in al_rows if r == "MEDIUM")
                    avg_s = round(sum(float(s or 0.0) for _, s in al_rows) / flagged_c, 4)
                    risk_lvl = "HIGH" if high_c > 0 else ("MEDIUM" if med_c > 0 else "LOW")

            sr = ChannelScanResult(
                scan_job_id=job.id,
                channel_username=entry["username"],
                channel_title=entry["title"],
                telegram_id=entry["telegram_id"],
                member_count=entry["member_count"],
                messages_scanned=msg_c,
                flagged_count=flagged_c,
                high_count=high_c,
                medium_count=med_c,
                avg_score=avg_s,
                risk_level=risk_lvl,
                seed_term=f"expand:{root_username}",
                already_monitored=bool(entry["channel_id"]),
                connected_nodes=json.dumps({
                    "discovered_from": entry["discovered_from"],
                    "reasons": entry["reasons"],
                    "evidence": entry["evidence"],
                }),
            )
            db.add(sr)
            persisted_count += 1
        await db.commit()

    frontier_list = sorted(frontier.values(), key=lambda x: (x["hop"], -len(x["evidence"]), x["username"].lower()))
    return {
        "root_username": root_username,
        "mode": "persist" if persist else "dry_run",
        "verify": verify,
        "max_hops": max_hops,
        "frontier_count": len(frontier_list),
        "persisted_count": persisted_count,
        "frontier": frontier_list,
    }
