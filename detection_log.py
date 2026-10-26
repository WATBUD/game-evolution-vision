from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path


class DetectionLogStore:
    """Append-only persistent storage for detection hit history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, str]] = []
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        for line in lines:
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                entries.append({
                    "timestamp": str(item.get("timestamp", "")),
                    "type": str(item.get("type", "")),
                    "content": str(item.get("content", "")),
                    "window": str(item.get("window", "")),
                    "detail": str(item.get("detail", "")),
                })
        return entries

    def append(
        self, detection_type: str, content: str, window: str, detail: str,
    ) -> dict[str, str]:
        entry = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "type": detection_type,
            "content": content,
            "window": window,
            "detail": detail,
        }
        payload = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
                handle.flush()
        return entry

    def clear(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
