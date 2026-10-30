"""Redis client wrapper with automatic fakeredis fallback and delta inspection."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class InMemoryFallbackRedis:
    """Lightweight in-memory RESP dict fallback if neither redis nor fakeredis is installed."""
    def __init__(self):
        self._sets = {}
        self._hashes = {}
        self._strings = {}
        self._zsets = {}

    def ping(self) -> bool:
        return True

    def sismember(self, key: str, member: Any) -> bool:
        return str(member) in self._sets.get(key, set())

    def smembers(self, key: str) -> set:
        return set(self._sets.get(key, set()))

    def sadd(self, key: str, *members: Any) -> int:
        if key not in self._sets:
            self._sets[key] = set()
        added = 0
        for m in members:
            sm = str(m)
            if sm not in self._sets[key]:
                self._sets[key].add(sm)
                added += 1
        return added

    def scard(self, key: str) -> int:
        return len(self._sets.get(key, set()))

    def hset(self, key: str, key_or_none: Any = None, value: Any = None, mapping: Optional[Dict[str, Any]] = None) -> int:
        if key not in self._hashes:
            self._hashes[key] = {}
        count = 0
        if mapping:
            for k, v in mapping.items():
                self._hashes[key][str(k)] = str(v)
                count += 1
        if key_or_none is not None and value is not None:
            self._hashes[key][str(key_or_none)] = str(value)
            count += 1
        return count

    def hgetall(self, key: str) -> Dict[str, str]:
        return dict(self._hashes.get(key, {}))

    def get(self, key: str) -> Optional[str]:
        return self._strings.get(key)

    def set(self, key: str, val: Any) -> bool:
        self._strings[key] = str(val)
        return True

    def incrbyfloat(self, key: str, amount: float) -> float:
        cur = float(self._strings.get(key, 0.0))
        cur += float(amount)
        self._strings[key] = str(cur)
        return cur

    def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    def zadd(self, key: str, mapping: Dict[str, float]) -> int:
        if key not in self._zsets:
            self._zsets[key] = {}
        added = 0
        for m, score in mapping.items():
            if str(m) not in self._zsets[key]:
                added += 1
            self._zsets[key][str(m)] = float(score)
        return added

    def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        all_keys = set(self._sets.keys()) | set(self._hashes.keys()) | set(self._strings.keys()) | set(self._zsets.keys())
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._sets:
                del self._sets[k]
                deleted += 1
            if k in self._hashes:
                del self._hashes[k]
                deleted += 1
            if k in self._strings:
                del self._strings[k]
                deleted += 1
            if k in self._zsets:
                del self._zsets[k]
                deleted += 1
        return deleted


class DemoRedisStore:
    """Redis client wrapper with automatic fakeredis or in-memory fallback and delta inspection."""

    def __init__(self, host: str = "localhost", port: int = 6379, prefix: str = "demo:"):
        self.prefix = prefix
        self.is_real = False
        self.client = None
        self.delta_callbacks: List[Callable[[Dict[str, Any]], None]] = []

        import socket
        def is_port_open(h: str, p: int) -> bool:
            try:
                s = socket.socket()
                s.settimeout(0.05)
                s.connect(('127.0.0.1' if h == 'localhost' else h, p))
                s.close()
                return True
            except Exception:
                return False

        if is_port_open(host, port):
            try:
                import redis
                real_client = redis.Redis(host='127.0.0.1', port=port, decode_responses=True, socket_connect_timeout=0.1)
                real_client.ping()
                self.client = real_client
                self.is_real = True
                logger.info("DemoRedisStore connected to live Redis server.")
            except Exception:
                self._init_in_memory()
        else:
            self._init_in_memory()

    def _init_in_memory(self) -> None:
        try:
            import fakeredis
            self.client = fakeredis.FakeRedis(decode_responses=True)
            self.is_real = False
            logger.info("DemoRedisStore initialized in-memory FakeRedis.")
        except Exception:
            self.client = InMemoryFallbackRedis()
            self.is_real = False
            logger.info("DemoRedisStore initialized native InMemoryFallbackRedis (fakeredis unavailable).")

    def on_delta(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for Redis state mutations."""
        self.delta_callbacks.append(callback)

    def _emit_delta(self, key: str, op: str, before: Any, after: Any) -> None:
        delta = {
            "key": key,
            "operation": op,
            "before": before,
            "after": after,
            "timestamp": time.time(),
        }
        for cb in self.delta_callbacks:
            try:
                cb(delta)
            except Exception as e:
                logger.error(f"Error in delta callback: {e}")

    # ─────────────────────────────────────────────────────────────
    # Blocklist & Holdlist operations
    # ─────────────────────────────────────────────────────────────

    def blocklist_account_key(self) -> str:
        return f"{self.prefix}blocklist:accounts"

    def blocklist_device_key(self) -> str:
        return f"{self.prefix}blocklist:devices"

    def holdlist_account_key(self) -> str:
        return f"{self.prefix}holdlist:accounts"

    def monitorlist_account_key(self) -> str:
        return f"{self.prefix}monitorlist:accounts"

    def is_account_blocked(self, account_id: str) -> bool:
        return bool(self.client.sismember(self.blocklist_account_key(), account_id))

    def is_device_blocked(self, device_id: str) -> bool:
        if not device_id:
            return False
        return bool(self.client.sismember(self.blocklist_device_key(), device_id))

    def is_account_held(self, account_id: str) -> bool:
        return bool(self.client.sismember(self.holdlist_account_key(), account_id))

    def is_account_monitored(self, account_id: str) -> bool:
        return bool(self.client.sismember(self.monitorlist_account_key(), account_id))

    def block_account(self, account_id: str, reason: str = "") -> None:
        key = self.blocklist_account_key()
        before = list(self.client.smembers(key))
        self.client.sadd(key, account_id)
        # Store metadata
        meta_key = f"{self.prefix}meta:block:{account_id}"
        self.client.hset(meta_key, mapping={"reason": reason, "timestamp": str(time.time())})
        after = list(self.client.smembers(key))
        self._emit_delta(key, "SADD", before, after)

    def block_device(self, device_id: str, reason: str = "") -> None:
        key = self.blocklist_device_key()
        before = list(self.client.smembers(key))
        self.client.sadd(key, device_id)
        after = list(self.client.smembers(key))
        self._emit_delta(key, "SADD", before, after)

    def hold_account(self, account_id: str, reason: str = "") -> None:
        key = self.holdlist_account_key()
        before = list(self.client.smembers(key))
        self.client.sadd(key, account_id)
        meta_key = f"{self.prefix}meta:hold:{account_id}"
        self.client.hset(meta_key, mapping={"reason": reason, "timestamp": str(time.time())})
        after = list(self.client.smembers(key))
        self._emit_delta(key, "SADD", before, after)

    def monitor_account(self, account_id: str, reason: str = "") -> None:
        key = self.monitorlist_account_key()
        before = list(self.client.smembers(key))
        self.client.sadd(key, account_id)
        meta_key = f"{self.prefix}meta:monitor:{account_id}"
        self.client.hset(meta_key, mapping={"reason": reason, "timestamp": str(time.time())})
        after = list(self.client.smembers(key))
        self._emit_delta(key, "SADD", before, after)

    # ─────────────────────────────────────────────────────────────
    # Feature keys (fan-in, velocity, behavioural)
    # ─────────────────────────────────────────────────────────────

    def record_fanin(self, payee_id: str, sender_id: str, amount: float = 0.0, step: int = 700) -> int:
        """Update fan-in set and return new count."""
        key = f"{self.prefix}fanin:24h:{payee_id}"
        before_count = self.client.scard(key)
        self.client.sadd(key, sender_id)
        if amount > 0:
            self.client.incrbyfloat(f"{self.prefix}inflow:{payee_id}", amount)
        after_count = self.client.scard(key)
        if after_count != before_count:
            self._emit_delta(key, "SADD", f"{before_count} senders", f"{after_count} senders (+{sender_id})")
        return after_count

    def record_fan_in(self, payee_id: str, sender_id: str, txn_id: str = "", amount: float = 0.0) -> int:
        return self.record_fanin(payee_id=payee_id, sender_id=sender_id, amount=amount)

    def get_fan_in_count(self, payee_id: str) -> int:
        return self.client.scard(f"{self.prefix}fanin:24h:{payee_id}")

    def get_fanin_count(self, payee_id: str) -> int:
        return self.get_fan_in_count(payee_id)

    def get_inflow(self, account_id: str) -> float:
        val = self.client.get(f"{self.prefix}inflow:{account_id}")
        return float(val) if val else 0.0

    def get_outflow(self, account_id: str) -> float:
        val = self.client.get(f"{self.prefix}outflow:{account_id}")
        return float(val) if val else 0.0

    def record_outflow(self, account_id: str, amount: float) -> float:
        return float(self.client.incrbyfloat(f"{self.prefix}outflow:{account_id}", amount))

    def record_velocity(self, account_id: str, amount: float, step: int, txn_id: str) -> None:
        key = f"{self.prefix}vel:1h:{account_id}"
        before_len = self.client.zcard(key)
        member = f"{txn_id}|{amount}"
        self.client.zadd(key, {member: float(step)})
        self.record_outflow(account_id, amount)
        after_len = self.client.zcard(key)
        self._emit_delta(key, "ZADD", f"{before_len} items", f"{after_len} items (₹{amount:.0f})")

    def record_passthrough(self, account_id: str, inflow: float, outflow: float) -> float:
        key = f"{self.prefix}passthrough:{account_id}"
        ratio = outflow / (inflow + 1.0)
        before = self.client.hgetall(key)
        self.client.hset(key, mapping={"inflow": str(inflow), "outflow": str(outflow), "ratio": f"{ratio:.2%}"})
        self._emit_delta(key, "HSET", before or "empty", {"inflow": inflow, "outflow": outflow, "ratio": f"{ratio:.2%}"})
        return ratio

    def get_summary(self) -> Dict[str, Any]:
        """Get state of all blocklists and held accounts."""
        return {
            "blocked_accounts": list(self.client.smembers(self.blocklist_account_key())),
            "blocked_devices": list(self.client.smembers(self.blocklist_device_key())),
            "held_accounts": list(self.client.smembers(self.holdlist_account_key())),
            "monitored_accounts": list(self.client.smembers(self.monitorlist_account_key())),
        }

    def get_all_keys(self) -> List[str]:
        return list(self.client.keys(f"{self.prefix}*"))

    def reset(self) -> None:
        """Clear all demo-scoped keys leaving zero residue."""
        keys = self.client.keys(f"{self.prefix}*")
        if keys:
            self.client.delete(*keys)
        logger.info(f"DemoRedisStore reset: removed {len(keys)} keys.")
