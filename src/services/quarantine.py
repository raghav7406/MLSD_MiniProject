"""Quarantine service – persists invalid payloads with field-level error detail."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUARANTINE_PATH = Path(os.getenv("QUARANTINE_PATH", "data/quarantine_records.json"))


def quarantine_payload(payload: Any, error: str, path: str | Path | None = None) -> str:
    """Quarantine an invalid payload and return a quarantine_id."""
    target = Path(path) if path else QUARANTINE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    quarantine_id = str(uuid.uuid4())

    # Extract field-level errors from Pydantic validation output
    field_errors: list[dict] = []
    if isinstance(error, str):
        try:
            import ast
            parsed = ast.literal_eval(error)
            if isinstance(parsed, list):
                for err in parsed:
                    if isinstance(err, dict):
                        field_errors.append({
                            "field": err.get("loc", ["unknown"])[-1] if err.get("loc") else "unknown",
                            "code": err.get("type", "validation_error"),
                            "message": err.get("msg", str(err)),
                        })
        except (ValueError, SyntaxError):
            field_errors.append({"field": "unknown", "code": "validation_error", "message": error})

    record = {
        "quarantine_id": quarantine_id,
        "payload": payload,
        "error": error,
        "field_errors": field_errors,
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
    }
    records.append(record)
    target.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    return quarantine_id
