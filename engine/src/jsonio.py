from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

WRITE_RETRY_ATTEMPTS = 8
WRITE_RETRY_SLEEP_SECONDS = 0.05
WRITE_RETRY_BACKOFF = 1.8
READ_RETRY_ATTEMPTS = 6
READ_RETRY_SLEEP_SECONDS = 0.05
READ_RETRY_BACKOFF = 1.7
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def _sanitize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _sanitize_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [_sanitize_payload(item) for item in payload]
    if isinstance(payload, str):
        return _CONTROL_CHARS_RE.sub(" ", payload)
    if isinstance(payload, float):
        if math.isnan(payload) or math.isinf(payload):
            return 0.0
        return float(payload)
    return payload


def dumps_json(payload: Any) -> str:
    sanitized = _sanitize_payload(payload)
    return json.dumps(sanitized, ensure_ascii=False, indent=2, allow_nan=False)


def write_json_atomic(payload: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = dumps_json(payload)
    json.loads(content)
    last_error: Exception | None = None

    for attempt in range(1, WRITE_RETRY_ATTEMPTS + 1):
        tmp = output_path.with_name(f"{output_path.name}.tmp.{os.getpid()}.{attempt}")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(output_path)
            json.loads(output_path.read_text(encoding="utf-8"))
            return
        except (PermissionError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            last_error = error
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            if attempt < WRITE_RETRY_ATTEMPTS:
                backoff = WRITE_RETRY_SLEEP_SECONDS * (WRITE_RETRY_BACKOFF ** (attempt - 1))
                time.sleep(backoff)
    raise RuntimeError(f"Failed to write JSON artifact: {output_path}: {last_error}")


def load_json_retry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    delay = READ_RETRY_SLEEP_SECONDS
    for attempt in range(1, READ_RETRY_ATTEMPTS + 1):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            if attempt >= READ_RETRY_ATTEMPTS:
                return {}
            time.sleep(delay)
            delay *= READ_RETRY_BACKOFF
    return {}
