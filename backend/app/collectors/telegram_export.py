"""
Telegram Desktop export (result.json) importer.

Converts a Telegram Desktop JSON export into import rows for
import_handler.process_rows, reusing the whole pipeline (classification,
identifier extraction, evidence hashing, OCR, MinHash).

Format reference (Telegram Desktop, "Machine-readable JSON"):
    {
      "name": "Channel Name", "type": "public_channel", "id": 1711574679,
      "messages": [
        {"id": 3, "type": "message", "date": "2026-09-01T20:57:19",
         "from": "...", "photo": "photos/photo_2@....jpg",
         "text": "plain" | ["plain", {"type": "phone", "text": "+91-..."}, ...],
         "text_entities": [...], "forwarded_from": "..."},
        {"id": 1, "type": "service", ...}   # service messages are skipped
      ]
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _flatten_text(text: Any) -> str:
    """
    Telegram export text is either a plain string or a list of inline segments
    (strings and {"type": "phone"/"mention"/"link"/..., "text": ...} objects).
    Concatenate in order — the segments are the visible message.
    """
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        parts: List[str] = []
        for seg in text:
            if isinstance(seg, str):
                parts.append(seg)
            elif isinstance(seg, dict):
                seg_text = seg.get("text")
                if seg_text:
                    parts.append(str(seg_text))
        return "".join(parts)
    return ""


def telegram_export_rows(result_json_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parse one channel export. Returns (rows, channel_meta); rows feed
    process_rows (with settings.IMPORT_MEDIA_ROOT set to the export folder so
    relative photo paths resolve).
    """
    result_json_path = Path(result_json_path)
    data = json.loads(result_json_path.read_text(encoding="utf-8"))
    name = data.get("name") or result_json_path.parent.name

    rows: List[Dict[str, Any]] = []
    skipped_service = 0
    forwarded = 0
    photos = 0
    for msg in data.get("messages", []):
        if msg.get("type") != "message":
            skipped_service += 1
            continue
        photo = msg.get("photo") or ""
        if photo:
            photos += 1
        if msg.get("forwarded_from"):
            forwarded += 1
        rows.append(
            {
                "message_id": msg.get("id"),
                "text": _flatten_text(msg.get("text")),
                "channel": name,
                "created_at": msg.get("date"),
                "sender": msg.get("from") or msg.get("actor") or "",
                "image_attachment": photo,
            }
        )

    meta = {
        "name": name,
        "telegram_id": data.get("id"),
        "chat_type": data.get("type"),
        "message_count": len(rows),
        "skipped_service": skipped_service,
        "forwarded": forwarded,
        "photos": photos,
        "export_dir": str(result_json_path.parent),
    }
    return rows, meta
