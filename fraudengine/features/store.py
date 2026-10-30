"""Feature store interface with in-memory and Redis backends."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import time
import uuid
import json

import collections
import redis
import pandas as pd
import numpy as np

from fraudengine.config import config


@dataclass
class VelocityFeatures:
    """Velocity features for a given window."""
    count: int
    sum: float
    distinct_payees: int
    amount_vs_sum: float


@dataclass
class BehaviouralProfile:
    """Running behavioural profile for an account."""
    amount_mean: float
    amount_m2: float  # Sum of squared differences for Welford's algorithm
    n_txns: int
    hour_of_day_counts: Dict[int, int]
    last_txn_step: int
    last_txn_time: float
    known_payees: set
    known_devices: set
    known_ip_prefixes: set

    @property
    def amount_std(self) -> float:
        """Compute standard deviation from M2."""
        if self.n_txns <= 1:
            return 0.0
        return (self.amount_m2 / self.n_txns) ** 0.5


class FeatureStore(ABC):
    """Abstract feature store for point-in-time feature computation."""

    @abstractmethod
    def get_velocity(self, account_id: str, step: int, windows: List[int]) -> Dict[int, VelocityFeatures]:
        """Get velocity features for multiple windows at a given step."""
        pass

    @abstractmethod
    def update_velocity(self, account_id: str, payee_id: str, amount: float, step: int, txn_id: str) -> None:
        """Update velocity state with a new transaction."""
        pass

    @abstractmethod
    def get_behavioural(self, account_id: str) -> Optional[BehaviouralProfile]:
        """Get behavioural profile for an account."""
        pass

    @abstractmethod
    def update_behavioural(self, account_id: str, amount: float, step: int, payee_id: str,
                          device_id: str, ip_prefix: str, hour_of_day: int) -> None:
        """Update behavioural profile with a new transaction."""
        pass

    @abstractmethod
    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        """Get device information."""
        pass

    @abstractmethod
    def update_device_info(self, device_id: str, account_id: str, ip_prefix: str, step: Optional[int] = None) -> None:
        """Update device information."""
        pass

    @abstractmethod
    def get_payee_info(self, payee_id: str) -> Dict[str, Any]:
        """Get payee information."""
        pass

    @abstractmethod
    def update_payee_info(self, payee_id: str, sender_id: str, amount: float, step: int, is_fraud: int) -> None:
        """Update payee information."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connections."""
        pass


