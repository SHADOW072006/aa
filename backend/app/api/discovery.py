"""
Channel discovery API endpoints.

GET  /discovery/seeds              List all seed terms
POST /discovery/seeds              Add a seed term
DELETE /discovery/seeds/{id}       Deactivate a seed term
POST /discovery/search             On-demand search by query term
GET  /discovery/discovered         List channels discovered automatically
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db

router = APIRouter(prefix="/discovery", tags=["discovery"])


# ── Seed management ────────────────────────────────────────────────────────────

class SeedCreate(BaseModel):
    term: str


class SeedOut(BaseModel):
    id: int
    term: str
    is_active: bool


async def _ensure_seeds_table(db: AsyncSession) -> None:
    """Create seeds table if it does not exist yet."""
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS discovery_seeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """))


@router.get("/seeds", response_model=List[SeedOut])
async def list_seeds(db: AsyncSession = Depends(get_db)):
    await _ensure_seeds_table(db)
    rows = (await db.execute(text("SELECT id, term, is_active FROM discovery_seeds ORDER BY id"))).fetchall()
    return [{"id": r[0], "term": r[1], "is_active": bool(r[2])} for r in rows]


@router.post("/seeds", response_model=SeedOut, status_code=status.HTTP_201_CREATED)
async def add_seed(payload: SeedCreate, db: AsyncSession = Depends(get_db)):
    await _ensure_seeds_table(db)
    term = payload.term.strip()
    if not term:
        raise HTTPException(400, "Empty term")
    try:
        await db.execute(
            text("INSERT INTO discovery_seeds (term) VALUES (:term)"),
            {"term": term},
        )
        row = (await db.execute(
            text("SELECT id, term, is_active FROM discovery_seeds WHERE term=:term"),
            {"term": term},
        )).fetchone()
        return {"id": row[0], "term": row[1], "is_active": bool(row[2])}
    except Exception:
        raise HTTPException(409, "Term already exists")


@router.delete("/seeds/{seed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_seed(seed_id: int, db: AsyncSession = Depends(get_db)):
    await _ensure_seeds_table(db)
    await db.execute(
        text("UPDATE discovery_seeds SET is_active=0 WHERE id=:id"),
        {"id": seed_id},
    )


# ── On-demand search ─────────���─────────────────────────────────────────────────

class SearchPayload(BaseModel):
    query: str


@router.post("/search")
async def search_channels(payload: SearchPayload):
    """
    Search Telegram for channels matching the query and score them.
    Does NOT auto-add — returns results for the user to review.
    """
    query = payload.query.strip()
    if not query:
        raise HTTPException(400, "Empty query")
    try:
        from app.collectors.channel_discovery import get_discovery_engine
        engine = get_discovery_engine()
        results = await engine.search_now(query)
        return {"query": query, "count": len(results), "results": results}
    except Exception as exc:
        raise HTTPException(500, f"Discovery search failed: {exc}")


# ── Force add from discovery result ───────────────────────────────────────────

class AddDiscoveredChannel(BaseModel):
    username: str
    title: Optional[str] = None
    telegram_id: Optional[int] = None


@router.post("/add", status_code=status.HTTP_201_CREATED)
async def add_discovered_channel(
    payload: AddDiscoveredChannel,
    db: AsyncSession = Depends(get_db),
):
    """Manually add a channel found in discovery results."""
    from app.db.crud import upsert_channel
    ch = await upsert_channel(
        db,
        username=payload.username.lstrip("@"),
        telegram_id=payload.telegram_id,
        title=payload.title,
    )
    return {"id": ch.id, "username": ch.username, "is_active": ch.is_active}