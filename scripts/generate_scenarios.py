"""Phase 2: Realistic scenario generator.

Produces a single chronologically ordered table merging PaySim with injected
fraud scenarios and hard negatives. Output is written to parquet (pyarrow) when
available, otherwise CSV.

Columns:
    txn_id, step, ts, account_id, payee_id, amount, txn_type,
    old_balance_orig, new_balance_orig, device_id, ip_prefix,
    label, scenario, group_id, split

Design decisions & rules:
- Scenarios are distributed across splits (train <= 500, val 501-600, test > 600)
  so supervised models can learn pattern signatures, validation can tune hyperparameters,
  and test provides unbiased held-out evaluation.
- Every scenario instance is assigned to exactly one split by its start step and
  never spans split boundaries.
- device_id and ip_prefix are synthesized deterministically per account.
- Injected transaction balances are internally consistent: a running balance is
  maintained per account.
- Amounts are drawn from empirical legitimate distributions.
- group_id identifies each scenario instance for group-aware evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import yaml

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE_TIME = datetime(2023, 1, 1, tzinfo=timezone.utc)
DEFAULT_INPUT = "data/PS_20174392719_1491204439457_log.csv"
DEFAULT_OUTPUT = "data/scenarios.parquet"
DEFAULT_CONFIG = "configs/model_config.yaml"
SEED = 42

TRAIN_MAX_STEP = 500
VAL_MAX_STEP = 600
TEST_MAX_STEP = 743

# Precompute step to ISO timestamp mapping for blazing fast vectorized mapping
STEP_TO_TS_MAP = {
    s: (BASE_TIME + timedelta(hours=int(s))).isoformat()
    for s in range(0, TEST_MAX_STEP + 50)
}


def _hash_u64(key: str, seed: int = SEED) -> int:
    return int(hashlib.md5(f"{seed}|{key}".encode()).hexdigest(), 16) % (2**63)


def account_device_ip(account: str, slot: int = 0) -> Tuple[str, str]:
    """Deterministic (device_id, ip_prefix) for an account/slot."""
    h = _hash_u64(f"{account}|slot{slot}")
    dev = f"DEV_{h % 1000000:06d}"
    a = (h // 1000000) % 256
    b = (h // 256000000) % 256
    ip = f"192.168.{a}.{b}.0/24"
    if slot >= 1:
        dev = f"DEV_S{dev}"
        ip = f"10.{a}.{b}.0/24"
    return dev, ip


def household_device(household_key: str) -> Tuple[str, str]:
    """Deterministic shared device/ip for a household group."""
    h = _hash_u64(f"HH|{household_key}")
    dev = f"DEV_H{h % 1000000:06d}"
    a = (h // 1000000) % 16 + 16
    b = (h // 256000000) % 256
    ip = f"172.{a}.{b}.0/24"
    return dev, ip


def split_of_step(step: int) -> str:
    if step <= TRAIN_MAX_STEP:
        return "train"
    if step <= VAL_MAX_STEP:
        return "val"
    return "test"


def load_paysim(input_path: str) -> pd.DataFrame:
    cols = [
        "step", "type", "amount", "nameOrig", "oldbalanceOrg",
        "newbalanceOrig", "nameDest", "isFraud",
    ]
    df = pd.read_csv(input_path, usecols=cols)
    df = df.rename(columns={
        "nameOrig": "account_id",
        "nameDest": "payee_id",
        "oldbalanceOrg": "old_balance_orig",
        "newbalanceOrig": "new_balance_orig",
        "isFraud": "label",
    })
    df["txn_type"] = df["type"]
    df = df.drop(columns=["type"])
    return df


def synthesise_devices_ips(accounts: List[str]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Deterministically assign shared household devices and second devices.

    Returns:
        account_device: dict of account -> [primary_device, second_device?]
        account_ip: dict of account -> [primary_ip, second_ip?]
    """
    rng = np.random.RandomState(SEED)
    accounts = sorted(set(accounts))

    account_device: Dict[str, List[str]] = {}
    account_ip: Dict[str, List[str]] = {}

    # Sample a manageable subset of accounts for household sharing (~20,000 households)
    n_sample = min(100000, len(accounts))
    sample_accts = [accounts[i] for i in rng.choice(len(accounts), size=n_sample, replace=False)]

    p = 0
    while p + 4 < len(sample_accts):
        size = int(rng.randint(2, 5))
        grp_accts = sample_accts[p:p + size]
        p += size
        household_key = "|".join(sorted(grp_accts))
        dev, ip = household_device(household_key)
        for a in grp_accts:
            account_device[a] = [dev]
            account_ip[a] = [ip]

    # ~5% of accounts get a second device
    for a in sample_accts[:int(len(sample_accts) * 0.05)]:
        if a not in account_device:
            dev0, ip0 = account_device_ip(a, slot=0)
            account_device[a] = [dev0]
            account_ip[a] = [ip0]
        dev1, ip1 = account_device_ip(a, slot=1)
        account_device[a].append(dev1)
        account_ip[a].append(ip1)

    return account_device, account_ip


