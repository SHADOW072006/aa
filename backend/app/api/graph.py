"""
Entity graph endpoints.

GET /graph              Full graph (Cytoscape JSON, capped at 500 nodes)
GET /graph/ego/{id}     Ego sub-graph for one identifier value (URL-encoded)
GET /graph/clusters     List of connected components (sorted by size)
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.retention_service import require_api_token
from app.graph.entity_graph import (
    build_graph,
    detect_clusters,
    get_graph_json,
    get_identifier_ego,
)

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/")
async def full_graph(
    limit: int = Query(500, ge=10, le=2000),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    G = await build_graph(db)
    return get_graph_json(G, limit_nodes=limit)


@router.get("/clusters")
async def clusters(
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    G = await build_graph(db)
    comps = detect_clusters(G)
    return {
        "cluster_count": len(comps),
        "clusters": [
            {"size": len(c), "members": c[:20]}  # cap member list in response
            for c in comps
        ],
    }


@router.get("/ego/{identifier}")
async def ego_graph(
    identifier: str,
    radius: int = Query(2, ge=1, le=3),
    _actor: str = Depends(require_api_token),
    db: AsyncSession = Depends(get_db),
):
    decoded = urllib.parse.unquote(identifier)
    G = await build_graph(db)
    return get_identifier_ego(G, decoded, radius=radius)
