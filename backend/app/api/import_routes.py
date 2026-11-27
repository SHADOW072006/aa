"""
Data import endpoints.

POST /import/csv    Upload a CSV file of posts
POST /import/json   Upload a JSON file of posts
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.collectors.import_handler import import_csv, import_json, validate_csv, validate_json
from app.services.retention_service import require_api_token

router = APIRouter(prefix="/import", tags=["import"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/validate")
async def validate_import(
    file: UploadFile = File(...),
    _actor: str = Depends(require_api_token),
):
    """
    Dry-run preview of a CSV/JSON import: field mapping, timestamp health,
    classification outcome, identifier stats and label agreement.
    Writes nothing to the database.
    """
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    name = (file.filename or "").lower()
    if name.endswith(".csv"):
        return await validate_csv(content, file.filename)
    if name.endswith(".json"):
        return await validate_json(content, file.filename)
    raise HTTPException(status_code=400, detail="Expected a .csv or .json file")


@router.post("/csv")
async def upload_csv(
    file: UploadFile = File(...),
    _actor: str = Depends(require_api_token),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Expected a .csv file")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    result = await import_csv(content, file.filename)
    return result


@router.post("/json")
async def upload_json(
    file: UploadFile = File(...),
    _actor: str = Depends(require_api_token),
):
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Expected a .json file")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    result = await import_json(content, file.filename)
    return result