class InMemoryFeatureStore(FeatureStore):
    """In-memory feature store for offline replay and testing."""

    def __init__(self, windows: List[int] = None, max_entries: int = 40000):
        self.windows = windows or [1, 6, 24]
        self.max_entries = max_entries
        self.velocity_state: collections.OrderedDict[str, List[Tuple[int, str, float, str]]] = collections.OrderedDict()
        self.behavioural_state: collections.OrderedDict[str, BehaviouralProfile] = collections.OrderedDict()
        self.device_state: collections.OrderedDict[str, Dict[str, Any]] = collections.OrderedDict()
        self.payee_state: collections.OrderedDict[str, Dict[str, Any]] = collections.OrderedDict()

    def _cleanup_old_events(self, account_id: str, current_step: int) -> None:
        """Remove events outside the largest window to save memory."""
        if account_id not in self.velocity_state:
            return
        max_window = max(self.windows)
        cutoff = current_step - max_window
        events = self.velocity_state[account_id]
        # Keep only events within the max window of current step
        self.velocity_state[account_id] = [e for e in events if e[0] >= cutoff]

    def get_velocity(self, account_id: str, step: int, windows: List[int] = None) -> Dict[int, VelocityFeatures]:
        windows = windows or self.windows
        self._cleanup_old_events(account_id, step)

        events = self.velocity_state.get(account_id, [])
        result = {}
        for window in windows:
            cutoff = step - window
            # Point-in-time: events with step in (step-window, step] i.e., step-window <= e[0] <= step
            window_events = [e for e in events if cutoff <= e[0] <= step]
            payees = set()
            total = 0.0
            for _, payee, amount, _ in window_events:
                payees.add(payee)
                total += amount
            count = len(window_events)
            current_amount = window_events[-1][2] if window_events else 0.0
            result[window] = VelocityFeatures(
                count=count,
                sum=round(total, 2),
                distinct_payees=len(payees),
                amount_vs_sum=current_amount / (total + 1.0) if window_events else 0.0
            )
        return result

    def update_velocity(self, account_id: str, payee_id: str, amount: float, step: int, txn_id: str) -> None:
        if account_id not in self.velocity_state:
            self.velocity_state[account_id] = []
            if len(self.velocity_state) > self.max_entries:
                self.velocity_state.popitem(last=False)
        self.velocity_state[account_id].append((step, payee_id, amount, txn_id))
        self._cleanup_old_events(account_id, step)

    def get_behavioural(self, account_id: str) -> Optional[BehaviouralProfile]:
        return self.behavioural_state.get(account_id)

    def update_behavioural(self, account_id: str, amount: float, step: int, payee_id: str,
                          device_id: str, ip_prefix: str, hour_of_day: int) -> None:
        if account_id not in self.behavioural_state:
            self.behavioural_state[account_id] = BehaviouralProfile(
                amount_mean=0.0,
                amount_m2=0.0,
                n_txns=0,
                hour_of_day_counts={},
                last_txn_step=-1,
                last_txn_time=0.0,
                known_payees=set(),
                known_devices=set(),
                known_ip_prefixes=set()
            )
            if len(self.behavioural_state) > self.max_entries:
                self.behavioural_state.popitem(last=False)

        profile = self.behavioural_state[account_id]

        # Welford's online algorithm for mean and variance
        n = profile.n_txns
        if n == 0:
            profile.amount_mean = amount
            profile.amount_m2 = 0.0
        else:
            delta = amount - profile.amount_mean
            profile.amount_mean += delta / (n + 1)
            delta2 = amount - profile.amount_mean
            profile.amount_m2 += delta * delta2

        profile.n_txns = n + 1
        profile.hour_of_day_counts[hour_of_day] = profile.hour_of_day_counts.get(hour_of_day, 0) + 1
        profile.last_txn_step = step
        profile.last_txn_time = time.time()
        profile.known_payees.add(payee_id)
        profile.known_devices.add(device_id)
        profile.known_ip_prefixes.add(ip_prefix)

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        return self.device_state.get(device_id, {
            "accounts": set(),
            "ip_prefixes": set(),
            "first_seen_step": None
        })

    def update_device_info(self, device_id: str, account_id: str, ip_prefix: str, step: Optional[int] = None) -> None:
        if device_id not in self.device_state:
            self.device_state[device_id] = {
                "accounts": set(),
                "ip_prefixes": set(),
                "first_seen_step": step
            }
            if len(self.device_state) > self.max_entries:
                self.device_state.popitem(last=False)
        self.device_state[device_id]["accounts"].add(account_id)
        self.device_state[device_id]["ip_prefixes"].add(ip_prefix)
        self.device_state[device_id]["last_seen_step"] = step

    def get_payee_info(self, payee_id: str) -> Dict[str, Any]:
        return self.payee_state.get(payee_id, {
            "senders": set(),
            "total_inflow": 0.0,
            "total_outflow": 0.0,
            "first_seen_step": None,
            "is_merchant": payee_id.startswith("M"),
            "fraud_senders": set()
        })

    def update_payee_info(self, payee_id: str, sender_id: str, amount: float, step: int, is_fraud: int) -> None:
        if payee_id not in self.payee_state:
            self.payee_state[payee_id] = {
                "senders": set(),
                "total_inflow": 0.0,
                "total_outflow": 0.0,
                "first_seen_step": step,
                "is_merchant": payee_id.startswith("M"),
                "fraud_senders": set()
            }
            if len(self.payee_state) > self.max_entries:
                self.payee_state.popitem(last=False)
        info = self.payee_state[payee_id]
        info["senders"].add(sender_id)
        info["total_inflow"] += amount
        if is_fraud == 1:
            info["fraud_senders"].add(sender_id)

    def close(self) -> None:
        pass


