"""Session recorder for storing and replaying live audience participation runs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT / "data" / "live_sessions"


class SessionRecorder:
    """Records live room events with monotonic offsets and supports disk persistence & replay."""

    def __init__(self, room_code: str):
        self.room_code = str(room_code).upper()
        self.session_id = f"session_{self.room_code}_{int(time.time())}"
        self.created_at = time.time()
        self.events: List[Dict[str, Any]] = []
        self._seq = 0
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.file_path = SESSIONS_DIR / f"{self.session_id}.json"

    def record_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        self._seq += 1
        record = {
            "seq": self._seq,
            "timestamp": time.time(),
            "event_type": event_type,
            "data": data,
        }
        self.events.append(record)
        return record

    def save(self) -> Path:
        payload = {
            "session_id": self.session_id,
            "room_code": self.room_code,
            "created_at": self.created_at,
            "updated_at": time.time(),
            "total_events": len(self.events),
            "events": self.events,
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Saved live session to {self.file_path}")
        return self.file_path

    @classmethod
    def load(cls, file_or_id: str | Path) -> Dict[str, Any]:
        path = Path(file_or_id)
        if not path.exists():
            path = SESSIONS_DIR / f"{file_or_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Session recording not found: {file_or_id}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
