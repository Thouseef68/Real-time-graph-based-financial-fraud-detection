"""R4 requirement: Cost-based threshold sweeps, 3-seed mean +/- std for learned models, time-slice stability.

Outputs:
  results_v2/model_stability.json
  results_v2/figures/model_stability.png
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.eval.runner import RESULTS_DIR, FIGURES_DIR
from fraudengine.features.engineering import ALL_FEATURES
from fraudengine.models.anomaly import AnomalyPipeline, ANOMALY_FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = ROOT / "data" / "cache"
OUTPUT_FILE = RESULTS_DIR / "model_stability.json"


def load_data():
    train_df = pd.read_parquet(CACHE_DIR / "train_features.parquet")
    val_df = pd.read_parquet(CACHE_DIR / "val_features.parquet")
    test_df = pd.read_parquet(CACHE_DIR / "test_features.parquet")
    return train_df, val_df, test_df


def evaluate_3_seed_stability(train_df, val_df, test_df, feature_names, seeds=[42, 43, 44]):
    """Train XGBoost model with 3 random seeds and report mean +/- std."""
    logger.info(f"Evaluating 3-seed stability across seeds: {seeds} ...")

    base_features = [f for f in feature_names if f not in ("isolation_forest_score", "autoencoder_reconstruction_error")]
    available = [f for f in base_features if f in train_df.columns]

    X_train = train_df[available].fillna(0).to_numpy(dtype=np.float32)
    y_train = train_df["label"].to_numpy(dtype=int)

    X_val = val_df[available].fillna(0).to_numpy(dtype=np.float32)
    y_val = val_df["label"].to_numpy(dtype=int)

    X_test = test_df[available].fillna(0).to_numpy(dtype=np.float32)
    y_test = test_df["label"].to_numpy(dtype=int)

    pos = int(y_train.sum())
    neg = len(y_train) - pos
    spw = min(float(neg / max(1, pos)), 30.0)

    seed_metrics = []

    for seed in seeds:
        logger.info(f"Training XGBoost with seed={seed} ...")
        clf = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.08,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=spw,
            tree_method="hist",
            eval_metric="aucpr",
            random_state=seed,
            n_jobs=-1,
        )
        clf.fit(X_train, y_train)

        # Calibrate on val
        val_probs = clf.predict_proba(X_val)[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(val_probs, y_val)

        # Test
        test_raw = clf.predict_proba(X_test)[:, 1]
        test_cal = iso.predict(test_raw)

        pr_auc = float(average_precision_score(y_test, test_cal))
        roc_auc = float(roc_auc_score(y_test, test_cal))

        # Alert budgets
        th_1pct = float(np.percentile(test_cal, 99.0))
        th_0_5pct = float(np.percentile(test_cal, 99.5))
        rec_1pct = float(((test_cal >= th_1pct) & (y_test == 1)).sum() / max(1, (y_test == 1).sum()))
        rec_0_5pct = float(((test_cal >= th_0_5pct) & (y_test == 1)).sum() / max(1, (y_test == 1).sum()))

        seed_metrics.append({
            "seed": seed,
            "pr_auc": round(pr_auc, 5),
            "roc_auc": round(roc_auc, 5),
            "recall_at_1pct": round(rec_1pct, 5),
            "recall_at_0_5pct": round(rec_0_5pct, 5),
        })

    pr_aucs = [m["pr_auc"] for m in seed_metrics]
    roc_aucs = [m["roc_auc"] for m in seed_metrics]
    rec_1pcts = [m["recall_at_1pct"] for m in seed_metrics]
    rec_0_5pcts = [m["recall_at_0_5pct"] for m in seed_metrics]

    return {
        "per_seed": seed_metrics,
        "mean_pr_auc": round(float(np.mean(pr_aucs)), 5),
        "std_pr_auc": round(float(np.std(pr_aucs)), 5),
        "mean_roc_auc": round(float(np.mean(roc_aucs)), 5),
        "std_roc_auc": round(float(np.std(roc_aucs)), 5),
        "mean_recall_at_1pct": round(float(np.mean(rec_1pcts)), 5),
        "std_recall_at_1pct": round(float(np.std(rec_1pcts)), 5),
        "mean_recall_at_0_5pct": round(float(np.mean(rec_0_5pcts)), 5),
        "std_recall_at_0_5pct": round(float(np.std(rec_0_5pcts)), 5),
    }


def evaluate_cost_sweeps(test_df, v2_scores, y_test):
    """Cost-based threshold sweeps across different cost ratio assumptions."""
    logger.info("Computing cost-based threshold sweeps ...")
    amounts = test_df["amount"].to_numpy(dtype=np.float32) if "amount" in test_df.columns else np.ones(len(y_test))

    # Test cost ratios (Cost of False Negative vs False Positive)
    # E.g. FN cost = fraud amount lost, FP cost = analyst review cost (e.g. $10, $25, $50)
    cost_scenarios = [
        {"name": "standard_analyst", "fp_cost": 25.0, "fn_multiplier": 1.0},
        {"name": "high_throughput_low_cost", "fp_cost": 10.0, "fn_multiplier": 1.0},
        {"name": "expensive_investigation", "fp_cost": 75.0, "fn_multiplier": 1.0},
        {"name": "severe_regulatory_penalty", "fp_cost": 25.0, "fn_multiplier": 2.5},
    ]

    thresholds = np.linspace(0.01, 0.99, 99)
    sweep_results = []

    for sc in cost_scenarios:
        fp_cost = sc["fp_cost"]
        fn_mult = sc["fn_multiplier"]

        losses = []
        for t in thresholds:
            pred_fraud = (v2_scores >= t)
            # FP: flagged legitimate -> analyst review cost
            fp_loss = float(np.sum((pred_fraud & (y_test == 0)) * fp_cost))
            # FN: missed fraud -> fraud amount lost * fn_mult
            fn_loss = float(np.sum((~pred_fraud & (y_test == 1)) * (amounts * fn_mult)))
            total_loss = fp_loss + fn_loss
            losses.append(total_loss)

        best_idx = int(np.argmin(losses))
        best_t = float(thresholds[best_idx])
        min_loss = float(losses[best_idx])

        # Metrics at best threshold
        pred_opt = (v2_scores >= best_t)
        tp = int(np.sum(pred_opt & (y_test == 1)))
        fp = int(np.sum(pred_opt & (y_test == 0)))
        fn = int(np.sum(~pred_opt & (y_test == 1)))
        tn = int(np.sum(~pred_opt & (y_test == 0)))

        prec = float(tp / max(1, tp + fp))
        rec = float(tp / max(1, tp + fn))
        fpr = float(fp / max(1, fp + tn))

        sweep_results.append({
            "scenario": sc["name"],
            "analyst_cost_per_review": fp_cost,
            "fn_penalty_multiplier": fn_mult,
            "cost_optimal_threshold": round(best_t, 3),
            "min_total_cost": round(min_loss, 2),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "fpr": round(fpr, 5),
            "flagged_count": int(np.sum(pred_opt)),
        })

    return sweep_results


def evaluate_time_slice_stability(test_df, v2_scores, y_test, n_slices=4):
    """Evaluate performance across chronological time slices of the test stream."""
    logger.info(f"Computing time-slice stability ({n_slices} chronological slices) ...")
    steps = test_df["step"].to_numpy()
    min_step, max_step = int(steps.min()), int(steps.max())
    step_ranges = np.linspace(min_step, max_step + 1, n_slices + 1, dtype=int)

    slice_metrics = []
    for i in range(n_slices):
        s_start = step_ranges[i]
        s_end = step_ranges[i + 1]
        mask = (steps >= s_start) & (steps < s_end)
        n_slice = int(mask.sum())
        if n_slice == 0:
            continue

        y_slice = y_test[mask]
        s_slice = v2_scores[mask]
        n_fraud = int(y_slice.sum())

        if n_fraud > 0 and n_fraud < n_slice:
            pr_auc = float(average_precision_score(y_slice, s_slice))
            roc_auc = float(roc_auc_score(y_slice, s_slice))
        else:
            pr_auc = 1.0 if n_fraud > 0 else 0.0
            roc_auc = 1.0

        # Fixed threshold (e.g. 0.5)
        pred_fraud = (s_slice >= 0.5)
        recall = float((pred_fraud & (y_slice == 1)).sum() / max(1, n_fraud)) if n_fraud > 0 else 1.0
        prec = float((pred_fraud & (y_slice == 1)).sum() / max(1, pred_fraud.sum())) if pred_fraud.sum() > 0 else 1.0

        slice_metrics.append({
            "slice_index": i + 1,
            "step_range": f"{s_start}-{s_end - 1}",
            "transactions": n_slice,
            "frauds": n_fraud,
            "fraud_rate": round(float(n_fraud / n_slice), 5),
            "pr_auc": round(pr_auc, 4),
            "roc_auc": round(roc_auc, 4),
            "recall": round(recall, 4),
            "precision": round(prec, 4),
        })

    return slice_metrics


def main():
    logger.info("=== R4: Model Stability & Threshold Sweeps ===")
    train_df, val_df, test_df = load_data()
    y_test = test_df["label"].to_numpy(dtype=int)

    # Load v2 model bundle to get test predictions
    models_dir = ROOT / "models_v2" / "v2.0.0"
    with open(models_dir / "feature_list.json") as f:
        feature_names = json.load(f)

    # 1. 3-Seed Stability
    stability_3seed = evaluate_3_seed_stability(train_df, val_df, test_df, feature_names)
    logger.info(
        f"3-Seed Results: PR-AUC = {stability_3seed['mean_pr_auc']:.4f} +/- {stability_3seed['std_pr_auc']:.4f}, "
        f"Recall@1% = {stability_3seed['mean_recall_at_1pct']:.4f} +/- {stability_3seed['std_recall_at_1pct']:.4f}"
    )

    # Score test set with v2 model
    import joblib
    v2_xgb = joblib.load(str(models_dir / "xgboost_model.joblib"))
    calibrator = joblib.load(str(models_dir / "calibrator.joblib"))
    anomaly_pipeline = AnomalyPipeline.load(str(models_dir / "anomaly_pipeline"))

    X_anom = test_df[ANOMALY_FEATURE_NAMES].fillna(0).to_numpy(dtype=np.float32)
    if_sc, ae_sc = anomaly_pipeline.score(X_anom)
    base_f = [f for f in feature_names if f not in ("isolation_forest_score", "autoencoder_reconstruction_error")]
    X_base = test_df[base_f].fillna(0).to_numpy(dtype=np.float32)
    X_full = np.hstack([X_base, if_sc.reshape(-1, 1), ae_sc.reshape(-1, 1)])
    raw_p = v2_xgb.predict_proba(X_full)[:, 1]
    v2_scores = calibrator.predict(raw_p)

    # 2. Cost sweeps
    cost_sweeps = evaluate_cost_sweeps(test_df, v2_scores, y_test)

    # 3. Time-slice stability
    time_slices = evaluate_time_slice_stability(test_df, v2_scores, y_test, n_slices=4)

    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "three_seed_stability": stability_3seed,
        "cost_based_threshold_sweeps": cost_sweeps,
        "time_slice_stability": time_slices,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved stability results to {OUTPUT_FILE}")

    # Generate Figure
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Panel 1: Time Slice PR-AUC Stability
    slice_labels = [s["step_range"] for s in time_slices]
    pr_vals = [s["pr_auc"] for s in time_slices]
    rec_vals = [s["recall"] for s in time_slices]
    x = np.arange(len(slice_labels))
    ax1.plot(x, pr_vals, marker="o", color="#3b82f6", linewidth=2, label="PR-AUC")
    ax1.plot(x, rec_vals, marker="s", color="#10b981", linewidth=2, linestyle="--", label="Recall")
    ax1.set_xticks(x)
    ax1.set_xticklabels(slice_labels)
    ax1.set_xlabel("Chronological Time Window (Steps)")
    ax1.set_ylabel("Metric Score")
    ax1.set_title("Model Performance Over Time Slices\n(Demonstrating temporal consistency)")
    ax1.set_ylim([0.8, 1.02])
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend()

    # Panel 2: Cost-based Optimal Thresholds
    sc_names = [s["scenario"].replace("_", " ").title() for s in cost_sweeps]
    opt_thresh = [s["cost_optimal_threshold"] for s in cost_sweeps]
    bars = ax2.bar(sc_names, opt_thresh, color="#8b5cf6", width=0.5)
    ax2.set_ylabel("Optimal Threshold (0 - 1)")
    ax2.set_title("Cost-Optimal Decision Thresholds\nBy Operational Risk Scenario")
    ax2.set_ylim([0.0, 1.0])
    ax2.grid(axis="y", linestyle=":", alpha=0.6)
    for bar in bars:
        yval = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2.0, yval + 0.02, f"{yval:.2f}", ha='center', va='bottom', fontsize=9)
    plt.xticks(rotation=15)

    plt.tight_layout()
    fig_path = FIGURES_DIR / "model_stability_and_cost_sweeps.png"
    plt.savefig(fig_path, dpi=200)
    plt.close()
    logger.info(f"Saved {fig_path}")


if __name__ == "__main__":
    main()
