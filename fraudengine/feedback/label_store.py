"""Phase 7A: SQLite label store for analyst feedback.

Provides tables for cases, case_events, and labels.
Supports the simulated analyst workflow.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = str(ROOT / "data" / "label_store.db")


class LabelStore:
    """SQLite-backed label store for analyst actions and feedback."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                txn_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                tier TEXT NOT NULL,
                score REAL NOT NULL,
                summary TEXT,
                scenario TEXT DEFAULT '',
                group_id TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                assigned_to TEXT DEFAULT NULL,
                amount REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS case_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT DEFAULT 'system',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (case_id) REFERENCES cases(case_id)
            );

            CREATE TABLE IF NOT EXISTS labels (
                label_id INTEGER PRIMARY KEY AUTOINCREMENT,
                txn_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                true_label INTEGER,
                analyst_label INTEGER,
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT 'analyst',
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(txn_id, source)
            );

            CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
            CREATE INDEX IF NOT EXISTS idx_cases_tier ON cases(tier);
            CREATE INDEX IF NOT EXISTS idx_cases_account ON cases(account_id);
            CREATE INDEX IF NOT EXISTS idx_labels_txn ON labels(txn_id);
        """)
        self.conn.commit()

    def create_case(self, decision_dict: Dict[str, Any]) -> str:
        """Create a new case from a scoring decision."""
        case_id = decision_dict.get("txn_id", f"case_{int(time.time() * 1000)}")
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT OR REPLACE INTO cases
            (case_id, txn_id, account_id, tier, score, summary, scenario, group_id, status, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                case_id,
                decision_dict.get("txn_id", ""),
                decision_dict.get("account_id", ""),
                decision_dict.get("tier", "REVIEW"),
                decision_dict.get("score", 0.0),
                decision_dict.get("summary", ""),
                decision_dict.get("scenario", ""),
                decision_dict.get("group_id", ""),
                decision_dict.get("amount", 0.0),
            ),
        )
        cursor.execute(
            """INSERT INTO case_events (case_id, action, actor, note)
            VALUES (?, 'created', 'system', ?)""",
            (case_id, f"Case created with tier={decision_dict.get('tier', 'REVIEW')}"),
        )
        self.conn.commit()
        return case_id

    def take_action(self, case_id: str, action: str, actor: str = "analyst",
                    note: str = "", label: Optional[int] = None) -> bool:
        """Record an analyst action on a case."""
        cursor = self.conn.cursor()
        # Verify case exists
        cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
        case = cursor.fetchone()
        if not case:
            return False

        # Map action to status
        status_map = {
            "approve": "approved",
            "block": "blocked",
            "escalate": "escalated",
            "dismiss": "dismissed",
            "reopen": "open",
        }
        new_status = status_map.get(action, case["status"])

        cursor.execute(
            """UPDATE cases SET status = ?, updated_at = datetime('now')
            WHERE case_id = ?""",
            (new_status, case_id),
        )
        cursor.execute(
            """INSERT INTO case_events (case_id, action, actor, note)
            VALUES (?, ?, ?, ?)""",
            (case_id, action, actor, note),
        )

        # If a label is provided, record it
        if label is not None:
            cursor.execute(
                """INSERT OR REPLACE INTO labels
                (txn_id, account_id, true_label, analyst_label, source)
                VALUES (?, ?, ?, ?, 'analyst')""",
                (case["txn_id"], case["account_id"], label, label),
            )

        self.conn.commit()
        return True

    def get_cases(self, status: Optional[str] = None, tier: Optional[str] = None,
                  limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get cases with optional filters."""
        query = "SELECT * FROM cases WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        query += " ORDER BY score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Get a single case with its events."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,))
        case = cursor.fetchone()
        if not case:
            return None

        result = dict(case)
        cursor.execute(
            "SELECT * FROM case_events WHERE case_id = ? ORDER BY created_at",
            (case_id,),
        )
        result["events"] = [dict(row) for row in cursor.fetchall()]
        return result

    def get_case_count(self, status: Optional[str] = None) -> int:
        """Count cases with optional status filter."""
        if status:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cases WHERE status = ?", (status,))
        else:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cases")
        return cursor.fetchone()[0]

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary metrics for the dashboard."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cases")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cases WHERE status = 'open'")
        open_cases = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cases WHERE tier = 'BLOCK'")
        blocked = cursor.fetchone()[0]
        cursor.execute("SELECT AVG(score) FROM cases WHERE status = 'open'")
        avg_score = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT SUM(amount) FROM cases WHERE tier IN ('REVIEW', 'BLOCK')")
        amount_held = cursor.fetchone()[0] or 0.0

        return {
            "total_cases": total,
            "open_cases": open_cases,
            "blocked_cases": blocked,
            "avg_risk_score": round(avg_score, 4),
            "amount_held": round(amount_held, 2),
        }

    def get_all_labels(self) -> Dict[str, Dict[str, Any]]:
        """Get all confirmed analyst labels as a dictionary keyed by txn_id."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT txn_id, account_id, true_label, analyst_label, source, created_at FROM labels")
        rows = cursor.fetchall()
        return {
            row["txn_id"]: {
                "account_id": row["account_id"],
                "true_label": row["true_label"],
                "analyst_label": row["analyst_label"],
                "source": row["source"],
                "created_at": row["created_at"],
            }
            for row in rows
        }

    def close(self):
        self.conn.close()

