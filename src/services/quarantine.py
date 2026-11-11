import json
from pathlib import Path
from typing import Any


def quarantine_payload(payload: Any, error: str, path: str | Path = "data/quarantine_records.json") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    records.append({"payload": payload, "error": error})
    target.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
