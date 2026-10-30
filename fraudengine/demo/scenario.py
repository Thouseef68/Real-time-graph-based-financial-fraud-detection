"""Scenario builder for The Four-Account Mule Ring live demo."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class DemoScenario:
    """Deterministic generator for the 7 Acts of the mule ring narrative."""

    def __init__(self, config_path: Optional[str] = None, seed: int = 42):
        self.seed = seed
        self.config_path = config_path or str(
            Path(__file__).resolve().parents[2] / "configs" / "demo_mule_ring.yaml"
        )
        self.cfg = self._load_config()
        self.rng = random.Random(seed)

    def _load_config(self) -> Dict[str, Any]:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def generate_events(self) -> List[Dict[str, Any]]:
        """Generate ordered list of scenario events (acts, transactions, and containment steps)."""
        self.rng = random.Random(self.seed)
        events: List[Dict[str, Any]] = []

        actors = self.cfg["actors"]
        mules = actors["mules"]
        household = actors["innocent_household"]
        cashout = actors["cashout"]["account_id"]

        # ─────────────────────────────────────────────────────────────
        # ACT 1: Normal Day
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 1,
            "title": "Act 1: Normal Day",
            "narrative": "Ordinary payments flowing between legitimate customers and merchants across 6 Kafka partitions. All health indicators green; model scores remain well below alert thresholds (< 0.05).",
            "step": 701,
        })

        norm_merchants = ["MERCHANT_GROCERY_99", "MERCHANT_COFFEE_12", "MERCHANT_STREAMING_04", "MERCHANT_FUEL_07"]
        for i in range(1, 7):
            sender = f"CUST_NORM_{i:02d}"
            receiver = norm_merchants[i % len(norm_merchants)]
            amount = round(self.rng.uniform(15.0, 120.0), 2)
            events.append({
                "type": "transaction",
                "act": 1,
                "step": 701,
                "txn_id": f"TXN_ACT1_{i:03d}",
                "account_id": sender,
                "payee_id": receiver,
                "amount": amount,
                "device_id": f"DEV_NORM_{i:02d}",
                "ip_prefix": f"192.168.1.{10+i}",
                "hour_of_day": 11,
                "txn_type": "PAYMENT",
                "is_fraud": 0,
                "description": f"Ordinary retail purchase: ₹{amount:.2f} to {receiver}",
            })

        # Routine household subscription establishing legitimate device on IP 198.51.100.14
        events.append({
            "type": "transaction",
            "act": 1,
            "step": 701,
            "txn_id": "TXN_ACT1_HOUSEHOLD_SUB",
            "account_id": household["account_id"],
            "payee_id": "MERCHANT_STREAMING_04",
            "amount": 19.99,
            "device_id": household["device_id"],
            "ip_prefix": household["ip_prefix"],
            "hour_of_day": 12,
            "txn_type": "PAYMENT",
            "is_fraud": 0,
            "description": "Routine OTT streaming subscription: ₹19.99 from smart TV (legitimate household on 198.51.100.14)",
        })

        # ─────────────────────────────────────────────────────────────
        # ACT 2: Ring Wakes Up
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 2,
            "title": "Act 2: Ring Wakes Up",
            "narrative": "Four dormant accounts (Members A, B, C, D) suddenly reactivate on new devices after 60+ days of silence. The entity graph registers shared infrastructure: Members A & B share an IP; Members B & C share a mobile device.",
            "step": 702,
        })

        # Dormant probes / activations linking devices and IPs in graph
        for key in ["A", "B", "C", "D"]:
            m = mules[key]
            events.append({
                "type": "transaction",
                "act": 2,
                "step": 702,
                "txn_id": f"TXN_ACT2_ACTIVATE_{key}",
                "account_id": m["account_id"],
                "payee_id": "MERCHANT_MOBILE_RECHARGE",
                "amount": 10.0,
                "device_id": m["device_id"],
                "ip_prefix": m["ip_prefix"],
                "hour_of_day": 14,
                "txn_type": "PAYMENT",
                "is_fraud": 0,
                "is_dormant_reactivation": True,
                "dormancy_days": m["dormancy_days"],
                "description": f"Member {key} wakes up: ₹10 test recharge from new device {m['device_id']}",
            })

        # ─────────────────────────────────────────────────────────────
        # ACT 3: Victims Pay
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 3,
            "title": "Act 3: Victims Pay (Fan-In Spike)",
            "narrative": "12 victims of an ongoing investment scam simultaneously send payments of ~₹4,000 each to Member A. Member A's 24h fan-in counter in Redis rapidly climbs from 0 to 12.",
            "step": 703,
        })

        victim_amounts = [
            4200.0, 3850.0, 4100.0, 3900.0, 4500.0, 3750.0,
            4000.0, 4300.0, 3950.0, 4150.0, 3800.0, 4250.0
        ]
        mule_a = mules["A"]
        for idx, amt in enumerate(victim_amounts, 1):
            victim_id = f"CUST_VICTIM_{idx:02d}"
            events.append({
                "type": "transaction",
                "act": 3,
                "step": 703,
                "txn_id": f"TXN_ACT3_VIC_{idx:02d}",
                "account_id": victim_id,
                "payee_id": mule_a["account_id"],
                "amount": amt,
                "device_id": f"DEV_VIC_{idx:02d}",
                "ip_prefix": f"172.16.{idx}.2",
                "hour_of_day": 15,
                "txn_type": "TRANSFER",
                "is_fraud": 1,
                "fanin_expected": idx,
                "description": f"Victim {idx:02d} pays ₹{amt:,.0f} to Member A (Fan-In count -> {idx})",
            })

        # ─────────────────────────────────────────────────────────────
        # ACT 4: Layering
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 4,
            "title": "Act 4: Layering (Pass-Through Hops)",
            "narrative": "To obfuscate the scam proceeds, money hops rapidly through the ring: A -> B -> C -> D within minutes. Outflow/inflow ratio approaches 98%, triggering high-risk pass-through flags in Redis and Graph.",
            "step": 704,
        })

        layering_hops = [
            ("A", "B", 48000.0, "TXN_ACT4_HOP_AB"),
            ("B", "C", 47500.0, "TXN_ACT4_HOP_BC"),
            ("C", "D", 47000.0, "TXN_ACT4_HOP_CD"),
        ]

        for s_key, r_key, hop_amt, tid in layering_hops:
            s = mules[s_key]
            r = mules[r_key]
            events.append({
                "type": "transaction",
                "act": 4,
                "step": 704,
                "txn_id": tid,
                "account_id": s["account_id"],
                "payee_id": r["account_id"],
                "amount": hop_amt,
                "device_id": s["device_id"],
                "ip_prefix": s["ip_prefix"],
                "hour_of_day": 16,
                "txn_type": "TRANSFER",
                "is_fraud": 1,
                "is_passthrough": True,
                "description": f"Layering Hop: Member {s_key} forwards ₹{hop_amt:,.0f} to Member {r_key}",
            })

        # ─────────────────────────────────────────────────────────────
        # ACT 5: Detection
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 5,
            "title": "Act 5: Real-Time Detection & SHAP Explanations",
            "narrative": "The real XGBoost engine and rules evaluate the cumulative feature state. Risk score spikes to 0.94, escalating directly to BLOCK with clear, plain-English SHAP reason cards.",
            "step": 705,
        })

        # Final trigger transaction that elevates Member A to confirmed BLOCK
        events.append({
            "type": "transaction",
            "act": 5,
            "step": 705,
            "txn_id": "TXN_ACT5_DETECT_A",
            "account_id": mule_a["account_id"],
            "payee_id": "MERCHANT_UNREGISTERED_RELOAD",
            "amount": 25000.0,
            "device_id": mule_a["device_id"],
            "ip_prefix": mule_a["ip_prefix"],
            "hour_of_day": 16,
            "txn_type": "TRANSFER",
            "is_fraud": 1,
            "dormancy_days": 65.0,
            "force_flag": True,
            "description": "Member A attempts additional fund siphon; Scorer triggers confirmed BLOCK tier",
        })

        # ─────────────────────────────────────────────────────────────
        # ACT 6: Containment
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 6,
            "title": "Act 6: Graph-Based Containment & Precision Isolation",
            "narrative": "On confirmed BLOCK of Member A, the automated graph containment policy executes. Members B, C, D are placed on HOLD via shared device/IP links. The innocent household neighbor sharing A's IP is reviewed and tagged for MONITORING only.",
            "step": 706,
        })

        events.append({
            "type": "containment_step",
            "act": 6,
            "step": 706,
            "target_account": mule_a["account_id"],
            "description": "Automated containment: Block Member A, Hold B/C/D, Monitor innocent household",
        })

        # Household tests their card: transaction succeeds without blockage
        events.append({
            "type": "transaction",
            "act": 6,
            "step": 706,
            "txn_id": "TXN_ACT6_HOUSEHOLD_GROCERY",
            "account_id": household["account_id"],
            "payee_id": "MERCHANT_SUPERMARKET_SAFE",
            "amount": 145.50,
            "device_id": household["device_id"],
            "ip_prefix": household["ip_prefix"],
            "hour_of_day": 17,
            "txn_type": "PAYMENT",
            "is_fraud": 0,
            "description": "Innocent household neighbor buys groceries: ₹145.50 authorized (precision proof)",
        })

        # ─────────────────────────────────────────────────────────────
        # ACT 7: Cash-Out Attempt
        # ─────────────────────────────────────────────────────────────
        events.append({
            "type": "narrative_step",
            "act": 7,
            "title": "Act 7: Instant Cash-Out Interception",
            "narrative": "Member D attempts to withdraw the remaining ₹46,000 to an external crypto cash-out gateway. Pre-scoring Redis blocklist check intercepts and declines the transfer in < 2ms.",
            "step": 707,
        })

        mule_d = mules["D"]
        events.append({
            "type": "transaction",
            "act": 7,
            "step": 707,
            "txn_id": "TXN_ACT7_CASHOUT_D",
            "account_id": mule_d["account_id"],
            "payee_id": cashout,
            "amount": 46000.0,
            "device_id": mule_d["device_id"],
            "ip_prefix": mule_d["ip_prefix"],
            "hour_of_day": 18,
            "txn_type": "TRANSFER",
            "is_fraud": 1,
            "description": "Member D attempts external cash-out of ₹46,000; instantly intercepted by pre-score blocklist",
        })

        return events
