"""SQLite-backed financial ledger for demo payments, balances, and loss accounting."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


class DemoLedger:
    """Real transactional ledger backed by SQLite.
    
    Tracks:
    - Account balances
    - Authorised transfers (money moved)
    - Held transfers (money held in escrow)
    - Declined/Blocked transfers (money saved)
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    account_name TEXT,
                    account_type TEXT,
                    balance REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    txn_id TEXT NOT NULL,
                    act_num INTEGER,
                    sender_id TEXT NOT NULL,
                    receiver_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL,  -- AUTHORIZED, HELD, DECLINED
                    tier TEXT NOT NULL,
                    reason TEXT,
                    money_moved REAL DEFAULT 0.0,
                    money_held REAL DEFAULT 0.0,
                    money_saved REAL DEFAULT 0.0,
                    created_at REAL NOT NULL
                )
            """)

    def reset(self) -> None:
        """Clear all accounts and ledger entries."""
        with self.conn:
            self.conn.execute("DELETE FROM accounts")
            self.conn.execute("DELETE FROM ledger_entries")

    def seed_account(self, account_id: str, balance: float, name: str = "", account_type: str = "customer") -> None:
        now = time.time()
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO accounts (account_id, account_name, account_type, balance, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (account_id, name or account_id, account_type, float(balance), now))

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_all_accounts(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM accounts ORDER BY account_id ASC")
        return [dict(r) for r in cur.fetchall()]

    def record_transfer(
        self,
        txn_id: str,
        act_num: int,
        sender_id: str,
        receiver_id: str,
        amount: float,
        tier: str,
        reason: str = "",
        protection_enabled: bool = True,
    ) -> Dict[str, Any]:
        """Record transfer based on decision tier and protection mode.
        
        If protection is OFF:
          All transactions are AUTHORIZED (simulating uncontained loss).
        If protection is ON:
          - ALLOW / STEP_UP -> AUTHORIZED (money moved)
          - REVIEW / HOLD -> HELD (money held in pending escrow)
          - BLOCK -> DECLINED (money saved)
        """
        now = time.time()
        amount = float(amount)
        
        if not protection_enabled:
            status = "AUTHORIZED"
            money_moved = amount
            money_held = 0.0
            money_saved = 0.0
        else:
            if tier == "BLOCK":
                status = "DECLINED"
                money_moved = 0.0
                money_held = 0.0
                money_saved = amount
            elif tier in ("REVIEW", "HOLD"):
                status = "HELD"
                money_moved = 0.0
                money_held = amount
                money_saved = 0.0
            else:
                status = "AUTHORIZED"
                money_moved = amount
                money_held = 0.0
                money_saved = 0.0

        # Update balances if authorized
        with self.conn:
            if status == "AUTHORIZED":
                self.conn.execute(
                    "UPDATE accounts SET balance = balance - ?, updated_at = ? WHERE account_id = ?",
                    (amount, now, sender_id),
                )
                self.conn.execute(
                    "UPDATE accounts SET balance = balance + ?, updated_at = ? WHERE account_id = ?",
                    (amount, now, receiver_id),
                )
            elif status == "HELD":
                # Deduct from sender into pending hold (escrow)
                self.conn.execute(
                    "UPDATE accounts SET balance = balance - ?, updated_at = ? WHERE account_id = ?",
                    (amount, now, sender_id),
                )

            cur = self.conn.execute("""
                INSERT INTO ledger_entries (
                    txn_id, act_num, sender_id, receiver_id, amount, status, tier, reason,
                    money_moved, money_held, money_saved, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                txn_id, act_num, sender_id, receiver_id, amount, status, tier, reason,
                money_moved, money_held, money_saved, now
            ))
            entry_id = cur.lastrowid

        return {
            "entry_id": entry_id,
            "txn_id": txn_id,
            "act_num": act_num,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "amount": amount,
            "status": status,
            "tier": tier,
            "reason": reason,
            "money_moved": money_moved,
            "money_held": money_held,
            "money_saved": money_saved,
            "sender_balance": self.get_account(sender_id).get("balance", 0.0) if self.get_account(sender_id) else 0.0,
            "receiver_balance": self.get_account(receiver_id).get("balance", 0.0) if self.get_account(receiver_id) else 0.0,
        }

    def get_totals(self) -> Dict[str, float]:
        """Compute aggregated money moved, money held, and money saved."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT 
                COALESCE(SUM(money_moved), 0.0) as total_moved,
                COALESCE(SUM(money_held), 0.0) as total_held,
                COALESCE(SUM(money_saved), 0.0) as total_saved,
                COUNT(*) as total_txns
            FROM ledger_entries
        """)
        row = cur.fetchone()
        return {
            "money_moved": round(row["total_moved"], 2),
            "money_held": round(row["total_held"], 2),
            "money_saved": round(row["total_saved"], 2),
            "total_txns": int(row["total_txns"]),
        }

    def get_recent_entries(self, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM ledger_entries ORDER BY entry_id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
