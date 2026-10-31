from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image


class DetectionLogStore:
    """Append-only persistent storage for detection hit history."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.evidence_dir = path.parent / "detection_evidence"
        self._lock = threading.Lock()
        self._known_ids: set[str] = set()

    @staticmethod
    def _new_log_id(existing: set[str]) -> str:
        while True:
            raw = secrets.token_hex(4).upper()
            log_id = f"{raw[:4]}-{raw[4:]}"
            if log_id not in existing:
                existing.add(log_id)
                return log_id

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, str]] = []
        known_ids: set[str] = set()
        migrated = False
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
                log_id = str(item.get("log_id", "")).strip().upper()
                if not log_id or log_id in known_ids:
                    log_id = self._new_log_id(known_ids)
                    migrated = True
                else:
                    known_ids.add(log_id)
                entries.append({
                    "log_id": log_id,
                    "locked": "1" if item.get("locked") in (True, "1") else "0",
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
        self._known_ids = known_ids
        if migrated:
            self._rewrite_entries(entries)
        return entries

    def _rewrite_entries(self, entries: list[dict[str, str]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                for entry in entries:
                    handle.write(
                        json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
                    )
                handle.flush()
            temporary.replace(self.path)

    def append(
        self, detection_type: str, target: str, content: str, score: str,
        threshold: str, window: str, detail: str, evidence: str,
    ) -> dict[str, str]:
        with self._lock:
            entry = {
                "log_id": self._new_log_id(self._known_ids),
                "locked": "0",
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
        self.clear_within_days(1e10)

    def set_locked(self, log_id: str, locked: bool) -> None:
        entries = self.load()
        for entry in entries:
            if entry["log_id"] == log_id:
                entry["locked"] = "1" if locked else "0"
        self._rewrite_entries(entries)

    def clear_within_days(self, days: float) -> int:
        if days <= 0:
            raise ValueError("days must be greater than zero")
        now = datetime.now().astimezone()
        try:
            cutoff = now - timedelta(days=days)
        except OverflowError:
            cutoff = datetime.min.replace(tzinfo=now.tzinfo)
        retained: list[dict[str, str]] = []
        removed: list[dict[str, str]] = []
        for entry in self.load():
            if entry.get("locked") == "1":
                retained.append(entry)
                continue
            try:
                timestamp = datetime.fromisoformat(entry.get("timestamp", ""))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.astimezone()
            except ValueError:
                retained.append(entry)
                continue
            (removed if timestamp >= cutoff else retained).append(entry)

        self._rewrite_entries(retained)
        with self._lock:
            self._known_ids = {entry.get("log_id", "") for entry in retained}
            evidence_root = self.evidence_dir.resolve()
            retained_evidence = {entry.get("evidence", "") for entry in retained}
            for entry in removed:
                evidence = entry.get("evidence", "")
                if not evidence or evidence in retained_evidence:
                    continue
                evidence_path = Path(evidence)
                try:
                    resolved = evidence_path.resolve()
                    resolved.relative_to(evidence_root)
                except (OSError, ValueError):
                    continue
                resolved.unlink(missing_ok=True)
        return len(removed)
