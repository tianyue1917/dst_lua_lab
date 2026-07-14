from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "length": len(value),
            "hex": value.hex(),
            "text_preview": value.decode("utf-8", "replace")[:160],
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): safe_value(v) for k, v in value.items()}
    return repr(value)


@dataclass(slots=True)
class TraceRecorder:
    path: Path
    max_events: int = 10000
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event_type: str, source: str, effect: str, **data: Any) -> None:
        if len(self.events) >= self.max_events:
            return
        event = {
            "seq": len(self.events) + 1,
            "virtual_time": 0.0,
            "type": event_type,
            "source": source,
            "effect": effect,
            "data": safe_value(data),
        }
        self.events.append(event)

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            for event in self.events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
