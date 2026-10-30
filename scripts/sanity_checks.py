"""Phase 2: Sanity checks for realistic scenario generator.

Checks:
(a) Train an XGBoost model using ONLY drain features and report its PR-AUC on
    injected-scenario rows. This should be low, demonstrating that injected
    scenarios are not trivially separable by simple account draining.
(b) Kolmogorov-Smirnov (KS) statistics comparing amount and balance distributions
    of injected fraud vs legitimate traffic.
(c) Summary table of transaction counts, fraud counts, and fraud rate by split
    and scenario.

Outputs are written to results_v2/phase2_sanity_checks.json and printed to stdout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results_v2"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = RESULTS_DIR / "phase2_sanity_checks.json"


def compute_drain_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute only drain-based features."""
    old_bal = df["old_balance_orig"].astype(float)
    new_bal = df["new_balance_orig"].astype(float)
    amount = df["amount"].astype(float)

    orig_drained = ((old_bal > 0) & (new_bal == 0.0)).astype(float)
    amount_to_balance = amount / (old_bal + 1.0)
    return pd.DataFrame({
        "orig_drained": orig_drained,
        "amount_to_balance": amount_to_balance,
    }, index=df.index)


def check_drain_model(df: pd.DataFrame) -> Dict[str, Any]:
    """Train XGBoost using ONLY drain features and evaluate on injected scenarios."""
    print("\n--- Check (a): Drain-Only Model on Injected Scenarios ---")

    # Train on training split
    train_mask = df["split"] == "train"
    train_df = df[train_mask]
    X_train = compute_drain_features(train_df)
    y_train = train_df["label"].astype(int)

    # Subsample training data if too large to ensure fast, deterministic fit
    if len(X_train) > 200000:
        sample_idx = train_df.sample(200000, random_state=42).index
        X_train = X_train.loc[sample_idx]
        y_train = y_train.loc[sample_idx]

    model = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        random_state=42,
        eval_metric="logloss",
        tree_method="hist",
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # Evaluate on injected scenario rows (both fraud and hard negatives)
    injected_mask = df["scenario"] != "paysim_native"
    inj_df = df[injected_mask]
    X_inj = compute_drain_features(inj_df)
    y_inj = inj_df["label"].astype(int).to_numpy()

    y_pred_proba = model.predict_proba(X_inj)[:, 1]

    pr_auc = float(average_precision_score(y_inj, y_pred_proba))
    roc_auc = float(roc_auc_score(y_inj, y_pred_proba))
    fraud_rate_inj = float(np.mean(y_inj))

    print(f"Injected rows count: {len(inj_df):,}")
    print(f"Injected fraud rate: {fraud_rate_inj:.4%}")
    print(f"Drain-only XGBoost PR-AUC on injected rows: {pr_auc:.4f}")
    print(f"Drain-only XGBoost ROC-AUC on injected rows: {roc_auc:.4f}")

    # For comparison, evaluate on native test fraud
    native_test_mask = (df["split"] == "test") & (df["scenario"] == "paysim_native")
    native_test_df = df[native_test_mask]
    if len(native_test_df) > 0:
        X_nat = compute_drain_features(native_test_df)
        y_nat = native_test_df["label"].astype(int).to_numpy()
        y_nat_proba = model.predict_proba(X_nat)[:, 1]
        native_pr_auc = float(average_precision_score(y_nat, y_nat_proba))
        print(f"Drain-only XGBoost PR-AUC on native test rows: {native_pr_auc:.4f}")
    else:
        native_pr_auc = None

    passed = pr_auc < 0.40  # Injected scenarios should not be trivially drain-separable
    print(f"Sanity Check (a) {'PASSED' if passed else 'FAILED'}: PR-AUC {pr_auc:.4f} < 0.40")

    return {
        "passed": bool(passed),
        "injected_rows": int(len(inj_df)),
        "injected_fraud_rate": fraud_rate_inj,
        "drain_only_pr_auc_injected": pr_auc,
        "drain_only_roc_auc_injected": roc_auc,
        "drain_only_pr_auc_native_test": native_pr_auc,
    }