class RedisFeatureStore(FeatureStore):
    """Redis-backed feature store for streaming."""

    def __init__(self, windows: List[int] = None, key_prefix: str = "fraud:v2:",
                 host: Optional[str] = None, port: Optional[int] = None,
                 redis_client: Optional[redis.Redis] = None):
        self.windows = windows or [1, 6, 24]
        self.key_prefix = key_prefix
        redis_cfg = config.load("redis_config")
        if redis_client is not None:
            self.r = redis_client
        else:
            h = host or redis_cfg["redis"]["host"]
            p = port or redis_cfg["redis"]["port"]
            self.r = redis.Redis(
                host=h,
                port=p,
                decode_responses=redis_cfg["redis"]["decode_responses"]
            )
        self.key_ttl = redis_cfg["redis"]["ttl_hours"] * 3600
        self.batch_size = redis_cfg["redis"]["pipeline_batch_size"]

    def _velocity_key(self, account_id: str) -> str:
        return f"{self.key_prefix}vel:{account_id}"

    def _behavioural_key(self, account_id: str) -> str:
        return f"{self.key_prefix}beh:{account_id}"

    def _device_key(self, device_id: str) -> str:
        return f"{self.key_prefix}dev:{device_id}"

    def _payee_key(self, payee_id: str) -> str:
        return f"{self.key_prefix}pay:{payee_id}"

    def get_velocity(self, account_id: str, step: int, windows: List[int] = None) -> Dict[int, VelocityFeatures]:
        windows = windows or self.windows
        key = self._velocity_key(account_id)
        result = {}

        for window in windows:
            cutoff = float(step - window)
            upper = float(step) + 0.999999
            # Use ZRANGEBYSCORE to get events in window strictly ordered by insertion sequence
            members = self.r.zrangebyscore(key, cutoff, upper)
            payees = set()
            total = 0.0
            count = len(members)
            for member in members:
                try:
                    _, payee, amount = member.split("|")
                    payees.add(payee)
                    total += float(amount)
                except ValueError:
                    continue
            current_amount = float(members[-1].split("|")[2]) if members else 0.0
            result[window] = VelocityFeatures(
                count=count,
                sum=round(total, 2),
                distinct_payees=len(payees),
                amount_vs_sum=current_amount / (total + 1.0) if members else 0.0
            )
        return result

    def update_velocity(self, account_id: str, payee_id: str, amount: float, step: int, txn_id: str) -> None:
        key = self._velocity_key(account_id)
        self._seq = getattr(self, "_seq", 0) + 1
        score = float(step) + (self._seq % 1000000) * 1e-7
        member = f"{txn_id}|{payee_id}|{amount}"
        pipe = self.r.pipeline(transaction=True)
        pipe.zadd(key, {member: score})
        pipe.expire(key, self.key_ttl)
        pipe.execute()

    def get_behavioural(self, account_id: str) -> Optional[BehaviouralProfile]:
        key = self._behavioural_key(account_id)
        data = self.r.hgetall(key)
        if not data:
            return None
        raw_counts = json.loads(data.get("hour_counts", "{}"))
        hour_counts = {int(k): int(v) for k, v in raw_counts.items()}
        return BehaviouralProfile(
            amount_mean=float(data.get("amount_mean", 0)),
            amount_m2=float(data.get("amount_m2", 0)),
            n_txns=int(data.get("n_txns", 0)),
            hour_of_day_counts=hour_counts,
            last_txn_step=int(data.get("last_step", -1)),
            last_txn_time=float(data.get("last_time", 0)),
            known_payees=set(json.loads(data.get("known_payees", "[]"))),
            known_devices=set(json.loads(data.get("known_devices", "[]"))),
            known_ip_prefixes=set(json.loads(data.get("known_ips", "[]")))
        )

    def update_behavioural(self, account_id: str, amount: float, step: int, payee_id: str,
                          device_id: str, ip_prefix: str, hour_of_day: int) -> None:
        key = self._behavioural_key(account_id)
        profile = self.get_behavioural(account_id)

        if profile is None:
            profile = BehaviouralProfile(
                amount_mean=0.0, amount_m2=0.0, n_txns=0,
                hour_of_day_counts={}, last_txn_step=-1,
                last_txn_time=0.0, known_payees=set(), known_devices=set(), known_ip_prefixes=set()
            )

        n = profile.n_txns
        if n == 0:
            profile.amount_mean = amount
            profile.amount_m2 = 0.0
        else:
            delta = amount - profile.amount_mean
            profile.amount_mean += delta / (n + 1)
            delta2 = amount - profile.amount_mean
            profile.amount_m2 += delta * delta2

        profile.n_txns = n + 1
        profile.hour_of_day_counts[hour_of_day] = profile.hour_of_day_counts.get(hour_of_day, 0) + 1
        profile.last_txn_step = step
        profile.last_txn_time = time.time()
        profile.known_payees.add(payee_id)
        profile.known_devices.add(device_id)
        profile.known_ip_prefixes.add(ip_prefix)

        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={
            "amount_mean": profile.amount_mean,
            "amount_m2": profile.amount_m2,
            "n_txns": profile.n_txns,
            "hour_counts": json.dumps(profile.hour_of_day_counts),
            "last_step": profile.last_txn_step,
            "last_time": profile.last_txn_time,
            "known_payees": json.dumps(list(profile.known_payees)),
            "known_devices": json.dumps(list(profile.known_devices)),
            "known_ips": json.dumps(list(profile.known_ip_prefixes))
        })
        pipe.expire(key, self.key_ttl)
        pipe.execute()

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        key = self._device_key(device_id)
        data = self.r.hgetall(key)
        if not data:
            return {"accounts": set(), "ip_prefixes": set(), "first_seen_step": None}
        step_val = data.get("first_seen_step")
        first_step = int(step_val) if (step_val is not None and step_val != "") else None
        return {
            "accounts": set(json.loads(data.get("accounts", "[]"))),
            "ip_prefixes": set(json.loads(data.get("ip_prefixes", "[]"))),
            "first_seen_step": first_step
        }

    def update_device_info(self, device_id: str, account_id: str, ip_prefix: str, step: Optional[int] = None) -> None:
        key = self._device_key(device_id)
        info = self.get_device_info(device_id)
        info["accounts"].add(account_id)
        info["ip_prefixes"].add(ip_prefix)
        if info["first_seen_step"] is None:
            info["first_seen_step"] = step

        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={
            "accounts": json.dumps(list(info["accounts"])),
            "ip_prefixes": json.dumps(list(info["ip_prefixes"])),
            "first_seen_step": "" if info["first_seen_step"] is None else str(info["first_seen_step"])
        })
        pipe.expire(key, self.key_ttl)
        pipe.execute()

    def get_payee_info(self, payee_id: str) -> Dict[str, Any]:
        key = self._payee_key(payee_id)
        data = self.r.hgetall(key)
        if not data:
            return {
                "senders": set(), "total_inflow": 0.0, "total_outflow": 0.0,
                "first_seen_step": None, "is_merchant": payee_id.startswith("M"),
                "fraud_senders": set()
            }
        return {
            "senders": set(json.loads(data.get("senders", "[]"))),
            "total_inflow": float(data.get("total_inflow", 0)),
            "total_outflow": float(data.get("total_outflow", 0)),
            "first_seen_step": int(data.get("first_seen_step", -1)) if data.get("first_seen_step") else None,
            "is_merchant": data.get("is_merchant", "false") == "true",
            "fraud_senders": set(json.loads(data.get("fraud_senders", "[]")))
        }

    def update_payee_info(self, payee_id: str, sender_id: str, amount: float, step: int, is_fraud: int) -> None:
        key = self._payee_key(payee_id)
        info = self.get_payee_info(payee_id)
        info["senders"].add(sender_id)
        info["total_inflow"] += amount
        if is_fraud == 1:
            info["fraud_senders"].add(sender_id)

        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping={
            "senders": json.dumps(list(info["senders"])),
            "total_inflow": info["total_inflow"],
            "total_outflow": info["total_outflow"],
            "first_seen_step": info["first_seen_step"] or step,
            "is_merchant": "true" if info["is_merchant"] else "false",
            "fraud_senders": json.dumps(list(info["fraud_senders"]))
        })
        pipe.expire(key, self.key_ttl)
        pipe.execute()

    def close(self) -> None:
        self.r.close()


def create_feature_store(backend: str = "memory", **kwargs) -> FeatureStore:
    """Factory function to create feature store."""
    if backend == "redis":
        return RedisFeatureStore(**kwargs)
    return InMemoryFeatureStore(**kwargs)