class ConditionalLegitSampler:
    """Samples amounts and balances from legitimate empirical conditional distributions
    by txn_type and balance bucket to guarantee zero artificial amount/balance separability.
    """
    def __init__(self, df: pd.DataFrame):
        legit = df[df["label"] == 0]
        self.pools: Dict[str, Dict[int, np.ndarray]] = {}
        self.empirical_bals: Dict[str, np.ndarray] = {}

        for ttype in ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"]:
            sub_t = legit[legit["txn_type"] == ttype]
            if len(sub_t) == 0:
                sub_t = legit

            pos_b = sub_t[sub_t["old_balance_orig"] > 500]["old_balance_orig"].to_numpy()
            if len(pos_b) == 0:
                pos_b = legit[legit["old_balance_orig"] > 500]["old_balance_orig"].to_numpy()
            self.empirical_bals[ttype] = pos_b

            self.pools[ttype] = {}
            # Buckets: 0: <=20k, 1: 20k-100k, 2: 100k-500k, 3: >500k
            b0 = sub_t[sub_t["old_balance_orig"] <= 20000]["amount"].to_numpy()
            b1 = sub_t[(sub_t["old_balance_orig"] > 20000) & (sub_t["old_balance_orig"] <= 100000)]["amount"].to_numpy()
            b2 = sub_t[(sub_t["old_balance_orig"] > 100000) & (sub_t["old_balance_orig"] <= 500000)]["amount"].to_numpy()
            b3 = sub_t[sub_t["old_balance_orig"] > 500000]["amount"].to_numpy()

            all_amt = sub_t["amount"].to_numpy()
            self.pools[ttype][0] = b0 if len(b0) > 0 else all_amt
            self.pools[ttype][1] = b1 if len(b1) > 0 else all_amt
            self.pools[ttype][2] = b2 if len(b2) > 0 else all_amt
            self.pools[ttype][3] = b3 if len(b3) > 0 else all_amt

    def sample_initial_balance(self, ttype: str, rng: np.random.RandomState, min_val: float = 1000.0) -> float:
        bals = self.empirical_bals.get(ttype, self.empirical_bals["TRANSFER"])
        filtered = bals[bals >= min_val]
        if len(filtered) > 0:
            return round(float(rng.choice(filtered)), 2)
        return round(float(rng.choice(bals)), 2)

    def sample_amount(self, ttype: str, current_balance: float, rng: np.random.RandomState,
                      max_fraction: float = 0.95, is_draining: bool = False) -> float:
        if is_draining and current_balance > 0:
            return round(current_balance * float(rng.uniform(0.95, 0.999)), 2)

        if current_balance <= 20000:
            b = 0
        elif current_balance <= 100000:
            b = 1
        elif current_balance <= 500000:
            b = 2
        else:
            b = 3

        pool = self.pools.get(ttype, self.pools["TRANSFER"])[b]
        raw = float(rng.choice(pool))

        if current_balance > 0:
            if raw >= current_balance:
                amt = current_balance * float(rng.uniform(0.05, max_fraction))
            else:
                amt = min(raw, current_balance * max_fraction)
        else:
            amt = raw
        return round(max(10.0, amt), 2)


