"""Phase 6: Append-only audit log with hash chain.

Each record includes txn_id, model_version, config_hash, feature_snapshot,
scores, decision, reasons, latency, and a prev_hash forming a tamper-evident chain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditLog:
    """Append-only JSONL audit log with hash chain for tamper detection."""

    def __init__(self, log_path: str, auto_flush: bool = True):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.auto_flush = auto_flush
        self._prev_hash = self._get_last_hash()
        self._file = None
        self._count = 0

    def _get_last_hash(self) -> str:
        """Read the last record's hash from the log file to continue the chain."""
        if not self.log_path.exists():
            return "GENESIS"
        last_line = ""
        try:
            with open(self.log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last_line = line
            if last_line:
                record = json.loads(last_line)
                return record.get("record_hash", "GENESIS")
        except Exception as e:
            logger.warning(f"Could not read last hash: {e}")
        return "GENESIS"

    def _compute_hash(self, record: Dict[str, Any], prev_hash: str) -> str:
        """Compute SHA-256 hash of record content + previous hash."""
        content = json.dumps(record, sort_keys=True, default=str)
        payload = f"{prev_hash}|{content}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def append(self, decision_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Append a decision record to the audit log."""
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "seq": self._count,
            "txn_id": decision_dict.get("txn_id", "unknown"),
            "account_id": decision_dict.get("account_id", "unknown"),
            "model_version": decision_dict.get("model_version", "unknown"),
            "config_hash": decision_dict.get("config_hash", "unknown"),
            "score": decision_dict.get("score", 0.0),
            "tier": decision_dict.get("tier", "ALLOW"),
            "summary": decision_dict.get("summary", ""),
            "reasons": decision_dict.get("reasons", []),
            "rule_hits": decision_dict.get("rule_hits", []),
            "latency_ms": decision_dict.get("latency_ms", 0.0),
            "feature_snapshot": decision_dict.get("feature_snapshot", {}),
            "prev_hash": self._prev_hash,
        }

        record_hash = self._compute_hash(record, self._prev_hash)
        record["record_hash"] = record_hash

        # Append to JSONL
        line = json.dumps(record, default=str)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

        self._prev_hash = record_hash
        self._count += 1
        return record

    def verify_chain(self) -> Dict[str, Any]:
        """Verify the entire hash chain. Returns verification result."""
        if not self.log_path.exists():
            return {"valid": True, "records": 0, "message": "Empty log"}

        records = []
        with open(self.log_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if not records:
            return {"valid": True, "records": 0, "message": "Empty log"}

        # Verify first record
        first = records[0]
        if first.get("prev_hash") != "GENESIS":
            return {
                "valid": False,
                "records": len(records),
                "broken_at": 0,
                "message": "First record does not start from GENESIS",
            }

        # Verify chain
        for i, record in enumerate(records):
            stored_hash = record.pop("record_hash", None)
            expected_prev = "GENESIS" if i == 0 else records[i - 1].get("record_hash_restored", "")
            computed_hash = self._compute_hash(record, record.get("prev_hash", ""))

            # Restore hash for next iteration
            record["record_hash"] = stored_hash
            record["record_hash_restored"] = stored_hash

            if stored_hash != computed_hash:
                return {
                    "valid": False,
                    "records": len(records),
                    "broken_at": i,
                    "message": f"Hash mismatch at record {i}: stored={stored_hash[:16]}..., computed={computed_hash[:16]}...",
                }

            if i > 0 and record.get("prev_hash") != records[i - 1].get("record_hash"):
                return {
                    "valid": False,
                    "records": len(records),
                    "broken_at": i,
                    "message": f"Chain broken at record {i}: prev_hash does not match previous record's hash",
                }

        # Clean up temp key
        for r in records:
            r.pop("record_hash_restored", None)

        return {
            "valid": True,
            "records": len(records),
            "message": f"All {len(records)} records verified successfully",
            "first_hash": records[0].get("record_hash", "")[:16],
            "last_hash": records[-1].get("record_hash", "")[:16],
        }

    def get_records(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Read records from the audit log."""
        if not self.log_path.exists():
            return []
        records = []
        with open(self.log_path, "r") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if len(records) >= limit:
                    break
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def count(self) -> int:
        """Count total records in the log."""
        if not self.log_path.exists():
            return 0
        count = 0
        with open(self.log_path, "r") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
