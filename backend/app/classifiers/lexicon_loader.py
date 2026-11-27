from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Dict, Tuple

from app.extractors.normaliser import normalise

logger = logging.getLogger(__name__)
TermIndex = Dict[str, Tuple[str, float, str]]
EmojiIndex = Dict[str, Tuple[str, float, str]]

DEFAULT_LOCAL_LEXICON_OVERLAY = "../data/local/lexicon_overlay.json"


class LexiconStore:
    def __init__(self):
        self.terms: TermIndex = {}
        self.emojis: EmojiIndex = {}
        self._sorted_terms_cache: list[str] | None = None

    def load(self, path: str | Path, lexicon_name: str) -> None:
        self._sorted_terms_cache = None
        p = Path(path)
        if not p.exists():
            logger.debug("Lexicon file not found: %s", p)
            return
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        for term, meta in data.get("terms", {}).items():
            key = normalise(term)
            if not key:
                continue
            existing = self.terms.get(key)
            if existing is None or meta["weight"] > existing[1]:
                self.terms[key] = (meta["category"], float(meta["weight"]), lexicon_name)
        for emoji, meta in data.get("emojis", {}).items():
            key = emoji.strip()
            existing = self.emojis.get(key)
            if existing is None or meta["weight"] > existing[1]:
                self.emojis[key] = (meta["category"], float(meta["weight"]), lexicon_name)
        logger.info("Loaded lexicon %r: %d terms, %d emojis", lexicon_name,
                    len(data.get("terms", {})), len(data.get("emojis", {})))

    def sorted_terms(self) -> list[str]:
        if self._sorted_terms_cache is None:
            self._sorted_terms_cache = sorted(self.terms.keys(), key=len, reverse=True)
        return self._sorted_terms_cache

    def term_count(self): return len(self.terms)
    def emoji_count(self): return len(self.emojis)


_store: LexiconStore | None = None


def get_lexicon_store() -> LexiconStore:
    global _store
    if _store is None:
        raise RuntimeError("Lexicon store not initialised.")
    return _store


def init_lexicons(
    drug_path: str,
    financial_path: str,
    arms_path: str,
    scam_path: str = "",
    extended_path: str = "",
    overlay_path: str = DEFAULT_LOCAL_LEXICON_OVERLAY,
) -> LexiconStore:
    global _store
    _store = LexiconStore()
    _store.load(drug_path, "drugs")
    _store.load(financial_path, "financial_crime")
    _store.load(arms_path, "arms")
    if scam_path:
        _store.load(scam_path, "scams")
    if extended_path:
        _store.load(extended_path, "extended")
    if overlay_path:
        _store.load(overlay_path, "local_overlay")
    logger.info("Lexicon store ready: %d terms, %d emojis", _store.term_count(), _store.emoji_count())
    return _store
