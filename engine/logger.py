from __future__ import annotations

import json
from datetime import datetime, timezone


def _serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def log_event(event: str, **fields: object) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    entries = [f"{key}={_serialize(value)}" for key, value in sorted(fields.items())]
    line = f"{timestamp} level=INFO event={event}"
    if entries:
        line = f"{line} {' '.join(entries)}"
    print(line, flush=True)
