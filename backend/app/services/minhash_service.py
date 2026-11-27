"""
Stage 5 (P1): MinHash / LSH near-duplicate text index (datasketch).

- Skips posts under MINHASH_MIN_WORDS (default 5 words).
- Serialises MinHash digest as JSON array of ints into Message.minhash_sig.
- Rebuilds MinHashLSH index from DB at startup.
- Surfaces cross-channel near-duplicate matches for alerts and graph edges.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from datasketch import MinHash, MinHashLSH
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.extractors.normaliser import normalise

logger = logging.getLogger(__name__)


def _tokenise(text: str) -> List[str]:
    norm = normalise(text)
    return [t for t in re.split(r"\s+", norm) if t]


def compute_minhash(text: str, num_perm: Optional[int] = None) -> Optional[MinHash]:
    """Return a MinHash object or None if text has fewer than MINHASH_MIN_WORDS words."""
    if not text:
        return None
    tokens = _tokenise(text)
    if len(tokens) < settings.MINHASH_MIN_WORDS:
        return None
    perms = num_perm or settings.MINHASH_NUM_PERM
    mh = MinHash(num_perm=perms)
    # Use word 2-shingles (plus unigrams) so reworded ads with shared phrases match reliably
    for tok in tokens:
        mh.update(tok.encode("utf-8"))
    for i in range(len(tokens) - 1):
        mh.update(f"{tokens[i]} {tokens[i + 1]}".encode("utf-8"))
    return mh


def serialise_minhash(mh: MinHash) -> str:
    return json.dumps([int(x) for x in mh.hashvalues])


def deserialise_minhash(raw: str, num_perm: Optional[int] = None) -> Optional[MinHash]:
    try:
        vals = json.loads(raw)
        if not isinstance(vals, list) or not vals:
            return None
        mh = MinHash(num_perm=len(vals))
        mh.hashvalues[:] = vals
        return mh
    except Exception:
        return None


class NearDuplicateIndex:
    def __init__(self, threshold: Optional[float] = None, num_perm: Optional[int] = None) -> None:
        self.threshold = threshold if threshold is not None else settings.MINHASH_SIMILARITY_THRESHOLD
        self.num_perm = num_perm if num_perm is not None else settings.MINHASH_NUM_PERM
        self.lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._msg_channel: Dict[str, int] = {}
        self._inserted: Set[str] = set()

    def reset(self) -> None:
        self.lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self._msg_channel.clear()
        self._inserted.clear()

    async def rebuild_from_db(self, db: AsyncSession) -> int:
        from app.db.models import Message
        self.reset()
        rows = (
            await db.execute(
                select(Message.id, Message.channel_id, Message.minhash_sig)
                .where(Message.minhash_sig.is_not(None))
            )
        ).all()
        loaded = 0
        for mid, cid, sig in rows:
            mh = deserialise_minhash(sig, num_perm=self.num_perm)
            if mh is None or len(mh.hashvalues) != self.num_perm:
                continue
            key = f"msg:{mid}"
            if key not in self._inserted:
                self.lsh.insert(key, mh)
                self._inserted.add(key)
                self._msg_channel[key] = cid
                loaded += 1
        logger.info("NearDuplicateIndex rebuilt from DB: %d signatures", loaded)
        return loaded

    def add_message(self, msg_id: int, channel_id: int, text: str) -> Tuple[Optional[str], List[int]]:
        """Compute MinHash, query similar channels, and insert into LSH index."""
        mh = compute_minhash(text, num_perm=self.num_perm)
        if mh is None:
            return None, []
        sig_str = serialise_minhash(mh)
        hits = self.lsh.query(mh)
        other_channels = sorted({
            self._msg_channel[k]
            for k in hits
            if k in self._msg_channel and self._msg_channel[k] != channel_id
        })
        key = f"msg:{msg_id}"
        if key not in self._inserted:
            self.lsh.insert(key, mh)
            self._inserted.add(key)
            self._msg_channel[key] = channel_id
        return sig_str, other_channels

    def query_similar_channels(self, sig_str: Optional[str], self_channel_id: int) -> List[int]:
        if not sig_str:
            return []
        mh = deserialise_minhash(sig_str, num_perm=self.num_perm)
        if mh is None or len(mh.hashvalues) != self.num_perm:
            return []
        hits = self.lsh.query(mh)
        return sorted({
            self._msg_channel[k]
            for k in hits
            if k in self._msg_channel and self._msg_channel[k] != self_channel_id
        })


_index: Optional[NearDuplicateIndex] = None


def get_minhash_index() -> NearDuplicateIndex:
    global _index
    if _index is None:
        _index = NearDuplicateIndex()
    return _index

