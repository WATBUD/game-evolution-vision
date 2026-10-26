from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from PIL import Image


class DetectionLogStore:
    """Append-only persistent storage for detection hit history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.evidence_dir = path.parent / "detection_evidence"
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
                    "target": str(item.get("target", item.get("content", ""))),
                    "content": str(item.get("content", "")),
                    "score": str(item.get("score", "")),
                    "threshold": str(item.get("threshold", "")),
                    "window": str(item.get("window", "")),
                    "detail": str(item.get("detail", "")),
                    "evidence": str(item.get("evidence", "")),
                })
        return entries

    def append(
        self, detection_type: str, target: str, content: str, score: str,
        threshold: str, window: str, detail: str, evidence: str,
    ) -> dict[str, str]:
        entry = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "type": detection_type,
            "target": target,
            "content": content,
            "score": score,
            "threshold": threshold,
            "window": window,
            "detail": detail,
            "evidence": evidence,
        }
        payload = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
                handle.flush()
        return entry

    def save_evidence(self, image: Image.Image, label: str) -> str:
        safe_label = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", label).strip("_")
        safe_label = safe_label[:40] or "hit"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        with self._lock:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"{stamp}_{safe_label}.jpg"
            image.convert("RGB").save(path, format="JPEG", quality=82)
        return str(path)

    def clear(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
            if self.evidence_dir.exists():
                for pattern in ("*.jpg", "*.png"):
                    for path in self.evidence_dir.glob(pattern):
                        path.unlink(missing_ok=True)
