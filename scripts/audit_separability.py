"""R1: Injection Separability Audit Script.

Computes:
1. Two-sample Kolmogorov-Smirnov (KS) test statistics for `amount`, `old_balance_orig`,
   and `new_balance_orig` between each injected scenario's transactions and legitimate
   transactions of the SAME txn_type (e.g. TRANSFER vs legitimate TRANSFER).
2. XGBoost classification models trained on each feature group individually:
   - amount_balance_only
   - base
   - velocity
   - behavioural
   - device_network
   - graph
   Evaluated on injected fraud rows vs legitimate background rows of the same type.
   Reports PR-AUC per group per scenario.
3. Flags any scenario where a non-intended group achieves PR-AUC > 0.90.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FEATURE_GROUPS = {
    "amount_balance_only": ["amount", "amount_to_balance"],
    "base": [
        "amount", "type_code", "amount_to_balance", "orig_drained",
        "new_balance_to_old", "balance_change_ratio"
    ],
    "velocity": [
        "count_1h", "sum_1h", "distinct_payees_1h", "amount_vs_sum_1h",
        "count_6h", "sum_6h", "distinct_payees_6h", "amount_vs_sum_6h",
        "count_24h", "sum_24h", "distinct_payees_24h", "amount_vs_sum_24h"
    ],
    "behavioural": [
        "amount_zscore", "new_payee_flag", "payee_first_seen_age",
        "hour_deviation", "time_since_last_txn", "dormancy_days",
        "device_count", "ip_prefix_count"
    ],
    "device_network": [
        "is_new_device", "accounts_per_device", "devices_per_account",
        "ip_prefix_sharing_count", "device_first_seen_age"
    ],
    "graph": [
        "payee_fan_in_1h", "payee_fan_in_24h", "payee_outflow_inflow_ratio_24h",
        "payee_pass_through_flag", "is_merchant", "fraud_exposure_2hop", "degree", "pagerank"
    ],
}

# The intended primary detection signal per scenario
INTENDED_SIGNALS = {
    "structuring": ["amount_balance_only", "base", "velocity"],
    "burst_takeover": ["velocity", "device_network", "behavioural"],
    "mule_fanin_fanout": ["graph", "velocity"],
    "shared_device_ring": ["device_network", "graph"],
    "dormant_reactivation": ["behavioural", "base"],
}


def run_audit(output_file: str = "results_v2/separability_audit_before.json") -> Dict[str, Any]:
    logger.info("=== Starting R1 Injection Separability Audit ===")
    
    # 1. Load train and test features
    train_df = pd.read_parquet(ROOT / "data" / "cache" / "train_features.parquet")
    test_df = pd.read_parquet(ROOT / "data" / "cache" / "test_features.parquet")
    logger.info(f"Loaded train ({len(train_df):,} rows) and test ({len(test_df):,} rows)")

    # Load raw scenarios for exact old/new balance distributions
    scenarios_df = pd.read_parquet(ROOT / "data" / "scenarios.parquet",
                                   columns=["txn_id", "txn_type", "amount", "old_balance_orig", "new_balance_orig", "label", "scenario"])
    
    # Legit background by txn_type
    legit_by_type = {}
    for t_type in ["TRANSFER", "CASH_OUT", "PAYMENT"]:
        legit_by_type[t_type] = scenarios_df[(scenarios_df["label"] == 0) & (scenarios_df["txn_type"] == t_type)]
    
    logger.info("Computing per-scenario KS statistics against legitimate traffic of same txn_type ...")
    ks_results = {}
    injected_scenarios = [s for s in scenarios_df["scenario"].unique() if s != "paysim_native"]

    for sc in injected_scenarios:
        sc_data = scenarios_df[scenarios_df["scenario"] == sc]
        # Predominant txn_type
        top_type = sc_data["txn_type"].mode().iloc[0] if len(sc_data) > 0 else "TRANSFER"
        legit_ref = legit_by_type.get(top_type, legit_by_type["TRANSFER"])

        # KS tests
        ks_amt = ks_2samp(sc_data["amount"], legit_ref["amount"])
        ks_old_bal = ks_2samp(sc_data["old_balance_orig"], legit_ref["old_balance_orig"])
        ks_new_bal = ks_2samp(sc_data["new_balance_orig"], legit_ref["new_balance_orig"])

        ks_results[sc] = {
            "txn_type": top_type,
            "n_injected": len(sc_data),
            "amount_ks_stat": round(float(ks_amt.statistic), 4),
            "amount_pvalue": float(ks_amt.pvalue),
            "old_balance_ks_stat": round(float(ks_old_bal.statistic), 4),
            "old_balance_pvalue": float(ks_old_bal.pvalue),
            "new_balance_ks_stat": round(float(ks_new_bal.statistic), 4),
            "new_balance_pvalue": float(ks_new_bal.pvalue),
        }
        logger.info(f"Scenario [{sc}] ({top_type}) -> Amount KS: {ks_amt.statistic:.4f}, OldBal KS: {ks_old_bal.statistic:.4f}")

    # 2. Evaluate single-group XGBoost models on injected rows vs legit
    logger.info("Evaluating XGBoost PR-AUC per feature group per injected scenario ...")
    pr_auc_results = {}
    flaws_detected = []

    fraud_scenarios = [sc for sc in injected_scenarios if (scenarios_df[scenarios_df["scenario"] == sc]["label"] == 1).any()]

    # Training set legitimate reference (subsample for fast training)
    train_legit = train_df[train_df["label"] == 0]
    test_legit = test_df[test_df["label"] == 0]

    for sc in fraud_scenarios:
        pr_auc_results[sc] = {}
        sc_train_fraud = train_df[(train_df["scenario"] == sc) & (train_df["label"] == 1)]
        sc_test_fraud = test_df[(test_df["scenario"] == sc) & (test_df["label"] == 1)]

        if len(sc_test_fraud) == 0:
            logger.warning(f"Scenario {sc} has 0 test instances, skipping.")
            continue

        # Build scenario-specific evaluation set: this scenario fraud vs legit test rows
        eval_train = pd.concat([sc_train_fraud, train_legit.sample(min(len(train_legit), 20000), random_state=42)])
        eval_test = pd.concat([sc_test_fraud, test_legit])

        y_tr = eval_train["label"].to_numpy(dtype=int)
        y_te = eval_test["label"].to_numpy(dtype=int)

        spw = float((y_tr == 0).sum() / max(1, (y_tr == 1).sum()))

        intended = INTENDED_SIGNALS.get(sc, [])

        for grp_name, feat_cols in FEATURE_GROUPS.items():
            avail_cols = [c for c in feat_cols if c in eval_train.columns]
            X_tr = eval_train[avail_cols].fillna(0).to_numpy(dtype=np.float32)
            X_te = eval_test[avail_cols].fillna(0).to_numpy(dtype=np.float32)

            clf = XGBClassifier(
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                scale_pos_weight=min(50.0, spw),
                tree_method="hist",
                random_state=42,
                n_jobs=-1,
            )
            clf.fit(X_tr, y_tr)
            preds = clf.predict_proba(X_te)[:, 1]
            score = float(average_precision_score(y_te, preds))
            pr_auc_results[sc][grp_name] = round(score, 4)

            # Check if this group reached > 0.90 when NOT intended
            is_unintended = grp_name not in intended and grp_name in ("amount_balance_only", "base")
            if score > 0.90 and is_unintended:
                flaw_desc = f"Scenario '{sc}' unintended separation on '{grp_name}' (PR-AUC={score:.4f})"
                flaws_detected.append({
                    "scenario": sc,
                    "group": grp_name,
                    "pr_auc": score,
                    "reason": "Injected amount/balance distribution does not match legitimate conditional distribution"
                })
                logger.warning(f"FLAW DETECTED: {flaw_desc}")

    out_data = {
        "ks_statistics": ks_results,
        "group_pr_auc": pr_auc_results,
        "flaws_detected": flaws_detected,
    }

    out_path = ROOT / output_file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out_data, f, indent=2)

    logger.info(f"Audit complete! Saved results to {out_path}")
    logger.info(f"Total generator flaws detected (PR-AUC > 0.9 on unintended base/amount): {len(flaws_detected)}")
    return out_data


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "results_v2/separability_audit_after.json"
    run_audit(output_file=out_file)
