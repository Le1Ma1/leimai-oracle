from __future__ import annotations

import json
from datetime import datetime, timezone


def log_event(event: str, **fields: object) -> None:
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), flush=True)
