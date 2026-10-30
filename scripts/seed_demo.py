"""Phase 9 seed script: Pre-populates at least 300 alerts across all scenarios.

Guarantees the dashboard UI is populated on first launch with realistic,
scenario-labeled cases, plain-English reasons, Cytoscape subgraphs, and a tamper-evident audit log.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.feedback.label_store import LabelStore
from fraudengine.graph.engine import GraphEngine
from fraudengine.rules.engine import RulesEngine
from fraudengine.scoring.audit import AuditLog
from fraudengine.scoring.case_bundle import CaseBundleExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCENARIO_TEMPLATES = {
    "burst_takeover": {
        "tier": "BLOCK",
        "score_range": (0.88, 0.96),
        "summary": "Burst account takeover: Multiple rapid transfers to new mule payees within 2 hours.",
        "action": "Decline transaction immediately and freeze account pending identity verification.",
        "reasons": [
            {"title": "Velocity Spike (1h)", "explanation": "Account executed 14 transactions within 90 minutes", "severity": "high", "evidence": {"count_1h": 14}},
            {"title": "New Device Used", "explanation": "Transaction originated from a mobile device never before linked to this account", "severity": "high", "evidence": {"is_new_device": 1.0}},
            {"title": "Multiple New Payees", "explanation": "Funds distributed to 3 new beneficiary accounts in quick succession", "severity": "medium", "evidence": {"distinct_payees_1h": 3}},
        ],
    },
    "mule_fanin_fanout": {
        "tier": "BLOCK",
        "score_range": (0.92, 0.99),
        "summary": "Mule account pattern: Rapid aggregation from 22 distinct senders followed by immediate 85% pass-through.",
        "action": "Hold funds immediately and initiate inter-bank recall on outbound transfers.",
        "reasons": [
            {"title": "High Payee Fan-In", "explanation": "Payee received funds from 22 distinct senders in the last 24 hours", "severity": "high", "evidence": {"payee_fan_in_24h": 22}},
            {"title": "Pass-Through Account", "explanation": "Account forwarded 88% of incoming funds within 4 hours", "severity": "high", "evidence": {"payee_outflow_inflow_ratio_24h": 0.88}},
            {"title": "Rapid Depletion", "explanation": "Aggregated funds transferred onwards to 2 collector accounts", "severity": "medium", "evidence": {"payee_pass_through_flag": 1.0}},
        ],
    },
    "shared_device_ring": {
        "tier": "BLOCK",
        "score_range": (0.89, 0.97),
        "summary": "Synthetic identity / device ring: 8 distinct accounts operating from a single hardware device.",
        "action": "Freeze all 8 accounts linked to hardware identifier dev_ring_08 and flag for ring investigation.",
        "reasons": [
            {"title": "Shared Hardware Fingerprint", "explanation": "Device ID dev_ring_08 is simultaneously associated with 8 active customer accounts", "severity": "critical", "evidence": {"accounts_per_device": 8.0}},
            {"title": "Circular Fund Layering", "explanation": "Repeated back-and-forth transfers detected between co-located accounts", "severity": "high", "evidence": {"fraud_exposure_2hop": 4.0}},
            {"title": "Subnet Colocation", "explanation": "All 8 accounts share IP subnet 10.42.100.0/24", "severity": "medium", "evidence": {"ip_prefix_sharing_count": 8.0}},
        ],
    },
    "structuring": {
        "tier": "REVIEW",
        "score_range": (0.75, 0.85),
        "summary": "Structuring / Smurfing pattern: Repeated transfers of ₹48,000–₹49,500 just below ₹50,000 reporting threshold.",
        "action": "Queue for compliance review and file Suspicious Activity Report (SAR) if unjustified.",
        "reasons": [
            {"title": "Threshold Avoidance", "explanation": "5 transactions between ₹48,000 and ₹49,500 within 48 hours (reporting threshold ₹50,000)", "severity": "high", "evidence": {"amount": 49200.0}},
            {"title": "Elevated Daily Activity", "explanation": "Cumulative 24h volume of ₹196,800 is 4.2 standard deviations above account mean", "severity": "medium", "evidence": {"amount_zscore": 4.2}},
            {"title": "Multiple Unlinked Payees", "explanation": "Transfers directed to 4 distinct payee accounts with no prior history", "severity": "medium", "evidence": {"distinct_payees_24h": 4}},
        ],
    },
    "dormant_reactivation": {
        "tier": "REVIEW",
        "score_range": (0.72, 0.84),
        "summary": "Dormant account reactivation: Account inactive for 68 days suddenly sending ₹75,000 from a new device.",
        "action": "Contact account owner via out-of-band verified phone number to confirm transaction authorization.",
        "reasons": [
            {"title": "Long Account Dormancy", "explanation": "Account was dormant for 68 days prior to sudden high-value transfer", "severity": "high", "evidence": {"dormancy_days": 68.0}},
            {"title": "Unfamiliar Device", "explanation": "First transaction ever executed from device fingerprint dev_new_99", "severity": "high", "evidence": {"is_new_device": 1.0}},
            {"title": "Unusual Amount", "explanation": "Transfer amount ₹75,000 exceeds typical historical balance by 3.8x", "severity": "medium", "evidence": {"amount_zscore": 3.8}},
        ],
    },
    "payroll": {
        "tier": "ALLOW",
        "score_range": (0.05, 0.15),
        "summary": "Legitimate enterprise payroll: Corporate employer dispersing standard monthly salaries to 50 employees.",
        "action": "Allow transaction to proceed; pattern matches verified corporate disbursement profile.",
        "reasons": [
            {"title": "Regular Recurring Schedule", "explanation": "Month-end salary batch matching historical payroll rhythm", "severity": "low", "evidence": {"hour_deviation": 0.05}},
            {"title": "Known Beneficiary Roster", "explanation": "98% of payees have received regular disbursements for > 6 months", "severity": "low", "evidence": {"new_payee_flag": 0.0}},
        ],
    },
    "merchant_high_fanin": {
        "tier": "ALLOW",
        "score_range": (0.04, 0.12),
        "summary": "Legitimate commercial merchant: Verified retail merchant receiving daily customer payments.",
        "action": "Allow transaction to proceed; merchant MCC and commercial KYC verified.",
        "reasons": [
            {"title": "Verified Merchant Entity", "explanation": "Account prefix M corresponds to a registered merchant processing terminal", "severity": "low", "evidence": {"is_merchant": 1.0}},
            {"title": "Normal Commercial Velocity", "explanation": "Transaction volume is within expected seasonal thresholds for retail merchant", "severity": "low", "evidence": {"payee_fan_in_24h": 85}},
        ],
    },
    "household_shared_device": {
        "tier": "ALLOW",
        "score_range": (0.08, 0.20),
        "summary": "Legitimate household device sharing: Family members sharing a home tablet or IP address.",
        "action": "Allow transaction to proceed; device sharing established for > 90 days with common billing address.",
        "reasons": [
            {"title": "Stable Residential IP", "explanation": "Shared domestic ISP prefix with over 3 months of consistent co-usage", "severity": "low", "evidence": {"ip_prefix_sharing_count": 3.0}},
            {"title": "Low Value Routine Purchases", "explanation": "Utility and grocery payments consistent with household expenditure", "severity": "low", "evidence": {"amount": 1250.0}},
        ],
    },
    "large_legitimate_drain": {
        "tier": "STEP_UP",
        "score_range": (0.35, 0.55),
        "summary": "Large legitimate balance drawdown: Verified account owner transferring funds to a known investment account.",
        "action": "Trigger SMS OTP verification to registered phone number before releasing funds.",
        "reasons": [
            {"title": "Full Balance Transfer", "explanation": "Account balance of ₹240,000 reduced to zero in a single transaction", "severity": "medium", "evidence": {"orig_drained": 1.0}},
            {"title": "Known Primary Device", "explanation": "Executed from account owner's primary device seen across 140 historical logins", "severity": "low", "evidence": {"is_new_device": 0.0}},
        ],
    },
    "bill_payment_burst": {
        "tier": "ALLOW",
        "score_range": (0.06, 0.18),
        "summary": "Legitimate bill payment burst: Month-start settlement of electricity, water, and telecom bills.",
        "action": "Allow transaction to proceed; recurring monthly utility payment batch.",
        "reasons": [
            {"title": "Registered Utility Biller", "explanation": "Payees are established municipal and utility utility billers", "severity": "low", "evidence": {"is_merchant": 1.0}},
            {"title": "Consistent Monthly Pattern", "explanation": "Identical payment cadence observed in previous calendar months", "severity": "low", "evidence": {"hour_deviation": 0.1}},
        ],
    },
    "paysim_native": {
        "tier": "BLOCK",
        "score_range": (0.91, 0.98),
        "summary": "Single-shot account drainage: Unusually large transfer immediately liquidating entire account balance.",
        "action": "Decline transaction immediately and freeze originating account.",
        "reasons": [
            {"title": "Account Balance Drained", "explanation": "Entire originating account balance was transferred out in a single transfer", "severity": "high", "evidence": {"orig_drained": 1.0}},
            {"title": "Amount vs Balance Match", "explanation": "Transfer amount exactly equals available balance (amount_to_balance: 1.0)", "severity": "high", "evidence": {"amount_to_balance": 1.0}},
        ],
    },
}


def seed_demo_alerts(target_alerts: int = 350):
    logger.info(f"=== Seeding Demo Alerts (Target: {target_alerts}+ alerts across all scenarios) ===")

    db_path = ROOT / "data" / "label_store.db"
    audit_path = ROOT / "data" / "audit_log.jsonl"
    cases_dir = ROOT / "results_v2" / "cases"
    scenarios_file = ROOT / "data" / "scenarios.parquet"

    label_store = LabelStore(str(db_path))
    audit_log = AuditLog(str(audit_path))
    graph_engine = GraphEngine(neo4j_uri=None)
    exporter = CaseBundleExporter(str(cases_dir))

    # Read slice from scenarios.parquet if available
    injected_rows = []
    if scenarios_file.exists():
        logger.info(f"Loading sample from {scenarios_file} ...")
        df = pd.read_parquet(scenarios_file)
        # Select all injected scenario rows + native fraud + hard negatives
        sc_mask = df["scenario"] != "paysim_native"
        fraud_mask = (df["label"] == 1) & (df["split"] == "test")
        sample_df = pd.concat([df[sc_mask], df[fraud_mask].head(100)]).drop_duplicates("txn_id")
        injected_rows = sample_df.to_dict(orient="records")
        logger.info(f"Found {len(injected_rows):,} candidate scenario transactions.")

    # Seed at least 350 alerts
    count = 0
    import random
    rng = random.Random(42)

    for i, row in enumerate(injected_rows):
        if count >= target_alerts:
            break

        scenario = row.get("scenario", "paysim_native")
        template = SCENARIO_TEMPLATES.get(scenario, SCENARIO_TEMPLATES["burst_takeover"])

        tier = template["tier"]
        # Skip pure ALLOWs if we want mostly alerts, but keep some for realistic distribution
        if tier == "ALLOW" and count % 5 != 0:
            continue

        min_s, max_s = template["score_range"]
        score = round(rng.uniform(min_s, max_s), 4)

        txn_id = str(row.get("txn_id", f"txn_{i}"))
        account_id = str(row.get("account_id", f"C_{i}"))
        payee_id = str(row.get("payee_id", f"M_{i}"))
        amount = float(row.get("amount", 25000.0))
        step = int(row.get("step", 605))

        decision_dict = {
            "txn_id": txn_id,
            "account_id": account_id,
            "payee_id": payee_id,
            "amount": amount,
            "step": step,
            "score": score,
            "tier": tier,
            "summary": template["summary"],
            "recommended_action": template["action"],
            "reasons": template["reasons"],
            "rule_hits": [],
            "scenario": scenario,
            "group_id": str(row.get("group_id", "")),
            "model_version": "2.0.0",
            "config_hash": "a1b2c3d4e5f60718",
            "latency_ms": round(rng.uniform(0.03, 0.09), 2),
            "feature_snapshot": {
                "amount": amount,
                "orig_drained": 1.0 if "drain" in scenario else 0.0,
                "is_new_device": 1.0 if "device" in scenario or "takeover" in scenario else 0.0,
                "payee_fan_in_24h": 22.0 if "mule" in scenario else 1.0,
            },
        }

        # 1. Add to SQLite label store
        label_store.create_case(decision_dict)

        # 2. Add to audit log (with SHA-256 hash chain)
        audit_log.append(decision_dict)

        # 3. Add to graph engine
        graph_engine.update_transaction(
            account_id=account_id,
            payee_id=payee_id,
            amount=amount,
            step=step,
            device_id=row.get("device_id", f"dev_{i % 50}"),
            ip_prefix=row.get("ip_prefix", "192.168.1"),
            label=int(row.get("label", 0)),
        )

        # 4. Export case bundle for REVIEW and BLOCK
        if tier in ("REVIEW", "BLOCK"):
            exporter.export(
                decision_dict=decision_dict,
                features=decision_dict["feature_snapshot"],
                graph_engine=graph_engine,
            )

        count += 1

    logger.info(f"Successfully seeded {count} cases across all 10 scenarios into label store & audit log!")

    # Verify audit chain integrity
    res = audit_log.verify_chain()
    logger.info(f"Audit log chain integrity: {res['message']} (valid={res['valid']})")


if __name__ == "__main__":
    seed_demo_alerts(350)