def partition_counts(total: int) -> Dict[str, int]:
    """Partition total instance count into train (60%), val (20%), test (20%)."""
    val_cnt = max(1, int(round(total * 0.20)))
    test_cnt = max(1, int(round(total * 0.20)))
    train_cnt = max(1, total - val_cnt - test_cnt)
    return {"train": train_cnt, "val": val_cnt, "test": test_cnt}


class ScenarioBuilder:
    def __init__(self, df: pd.DataFrame, account_device: Dict[str, List[str]],
                 account_ip: Dict[str, List[str]]):
        self.df = df
        self.account_device = account_device
        self.account_ip = account_ip
        self.rows: List[Dict[str, Any]] = []
        self.group_counter = 0

        # Empirical legitimate conditional sampler
        self.sampler = ConditionalLegitSampler(df)

        # Pick accounts with positive balance
        bal_series = df.groupby("account_id")["new_balance_orig"].last()
        self.bal = bal_series.astype(float).to_dict()

        cand_rng = np.random.RandomState(SEED + 1)
        all_accts = [a for a, b in self.bal.items() if b > 500]
        if len(all_accts) < 10000:
            all_accts = list(self.bal.keys())
        self.candidates = cand_rng.choice(all_accts, size=min(150000, len(all_accts)), replace=False).tolist()

        # Track last seen step per candidate for dormant reactivation
        last_step = df.groupby("account_id")["step"].max()
        self.dormant_candidates = last_step[last_step <= 200].index.intersection(self.candidates).tolist()
        if len(self.dormant_candidates) < 50:
            self.dormant_candidates = self.candidates[:500]

    def _device_ip_for(self, account: str, prefer_new: bool = False) -> Tuple[str, str]:
        devs = self.account_device.get(account)
        ips = self.account_ip.get(account)
        if not devs:
            dev, ip = account_device_ip(account, slot=0)
            return dev, ip
        if prefer_new and len(devs) > 1:
            return devs[-1], ips[-1]
        return devs[0], ips[0]

    def _emit(self, step: int, account: str, payee: str, amount: float,
              txn_type: str, label: int, scenario: str, group_id: str,
              new_device: bool = False, device_override: str = None,
              ip_override: str = None) -> None:
        old_bal = self.bal.get(account, 1000.0)
        new_bal = max(0.0, old_bal - amount)
        self.bal[payee] = self.bal.get(payee, 0.0) + amount
        self.bal[account] = new_bal

        if device_override and ip_override:
            dev, ip = device_override, ip_override
        else:
            dev, ip = self._device_ip_for(account, prefer_new=new_device)

        self.rows.append({
            "txn_id": f"INJ_{scenario}_{group_id}_{len(self.rows)}",
            "step": int(step),
            "ts": STEP_TO_TS_MAP.get(int(step), f"2023-01-01T00:00:00+00:00"),
            "account_id": account,
            "payee_id": payee,
            "amount": round(float(amount), 2),
            "txn_type": txn_type,
            "old_balance_orig": round(float(old_bal), 2),
            "new_balance_orig": round(float(new_bal), 2),
            "device_id": dev,
            "ip_prefix": ip,
            "label": int(label),
            "scenario": scenario,
            "group_id": group_id,
            "split": split_of_step(int(step)),
        })

    def _next_group(self, prefix: str) -> str:
        self.group_counter += 1
        return f"{prefix}_{self.group_counter:04d}"

    def _split_step_range(self, split: str, duration: int) -> Tuple[int, int]:
        """Return safe (min_step, max_step) so start_step + duration stays strictly within split."""
        if split == "train":
            return (50, TRAIN_MAX_STEP - duration - 2)
        elif split == "val":
            return (TRAIN_MAX_STEP + 5, VAL_MAX_STEP - duration - 2)
        else:
            return (VAL_MAX_STEP + 5, TEST_MAX_STEP - duration - 2)

    # ---- Scenario A: burst takeover ----
    def burst_takeover(self, counts: Dict[str, int], rng: np.random.RandomState,
                       cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"burst_{split}")
                originator = rng.choice(self.candidates)
                if self.bal.get(originator, 0) < 50000:
                    self.bal[originator] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=100000.0)

                n_mules = int(rng.randint(1, 4))
                mules = rng.choice([a for a in self.candidates if a != originator],
                                   size=n_mules, replace=False)
                n_txns = int(rng.randint(8, 26))
                window_h = int(rng.randint(1, 4))
                lo, hi = self._split_step_range(split, window_h)
                start = int(rng.randint(lo, hi + 1))

                for k in range(n_txns):
                    step = start + int((k * window_h) // n_txns)
                    mule = mules[k % len(mules)]
                    amount = self.sampler.sample_amount("TRANSFER", self.bal[originator], rng, max_fraction=0.15)
                    self._emit(step, originator, mule, amount, "TRANSFER", 1,
                               "burst_takeover", group_id, new_device=(k == 0))

    # ---- Scenario B: mule fan-in / fan-out ----
    def mule_fanin_fanout(self, counts: Dict[str, int], rng: np.random.RandomState,
                          cfg: Dict[str, Any]) -> None:
        forward_ratio = float(cfg.get("forward_ratio", 0.8))
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"mule_{split}")
                mule = rng.choice(self.candidates)
                self.bal[mule] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=1000.0)

                n_victims = int(rng.randint(10, 41))
                victims = rng.choice([a for a in self.candidates if a != mule],
                                     size=n_victims, replace=False)
                total_duration = 30  # 24h fan-in + 6h fan-out
                lo, hi = self._split_step_range(split, total_duration)
                start = int(rng.randint(lo, hi + 1))

                # Victims pay mule within 24h
                for v in victims:
                    step = start + int(rng.randint(0, 24))
                    if self.bal.get(v, 0) < 50000:
                        self.bal[v] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=100000.0)
                    amount = self.sampler.sample_amount("TRANSFER", self.bal[v], rng, max_fraction=0.85)
                    self._emit(step, v, mule, amount, "TRANSFER", 0,
                               "mule_fanin_fanout", group_id)

                # Mule forwards >=80% within 6h to 1-3 collectors
                mule_in = sum(r["amount"] for r in self.rows
                              if r["group_id"] == group_id and r["payee_id"] == mule)
                target_forward = mule_in * forward_ratio
                n_collectors = int(rng.randint(1, 4))
                collectors = rng.choice([a for a in self.candidates if a != mule and a not in victims],
                                        size=n_collectors, replace=False)

                fstart = start + 24
                forwarded_so_far = 0.0
                step_idx = 0
                while forwarded_so_far < target_forward and self.bal.get(mule, 0) > 1000.0:
                    c = collectors[step_idx % len(collectors)]
                    fstep = fstart + int(rng.randint(1, 7))
                    rem = target_forward - forwarded_so_far
                    amt = self.sampler.sample_amount("TRANSFER", self.bal[mule], rng, max_fraction=0.85)
                    amt = min(amt, self.bal[mule], rem)
                    if amt < 100.0:
                        break
                    self._emit(fstep, mule, c, amt, "TRANSFER", 1,
                               "mule_fanin_fanout", group_id)
                    forwarded_so_far += amt
                    step_idx += 1

    # ---- Scenario C: shared device ring ----
    def shared_device_ring(self, counts: Dict[str, int], rng: np.random.RandomState,
                           cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"ring_{split}")
                size = int(rng.randint(5, 16))
                ring = rng.choice(self.candidates, size=size, replace=False).tolist()

                shared_dev = f"DEV_RING_{group_id}"
                shared_ip = f"172.{int(rng.randint(16, 31))}.{int(rng.randint(1, 254))}.0/24"
                common_payee = f"COMMON_PAY_{group_id}"
                self.bal[common_payee] = 0.0

                for a in ring:
                    if self.bal.get(a, 0) < 50000:
                        self.bal[a] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=100000.0)

                duration = 18
                lo, hi = self._split_step_range(split, duration)
                start = int(rng.randint(lo, hi + 1))

                total_txns = 3 * len(ring)
                for k in range(total_txns):
                    step = start + int((k * duration) // total_txns)
                    sender = ring[k % len(ring)]
                    receiver = ring[(k + 1) % len(ring)]
                    amount = self.sampler.sample_amount("TRANSFER", self.bal[sender], rng, max_fraction=0.25)
                    self._emit(step, sender, receiver, amount, "TRANSFER", 1,
                               "shared_device_ring", group_id,
                               device_override=shared_dev, ip_override=shared_ip)

                    # Layering through common payee
                    amt2 = self.sampler.sample_amount("TRANSFER", self.bal[sender], rng, max_fraction=0.25)
                    self._emit(step, sender, common_payee, amt2, "TRANSFER", 1,
                               "shared_device_ring", group_id,
                               device_override=shared_dev, ip_override=shared_ip)

    # ---- Scenario D: structuring ----
    def structuring(self, counts: Dict[str, int], rng: np.random.RandomState,
                    cfg: Dict[str, Any]) -> None:
        threshold = float(cfg.get("amount_threshold", 10000.0))
        buffer_amt = float(cfg.get("buffer", 500.0))
        txns_per_account = int(cfg.get("txns_per_account", 8))

        for split, n_inst in counts.items():
            duration_days = 3 if split == "val" else 5
            duration_hours = duration_days * 24
            for _ in range(n_inst):
                group_id = self._next_group(f"struct_{split}")
                account = rng.choice(self.candidates)
                needed = (threshold - buffer_amt) * txns_per_account + 5000.0
                if self.bal.get(account, 0) < needed:
                    self.bal[account] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=needed + 50000.0)

                lo, hi = self._split_step_range(split, duration_hours)
                start = int(rng.randint(lo, hi + 1))

                for k in range(txns_per_account):
                    step = start + int((k * duration_hours) // txns_per_account)
                    payee = f"STRUCT_PAYEE_{group_id}_{k}"
                    amount = round(float(rng.uniform(threshold - buffer_amt, threshold - 10.0)), 2)
                    self._emit(step, account, payee, amount, "TRANSFER", 1,
                               "structuring", group_id)

    # ---- Scenario E: dormant reactivation ----
    def dormant_reactivation(self, counts: Dict[str, int], rng: np.random.RandomState,
                             cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"dormant_{split}")
                account = rng.choice(self.dormant_candidates)
                self.bal[account] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=50000.0)
                amount = self.sampler.sample_amount("TRANSFER", self.bal[account], rng, max_fraction=0.80)

                lo, hi = self._split_step_range(split, 1)
                start = int(rng.randint(lo, hi + 1))
                new_payee = f"NEW_PAYEE_{group_id}"
                self._emit(start, account, new_payee, amount, "TRANSFER", 1,
                           "dormant_reactivation", group_id, new_device=True)

    # ---- Hard negatives (label 0) ----
    def payroll(self, counts: Dict[str, int], rng: np.random.RandomState,
                cfg: Dict[str, Any]) -> None:
        n_emp = int(cfg.get("employees_per_employer", 50))
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"payroll_{split}")
                employer = rng.choice(self.candidates)
                employees = rng.choice([a for a in self.candidates if a != employer],
                                       size=n_emp, replace=False)
                amount = self.sampler.sample_amount("TRANSFER", 100000.0, rng, max_fraction=0.5)
                self.bal[employer] = (amount * n_emp) + 500000.0

                duration = 6
                lo, hi = self._split_step_range(split, duration)
                start = int(rng.randint(lo, hi + 1))

                for j, emp in enumerate(employees):
                    step = start + int((j * duration) // n_emp)
                    self._emit(step, employer, emp, amount, "TRANSFER", 0,
                               "payroll", group_id)

    def merchant_high_fanin(self, counts: Dict[str, int], rng: np.random.RandomState,
                            cfg: Dict[str, Any]) -> None:
        n_cust = int(cfg.get("customers_per_merchant", 80))
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"merchant_{split}")
                merchant = rng.choice(self.candidates)
                customers = rng.choice([a for a in self.candidates if a != merchant],
                                       size=n_cust, replace=False)
                duration = 24
                lo, hi = self._split_step_range(split, duration)
                start = int(rng.randint(lo, hi + 1))

                for j, cust in enumerate(customers):
                    step = start + int(rng.randint(0, duration))
                    if self.bal.get(cust, 0) < 5000:
                        self.bal[cust] = self.sampler.sample_initial_balance("PAYMENT", rng, min_val=10000.0)
                    amount = self.sampler.sample_amount("PAYMENT", self.bal[cust], rng)
                    self._emit(step, cust, merchant, amount, "PAYMENT", 0,
                               "merchant_high_fanin", group_id)

    def household_shared_device(self, counts: Dict[str, int], rng: np.random.RandomState,
                                cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"household_{split}")
                size = int(rng.randint(2, 5))
                grp = rng.choice(self.candidates, size=size, replace=False).tolist()
                shared_dev = f"DEV_HH_{group_id}"
                shared_ip = f"172.{int(rng.randint(16, 31))}.{int(rng.randint(1, 254))}.0/24"

                for a in grp:
                    if self.bal.get(a, 0) < 20000:
                        self.bal[a] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=50000.0)

                duration = 12
                lo, hi = self._split_step_range(split, duration)
                start = int(rng.randint(lo, hi + 1))

                for k in range(size * 4):
                    step = start + int((k * duration) // (size * 4))
                    sender = grp[k % size]
                    receiver = grp[(k + 1) % size]
                    amount = self.sampler.sample_amount("TRANSFER", self.bal[sender], rng, max_fraction=0.20)
                    self._emit(step, sender, receiver, amount, "TRANSFER", 0,
                               "household_shared_device", group_id,
                               device_override=shared_dev, ip_override=shared_ip)

    def large_legitimate_drain(self, counts: Dict[str, int], rng: np.random.RandomState,
                               cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"drain_{split}")
                account = rng.choice(self.candidates)
                if self.bal.get(account, 0) < 50000:
                    self.bal[account] = self.sampler.sample_initial_balance("TRANSFER", rng, min_val=100000.0)

                lo, hi = self._split_step_range(split, 1)
                start = int(rng.randint(lo, hi + 1))
                payee = f"LEGIT_EXPENSE_{group_id}"
                amount = self.sampler.sample_amount("TRANSFER", self.bal[account], rng, is_draining=True)
                self._emit(start, account, payee, amount, "TRANSFER", 0,
                           "large_legitimate_drain", group_id)

    def bill_payment_burst(self, counts: Dict[str, int], rng: np.random.RandomState,
                           cfg: Dict[str, Any]) -> None:
        for split, n_inst in counts.items():
            for _ in range(n_inst):
                group_id = self._next_group(f"bills_{split}")
                account = rng.choice(self.candidates)
                n_bills = int(rng.randint(4, 10))
                self.bal[account] = self.sampler.sample_initial_balance("PAYMENT", rng, min_val=50000.0)

                duration = 3
                lo, hi = self._split_step_range(split, duration)
                start = int(rng.randint(lo, hi + 1))

                for j in range(n_bills):
                    step = start + int((j * duration) // n_bills)
                    payee = f"BILLER_{group_id}_{j}"
                    amount = self.sampler.sample_amount("PAYMENT", self.bal[account], rng)
                    self._emit(step, account, payee, amount, "PAYMENT", 0,
                               "bill_payment_burst", group_id)

    def build(self) -> pd.DataFrame:
        cols = [
            "txn_id", "step", "ts", "account_id", "payee_id", "amount",
            "txn_type", "old_balance_orig", "new_balance_orig", "device_id",
            "ip_prefix", "label", "scenario", "group_id", "split"
        ]
        return pd.DataFrame(self.rows, columns=cols)


def _vectorized_device_ip(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Derive (device_id, ip_prefix) vectorized from account_id via fast integer arithmetic."""
    # Slicing is >10x faster than regex
    digits = pd.to_numeric(series.str.slice(1), errors="coerce").fillna(0).astype(np.uint64)
    h = (digits * np.uint64(2654435761)) % np.uint64(2**32)
    dev_idx = (h % np.uint64(1000000)).astype(str).str.zfill(6)
    device_id = "DEV_" + dev_idx
    a = ((h // np.uint64(1000000)) % np.uint64(256)).astype(int)
    b = ((h // np.uint64(256000000)) % np.uint64(256)).astype(int)
    ip_prefix = "192.168." + a.astype(str) + "." + b.astype(str) + ".0/24"
    return device_id, ip_prefix


def prepare_paysim_rows(df: pd.DataFrame,
                        account_device: Dict[str, List[str]],
                        account_ip: Dict[str, List[str]]) -> pd.DataFrame:
    """Add derived columns to native PaySim rows (vectorized)."""
    out = df.copy()
    n = len(out)
    out["txn_id"] = "PS_" + np.arange(n).astype(str)
    out["ts"] = out["step"].map(STEP_TO_TS_MAP)

    device_id, ip_prefix = _vectorized_device_ip(out["account_id"])

    # Apply household overrides if present
    if account_device:
        dev_map = {a: v[0] for a, v in account_device.items() if v}
        ip_map = {a: v[0] for a, v in account_ip.items() if v}
        acct = out["account_id"]
        ov_dev = acct.map(dev_map)
        ov_ip = acct.map(ip_map)
        device_id = device_id.where(ov_dev.isna(), ov_dev)
        ip_prefix = ip_prefix.where(ov_ip.isna(), ov_ip)

    out["device_id"] = device_id
    out["ip_prefix"] = ip_prefix
    out["scenario"] = "paysim_native"
    out["group_id"] = "paysim_native"
    out["split"] = np.where(
        out["step"] <= TRAIN_MAX_STEP, "train",
        np.where(out["step"] <= VAL_MAX_STEP, "val", "test")
    )
    cols = [
        "txn_id", "step", "ts", "account_id", "payee_id", "amount",
        "txn_type", "old_balance_orig", "new_balance_orig", "device_id",
        "ip_prefix", "label", "scenario", "group_id", "split"
    ]
    return out[cols]


def load_config_dict(config_arg: str) -> Dict[str, Any]:
    p = Path(config_arg)
    if p.exists() and p.suffix.lower() in (".yaml", ".yml"):
        with open(p, "r") as f:
            return yaml.safe_load(f)
    from fraudengine.config import config
    return config.load(config_arg)


def run(args: argparse.Namespace) -> pd.DataFrame:
    cfg_all = load_config_dict(args.config)
    scenarios_cfg = cfg_all.get("scenarios", {})
    hard_cfg = cfg_all.get("hard_negatives", {})

    print(f"Loading PaySim dataset from {args.input} ...")
    df = load_paysim(args.input)
    print(f"Loaded {len(df):,} rows (steps {df.step.min()} to {df.step.max()})")

    # Sample unique accounts for household synthesis
    sample_accounts = df["account_id"].drop_duplicates().tolist()
    print(f"Synthesizing device and IP mappings ...")
    account_device, account_ip = synthesise_devices_ips(sample_accounts)

    rng = np.random.RandomState(SEED)
    print(f"Initializing scenario builder ...")
    builder = ScenarioBuilder(df, account_device, account_ip)

    print(f"Injecting fraud scenarios across train/val/test splits ...")
    # Scenario A: Burst Takeover
    if scenarios_cfg.get("burst_takeover", {}).get("enabled", True):
        cnt = int(scenarios_cfg["burst_takeover"].get("count", 50))
        builder.burst_takeover(partition_counts(cnt), rng, scenarios_cfg["burst_takeover"])

    # Scenario B: Mule Fan-in / Fan-out
    if scenarios_cfg.get("mule_fanin_fanout", {}).get("enabled", True):
        cnt = int(scenarios_cfg["mule_fanin_fanout"].get("count", 20))
        builder.mule_fanin_fanout(partition_counts(cnt), rng, scenarios_cfg["mule_fanin_fanout"])

    # Scenario C: Shared Device Ring
    if scenarios_cfg.get("shared_device_ring", {}).get("enabled", True):
        cnt = int(scenarios_cfg["shared_device_ring"].get("count", 10))
        builder.shared_device_ring(partition_counts(cnt), rng, scenarios_cfg["shared_device_ring"])

    # Scenario D: Structuring
    if scenarios_cfg.get("structuring", {}).get("enabled", True):
        cnt = int(scenarios_cfg["structuring"].get("count", 15))
        builder.structuring(partition_counts(cnt), rng, scenarios_cfg["structuring"])

    # Scenario E: Dormant Reactivation
    if scenarios_cfg.get("dormant_reactivation", {}).get("enabled", True):
        cnt = int(scenarios_cfg["dormant_reactivation"].get("count", 20))
        builder.dormant_reactivation(partition_counts(cnt), rng, scenarios_cfg["dormant_reactivation"])

    print(f"Injecting hard negative scenarios across train/val/test splits ...")
    # Payroll
    if hard_cfg.get("payroll", {}).get("enabled", True):
        cnt = int(hard_cfg["payroll"].get("count", 20))
        builder.payroll(partition_counts(cnt), rng, hard_cfg["payroll"])

    # Merchant high fan-in
    if hard_cfg.get("merchant_high_fanin", {}).get("enabled", True):
        cnt = int(hard_cfg["merchant_high_fanin"].get("count", 15))
        builder.merchant_high_fanin(partition_counts(cnt), rng, hard_cfg["merchant_high_fanin"])

    # Household shared device
    if hard_cfg.get("household_shared_device", {}).get("enabled", True):
        cnt = int(hard_cfg["household_shared_device"].get("count", 25))
        builder.household_shared_device(partition_counts(cnt), rng, hard_cfg["household_shared_device"])

    # Large legitimate drain
    if hard_cfg.get("large_legitimate_drain", {}).get("enabled", True):
        cnt = int(hard_cfg["large_legitimate_drain"].get("count", 20))
        builder.large_legitimate_drain(partition_counts(cnt), rng, hard_cfg["large_legitimate_drain"])

    # Bill payment burst
    if hard_cfg.get("bill_payment_burst", {}).get("enabled", True):
        cnt = int(hard_cfg["bill_payment_burst"].get("count", 20))
        builder.bill_payment_burst(partition_counts(cnt), rng, hard_cfg["bill_payment_burst"])

    inj = builder.build()
    print(f"Generated {len(inj):,} injected scenario rows")

    print(f"Preparing native PaySim rows ...")
    native = prepare_paysim_rows(df, account_device, account_ip)

    print(f"Merging and chronologically sorting dataset ...")
    combined = pd.concat([native, inj], ignore_index=True)
    combined = combined.sort_values("step").reset_index(drop=True)

    combined["amount"] = combined["amount"].astype(float)
    combined["old_balance_orig"] = combined["old_balance_orig"].astype(float)
    combined["new_balance_orig"] = combined["new_balance_orig"].astype(float)
    return combined


def write_output(df: pd.DataFrame, output: str) -> None:
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        print(f"Writing parquet to {out_path} ...")
        df.to_parquet(out_path, index=False)
        print(f"Successfully wrote {len(df):,} rows to {out_path}")
    except Exception as e:
        print(f"Parquet write failed ({e}); falling back to CSV")
        csv_path = out_path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        print(f"Successfully wrote {len(df):,} rows to {csv_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate realistic scenario dataset")
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--sanity-checks", action="store_true",
                    help="Run Phase 2 sanity checks after generation")
    args = ap.parse_args()

    combined = run(args)
    write_output(combined, args.output)

    if args.sanity_checks:
        from scripts.sanity_checks import run_sanity_checks
        run_sanity_checks(combined)


if __name__ == "__main__":
    main()