def check_ks_statistics(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute KS test comparing amount and balance of injected fraud vs legitimate."""
    print("\n--- Check (b): Kolmogorov-Smirnov Distribution Tests ---")

    legit_mask = df["label"] == 0
    injected_fraud_mask = (df["scenario"] != "paysim_native") & (df["label"] == 1)

    legit_amounts = df.loc[legit_mask, "amount"].astype(float).to_numpy()
    inj_fraud_amounts = df.loc[injected_fraud_mask, "amount"].astype(float).to_numpy()

    legit_balances = df.loc[legit_mask, "old_balance_orig"].astype(float).to_numpy()
    inj_fraud_balances = df.loc[injected_fraud_mask, "old_balance_orig"].astype(float).to_numpy()

    # Subsample legit for fast KS computation
    if len(legit_amounts) > 100000:
        rng = np.random.RandomState(42)
        idx = rng.choice(len(legit_amounts), size=100000, replace=False)
        legit_amounts_sample = legit_amounts[idx]
        legit_balances_sample = legit_balances[idx]
    else:
        legit_amounts_sample = legit_amounts
        legit_balances_sample = legit_balances

    ks_amount = stats.ks_2samp(inj_fraud_amounts, legit_amounts_sample)
    ks_balance = stats.ks_2samp(inj_fraud_balances, legit_balances_sample)

    print(f"Injected fraud amount vs Legit amount: KS stat = {ks_amount.statistic:.4f}, p-value = {ks_amount.pvalue:.4e}")
    print(f"Injected fraud balance vs Legit balance: KS stat = {ks_balance.statistic:.4f}, p-value = {ks_balance.pvalue:.4e}")

    return {
        "amount_ks_statistic": float(ks_amount.statistic),
        "amount_p_value": float(ks_amount.pvalue),
        "balance_ks_statistic": float(ks_balance.statistic),
        "balance_p_value": float(ks_balance.pvalue),
        "injected_fraud_count": int(len(inj_fraud_amounts)),
        "legit_sample_count": int(len(legit_amounts_sample)),
    }


def check_counts_and_fraud_rates(df: pd.DataFrame) -> Dict[str, Any]:
    """Generate table of counts and fraud rate by split and scenario."""
    print("\n--- Check (c): Counts and Fraud Rate by Split and Scenario ---")

    grouped = df.groupby(["split", "scenario"]).agg(
        total_txns=("label", "count"),
        fraud_txns=("label", lambda x: int((x == 1).sum())),
        fraud_rate=("label", "mean"),
        unique_groups=("group_id", "nunique"),
    ).reset_index()

    grouped["fraud_rate_pct"] = (grouped["fraud_rate"] * 100).round(2)
    print(grouped.to_string(index=False))

    # Also build markdown table string
    md_lines = [
        "| Split | Scenario | Total Txns | Fraud Txns | Fraud Rate | Unique Groups |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in grouped.iterrows():
        md_lines.append(
            f"| {r['split']} | {r['scenario']} | {r['total_txns']:,} | {r['fraud_txns']:,} | {r['fraud_rate_pct']:.2f}% | {r['unique_groups']:,} |"
        )
    md_table = "\n".join(md_lines)

    return {
        "records": grouped.to_dict(orient="records"),
        "markdown_table": md_table,
    }


def run_sanity_checks(df: pd.DataFrame) -> Dict[str, Any]:
    """Execute all Phase 2 sanity checks and record results."""
    print(f"Running Phase 2 Sanity Checks on dataset with {len(df):,} rows ...")
    drain_results = check_drain_model(df)
    ks_results = check_ks_statistics(df)
    counts_results = check_counts_and_fraud_rates(df)

    summary = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "total_dataset_rows": int(len(df)),
        "check_a_drain_model": drain_results,
        "check_b_ks_statistics": ks_results,
        "check_c_counts_by_split_and_scenario": counts_results,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSaved sanity check results to {OUTPUT_FILE}")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Phase 2 sanity checks")
    parser.add_argument("--data", default="data/scenarios.parquet", help="Path to scenarios parquet/csv")
    args = parser.parse_args()

    p = Path(args.data)
    if not p.exists():
        p_csv = p.with_suffix(".csv")
        if p_csv.exists():
            p = p_csv
        else:
            raise FileNotFoundError(f"Could not find dataset at {p} or {p_csv}")

    print(f"Loading {p} ...")
    if p.suffix == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)

    run_sanity_checks(df)
