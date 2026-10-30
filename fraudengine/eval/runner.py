"""Phase 5: Experiment evaluation runner.

Produces results_v2/*.json, results_v2/tables/*.md, results_v2/figures/*.png.
Computes per-scenario and overall metrics with bootstrap CIs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
RESULTS_DIR = ROOT / "results_v2"
TABLES_DIR = RESULTS_DIR / "tables"
FIGURES_DIR = RESULTS_DIR / "figures"

for d in [RESULTS_DIR, TABLES_DIR, FIGURES_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────
# Metric helpers
# ─────────────────────────────────────────────────────────

def pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        return float("nan")
    return float(average_precision_score(y_true, y_score))


def roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, y_score))


def metrics_at_alert_budget(y_true: np.ndarray, y_score: np.ndarray, budget: float) -> Dict[str, float]:
    """Operational Alert Budget Metrics.
    
    Definition:
      An alert budget alpha in (0, 1] (e.g. 1% = 0.01, 0.5% = 0.005) represents the fixed
      operational review capacity of fraud investigators. Transactions are ranked
      descending by predicted score. The top K = floor(alpha * N) transactions are flagged.
      
      - Threshold: Score of the K-th transaction (or cutoff score).
      - Precision@budget: TP / K (share of alerted transactions that are true fraud).
      - Recall@budget: TP / Total_Positives (share of all true frauds captured).
      - FPR@budget: FP / Total_Negatives = (K - TP) / (N - Total_Positives).
    """
    n_total = len(y_score)
    n_pos = int(y_true.sum())
    n_neg = max(1, n_total - n_pos)
    k_alert = max(1, int(n_total * budget))

    # Stable sort descending
    sorted_idx = np.argsort(-y_score, kind="stable")
    alert_mask = np.zeros(n_total, dtype=bool)
    alert_mask[sorted_idx[:k_alert]] = True

    tp = int(((alert_mask) & (y_true == 1)).sum())
    fp = k_alert - tp

    prec = float(tp / k_alert) if k_alert > 0 else 0.0
    rec = float(tp / max(1, n_pos)) if n_pos > 0 else 0.0
    fpr = float(fp / n_neg) if n_neg > 0 else 0.0
    cutoff = float(y_score[sorted_idx[min(k_alert - 1, n_total - 1)]])

    return {
        "alert_budget": budget,
        "k_alerts": k_alert,
        "threshold": round(cutoff, 6),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "fpr": round(fpr, 6),
    }


def recall_at_alert_budget(y_true: np.ndarray, y_score: np.ndarray, budget: float) -> float:
    """Recall when only the top `budget` fraction of transactions are alerted."""
    res = metrics_at_alert_budget(y_true, y_score, budget)
    return res["recall"]


def precision_at_recall(y_true: np.ndarray, y_score: np.ndarray, target_recall: float) -> float:
    """Precision at a given recall level."""
    prec, rec, _ = precision_recall_curve(y_true, y_score)
    # Find the highest precision at recall >= target
    valid = rec >= target_recall
    if not valid.any():
        return 0.0
    return float(prec[valid].max())


def cost_weighted_loss(y_true: np.ndarray, y_score: np.ndarray,
                       threshold: float = 0.5, amounts: Optional[np.ndarray] = None,
                       cost_review: float = 1.0, cost_fraud_multiplier: float = 1.0,
                       cost_false_block: float = 5.0) -> float:
    """Cost-weighted loss: review cost + fraud loss + false-block cost."""
    preds = (y_score >= threshold).astype(int)
    fp = ((preds == 1) & (y_true == 0))
    fn = ((preds == 0) & (y_true == 1))
    tp = ((preds == 1) & (y_true == 1))

    if amounts is not None:
        fraud_loss = float((fn * amounts).sum()) * cost_fraud_multiplier
    else:
        fraud_loss = float(fn.sum()) * 1000.0 * cost_fraud_multiplier

    review_cost = float(tp.sum() + fp.sum()) * cost_review
    false_block_cost = float(fp.sum()) * cost_false_block
    return fraud_loss + review_cost + false_block_cost


def bootstrap_ci(y_true: np.ndarray, y_score: np.ndarray,
                 metric_fn, n_resamples: int = 500,
                 confidence: float = 0.95,
                 group_ids: Optional[np.ndarray] = None,
                 seed: int = 42) -> Tuple[float, float, float]:
    """Bootstrap confidence interval resampling by group_id or account."""
    rng = np.random.RandomState(seed)
    scores = []

    if group_ids is not None:
        unique_groups = np.unique(group_ids)
        for _ in range(n_resamples):
            sampled_groups = rng.choice(unique_groups, size=len(unique_groups), replace=True)
            mask = np.isin(group_ids, sampled_groups)
            if mask.sum() > 0 and y_true[mask].sum() > 0:
                try:
                    scores.append(metric_fn(y_true[mask], y_score[mask]))
                except Exception:
                    pass
    else:
        n = len(y_true)
        for _ in range(n_resamples):
            idx = rng.choice(n, size=n, replace=True)
            if y_true[idx].sum() > 0:
                try:
                    scores.append(metric_fn(y_true[idx], y_score[idx]))
                except Exception:
                    pass

    if not scores:
        point = metric_fn(y_true, y_score) if y_true.sum() > 0 else float("nan")
        return point, float("nan"), float("nan")

    scores = np.array(scores)
    alpha = (1 - confidence) / 2
    lo = float(np.percentile(scores, alpha * 100))
    hi = float(np.percentile(scores, (1 - alpha) * 100))
    point = float(np.median(scores))
    return point, lo, hi


# ─────────────────────────────────────────────────────────
# Model evaluation
# ─────────────────────────────────────────────────────────

def evaluate_model(
    name: str,
    y_true: np.ndarray,
    y_score: np.ndarray,
    scenarios: np.ndarray,
    group_ids: np.ndarray,
    amounts: Optional[np.ndarray] = None,
    threshold: float = 0.5,
    n_bootstrap: int = 500,
) -> Dict[str, Any]:
    """Evaluate a single model/variant: natural-prevalence full set, sub-populations, per-scenario metrics with bootstrap CIs."""
    results: Dict[str, Any] = {"model_name": name}

    # 1. Full natural-prevalence test split
    results["overall"] = _compute_metrics_block(
        y_true, y_score, amounts, threshold, group_ids, n_bootstrap
    )
    # Explicit operational alert budget summary on natural-prevalence set
    results["alert_budget_summary"] = {
        "budget_1pct": metrics_at_alert_budget(y_true, y_score, 0.01),
        "budget_0_5pct": metrics_at_alert_budget(y_true, y_score, 0.005),
    }

    # 2. Sub-population evaluations: (a) PaySim-native rows and (b) Injected rows
    native_mask = (scenarios == "paysim_native")
    injected_mask = (scenarios != "paysim_native")

    results["sub_populations"] = {
        "paysim_native": _compute_metrics_block(
            y_true[native_mask], y_score[native_mask],
            amounts[native_mask] if amounts is not None else None,
            threshold, group_ids[native_mask], n_bootstrap
        ) if native_mask.sum() > 0 else {},
        "injected_scenarios": _compute_metrics_block(
            y_true[injected_mask], y_score[injected_mask],
            amounts[injected_mask] if amounts is not None else None,
            threshold, group_ids[injected_mask], n_bootstrap
        ) if injected_mask.sum() > 0 else {},
    }

    # 3. Per-scenario breakdowns with group_id bootstrap CI and low-confidence flagging (< 30)
    results["per_scenario"] = {}
    unique_scenarios = np.unique(scenarios)
    for sc in unique_scenarios:
        mask = scenarios == sc
        if mask.sum() == 0:
            continue
        y_t = y_true[mask]
        y_s = y_score[mask]
        g = group_ids[mask]
        amt = amounts[mask] if amounts is not None else None
        results["per_scenario"][sc] = _compute_metrics_block(
            y_t, y_s, amt, threshold, g, n_bootstrap
        )

    # 4. Hard-negative FPR (share of legitimate hard negatives flagged)
    hn_scenarios = [
        "payroll", "merchant_high_fanin", "household_shared_device",
        "large_legitimate_drain", "bill_payment_burst"
    ]
    hn_mask = np.isin(scenarios, hn_scenarios) & (y_true == 0)
    if hn_mask.sum() > 0:
        hn_preds = (y_score[hn_mask] >= threshold).astype(int)
        results["hard_negative_fpr"] = float(hn_preds.mean())
        results["hard_negative_count"] = int(hn_mask.sum())
        results["hard_negative_flagged"] = int(hn_preds.sum())
        results["hard_negative_definition"] = "Share of legitimate hard negatives flagged as alerts"
    else:
        results["hard_negative_fpr"] = 0.0
        results["hard_negative_count"] = 0
        results["hard_negative_flagged"] = 0
        results["hard_negative_definition"] = "Share of legitimate hard negatives flagged as alerts"

    # 5. Time-slice stability (split test into 3 chronological windows)
    results["time_slices"] = _compute_time_slices(y_true, y_score, scenarios, 3)

    return results


def _compute_metrics_block(
    y_true: np.ndarray,
    y_score: np.ndarray,
    amounts: Optional[np.ndarray],
    threshold: float,
    group_ids: np.ndarray,
    n_bootstrap: int,
) -> Dict[str, Any]:
    """Compute the standard metrics block."""
    n_pos = int(y_true.sum())
    n_total = len(y_true)
    fraud_rate = float(n_pos / max(1, n_total))
    is_low_conf = bool(n_total < 30)

    block: Dict[str, Any] = {
        "n_total": n_total,
        "n_fraud": n_pos,
        "fraud_rate": round(fraud_rate, 6),
        "is_low_confidence": is_low_conf,
    }
    if is_low_conf:
        block["low_confidence_flag"] = f"LOW CONFIDENCE: scenario has {n_total} instances (< 30) in test split"

    if n_pos == 0 or n_pos == n_total:
        block["pr_auc"] = {"point": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
        block["roc_auc"] = float("nan")
        block["recall_at_1pct"] = float("nan")
        block["recall_at_0_5pct"] = float("nan")
        block["precision_at_recall_0_8"] = float("nan")
        block["precision_at_recall_0_9"] = float("nan")
        block["cost_weighted_loss"] = float("nan")
        return block

    # PR-AUC with CI bootstrapped by group_id
    point, lo, hi = bootstrap_ci(y_true, y_score, pr_auc, n_bootstrap, 0.95, group_ids)
    block["pr_auc"] = {"point": round(point, 4), "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)}

    block["roc_auc"] = round(roc_auc(y_true, y_score), 4)

    # Operational alert budgets
    b_1pct = metrics_at_alert_budget(y_true, y_score, 0.01)
    b_0_5pct = metrics_at_alert_budget(y_true, y_score, 0.005)

    block["recall_at_1pct"] = b_1pct["recall"]
    block["precision_at_1pct"] = b_1pct["precision"]
    block["fpr_at_1pct"] = b_1pct["fpr"]

    block["recall_at_0_5pct"] = b_0_5pct["recall"]
    block["precision_at_0_5pct"] = b_0_5pct["precision"]
    block["fpr_at_0_5pct"] = b_0_5pct["fpr"]

    block["precision_at_recall_0_8"] = round(precision_at_recall(y_true, y_score, 0.8), 4)
    block["precision_at_recall_0_9"] = round(precision_at_recall(y_true, y_score, 0.9), 4)
    block["cost_weighted_loss"] = round(
        cost_weighted_loss(y_true, y_score, threshold, amounts), 2
    )
    return block


def _compute_time_slices(
    y_true: np.ndarray,
    y_score: np.ndarray,
    scenarios: np.ndarray,
    n_slices: int,
) -> List[Dict[str, Any]]:
    """Split into n_slices and compute PR-AUC in each for stability."""
    n = len(y_true)
    slice_size = n // n_slices
    slices = []
    for i in range(n_slices):
        start = i * slice_size
        end = (i + 1) * slice_size if i < n_slices - 1 else n
        y_t = y_true[start:end]
        y_s = y_score[start:end]
        if y_t.sum() > 0 and len(np.unique(y_t)) > 1:
            slices.append({
                "slice": i,
                "n": int(end - start),
                "n_fraud": int(y_t.sum()),
                "pr_auc": round(pr_auc(y_t, y_s), 4),
            })
        else:
            slices.append({
                "slice": i,
                "n": int(end - start),
                "n_fraud": int(y_t.sum()),
                "pr_auc": float("nan"),
            })
    return slices


# ─────────────────────────────────────────────────────────
# Error analysis
# ─────────────────────────────────────────────────────────

def error_analysis(
    test_df: pd.DataFrame,
    y_score: np.ndarray,
    threshold: float,
    feature_cols: List[str],
    top_n: int = 50,
) -> Dict[str, Any]:
    """Top false positives and false negatives with features."""
    df = test_df.copy()
    df["score"] = y_score
    df["predicted"] = (y_score >= threshold).astype(int)

    # False positives: predicted=1 but label=0
    fp_mask = (df["predicted"] == 1) & (df["label"] == 0)
    fp_df = df[fp_mask].nlargest(top_n, "score")

    # False negatives: predicted=0 but label=1
    fn_mask = (df["predicted"] == 0) & (df["label"] == 1)
    fn_df = df[fn_mask].nsmallest(top_n, "score")

    meta_cols = ["txn_id", "account_id", "orig_account", "dest_account", "payee_id", "amount", "score", "scenario", "group_id"]
    cols_to_keep = [c for c in meta_cols if c in df.columns] + [c for c in feature_cols if c in df.columns and c not in meta_cols]

    return {
        "false_positives": fp_df[cols_to_keep].to_dict(orient="records")[:top_n],
        "false_negatives": fn_df[cols_to_keep].to_dict(orient="records")[:top_n],
        "n_fp_total": int(fp_mask.sum()),
        "n_fn_total": int(fn_mask.sum()),
    }


# ─────────────────────────────────────────────────────────
# Ablation study
# ─────────────────────────────────────────────────────────

def run_ablation_study(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_groups: Dict[str, List[str]],
    target_col: str = "label",
    seed: int = 42,
) -> Dict[str, Any]:
    """Run feature-group ablation: remove each group one at a time."""
    from xgboost import XGBClassifier

    all_features = [f for group in feature_groups.values() for f in group
                    if f in train_df.columns]

    results = {}

    # Full model baseline
    logger.info("Ablation: training full model ...")
    full_metrics = _train_and_eval_ablation(
        train_df, test_df, all_features, target_col, seed
    )
    results["full_model"] = full_metrics

    # Remove one group at a time
    for group_name, group_features in feature_groups.items():
        remaining = [f for f in all_features if f not in group_features]
        if len(remaining) == 0:
            continue
        logger.info(f"Ablation: removing {group_name} ({len(group_features)} features) ...")
        ablation_metrics = _train_and_eval_ablation(
            train_df, test_df, remaining, target_col, seed
        )
        results[f"without_{group_name}"] = ablation_metrics

    # Cumulative addition
    cumulative_features: List[str] = []
    group_order = ["base", "velocity", "behavioural", "device_network", "graph", "anomaly"]
    for group_name in group_order:
        if group_name not in feature_groups:
            continue
        group_feats = [f for f in feature_groups[group_name] if f in train_df.columns]
        cumulative_features.extend(group_feats)
        if len(cumulative_features) == 0:
            continue
        logger.info(f"Ablation: cumulative up to {group_name} ({len(cumulative_features)} features) ...")
        cum_metrics = _train_and_eval_ablation(
            train_df, test_df, cumulative_features.copy(), target_col, seed
        )
        results[f"cumulative_upto_{group_name}"] = cum_metrics

    return results


def _train_and_eval_ablation(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    features: List[str],
    target_col: str,
    seed: int,
) -> Dict[str, Any]:
    """Train XGBoost on given features and evaluate on test."""
    from xgboost import XGBClassifier

    X_train = train_df[features].fillna(0).to_numpy(dtype=np.float32)
    y_train = train_df[target_col].to_numpy(dtype=int)
    X_test = test_df[features].fillna(0).to_numpy(dtype=np.float32)
    y_test = test_df[target_col].to_numpy(dtype=int)

    pos = y_train.sum()
    neg = len(y_train) - pos
    spw = float(neg / max(1, pos))

    clf = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        scale_pos_weight=min(spw, 50.0),
        tree_method="hist",
        eval_metric="aucpr",
        random_state=seed,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)
    y_score = clf.predict_proba(X_test)[:, 1]

    return {
        "n_features": len(features),
        "features": features,
        "pr_auc": round(pr_auc(y_test, y_score), 4),
        "roc_auc": round(roc_auc(y_test, y_score), 4),
        "recall_at_1pct": round(recall_at_alert_budget(y_test, y_score, 0.01), 4),
    }


# ─────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────

def generate_figures(
    model_results: Dict[str, Dict[str, Any]],
    test_df: pd.DataFrame,
    model_scores: Dict[str, np.ndarray],
    ablation_results: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Generate evaluation figures. Returns list of saved file paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    saved = []

    # 1. PR Curves
    fig, ax = plt.subplots(figsize=(10, 7))
    y_test = test_df["label"].to_numpy(dtype=int)
    for model_name, scores in model_scores.items():
        if y_test.sum() > 0:
            prec, rec, _ = precision_recall_curve(y_test, scores)
            ap = average_precision_score(y_test, scores)
            ax.plot(rec, prec, label=f"{model_name} (AP={ap:.4f})", linewidth=2)
    ax.set_xlabel("Recall", fontsize=12)
    ax.set_ylabel("Precision", fontsize=12)
    ax.set_title("Precision-Recall Curves", fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    pr_path = str(FIGURES_DIR / "pr_curves.png")
    fig.savefig(pr_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    saved.append(pr_path)

    # 2. Per-scenario recall bars
    if model_results:
        main_model = list(model_results.keys())[-1]  # Use the latest model
        result = model_results[main_model]
        per_sc = result.get("per_scenario", {})
        if per_sc:
            scenarios_list = sorted(per_sc.keys())
            recalls_1pct = [per_sc[s].get("recall_at_1pct", 0) for s in scenarios_list]
            recalls_1pct = [r if not (isinstance(r, float) and np.isnan(r)) else 0 for r in recalls_1pct]

            fig, ax = plt.subplots(figsize=(12, 6))
            x = np.arange(len(scenarios_list))
            bars = ax.bar(x, recalls_1pct, color="#5B8DEF", edgecolor="white", linewidth=0.5)
            ax.set_xticks(x)
            ax.set_xticklabels(scenarios_list, rotation=45, ha="right", fontsize=9)
            ax.set_ylabel("Recall @ 1% Alert Budget", fontsize=12)
            ax.set_title(f"Per-Scenario Recall ({main_model})", fontsize=14)
            ax.set_ylim(0, 1.05)
            for bar, val in zip(bars, recalls_1pct):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                        f"{val:.2f}", ha="center", fontsize=8)
            ax.grid(axis="y", alpha=0.3)
            sc_path = str(FIGURES_DIR / "per_scenario_recall.png")
            fig.savefig(sc_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            saved.append(sc_path)

    # 3. Ablation chart
    if ablation_results:
        fig, ax = plt.subplots(figsize=(12, 6))
        ablation_items = [(k, v) for k, v in ablation_results.items() if k.startswith("without_")]
        if ablation_items:
            full_pr_auc = ablation_results.get("full_model", {}).get("pr_auc", 0)
            names = [k.replace("without_", "- ") for k, _ in ablation_items]
            vals = [v.get("pr_auc", 0) for _, v in ablation_items]
            drops = [full_pr_auc - v for v in vals]

            x = np.arange(len(names))
            colors = ["#EF5350" if d > 0.01 else "#66BB6A" if d < -0.01 else "#BDBDBD" for d in drops]
            ax.barh(x, drops, color=colors, edgecolor="white")
            ax.set_yticks(x)
            ax.set_yticklabels(names, fontsize=10)
            ax.set_xlabel("PR-AUC Drop (higher = more important)", fontsize=12)
            ax.set_title("Feature Group Ablation: PR-AUC Impact", fontsize=14)
            ax.axvline(x=0, color="black", linewidth=0.5)
            ax.grid(axis="x", alpha=0.3)
            ab_path = str(FIGURES_DIR / "ablation_chart.png")
            fig.savefig(ab_path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            saved.append(ab_path)

    # 4. Score distributions
    if model_scores:
        main_model = list(model_scores.keys())[-1]
        scores = model_scores[main_model]
        fig, ax = plt.subplots(figsize=(10, 6))
        fraud_scores = scores[y_test == 1]
        legit_scores = scores[y_test == 0]
        ax.hist(legit_scores, bins=100, alpha=0.6, label="Legitimate", color="#66BB6A", density=True)
        ax.hist(fraud_scores, bins=100, alpha=0.6, label="Fraud", color="#EF5350", density=True)
        ax.set_xlabel("Model Score", fontsize=12)
        ax.set_ylabel("Density", fontsize=12)
        ax.set_title(f"Score Distribution ({main_model})", fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        sd_path = str(FIGURES_DIR / "score_distributions.png")
        fig.savefig(sd_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        saved.append(sd_path)

    # 5. Calibration curve
    if model_scores:
        main_model = list(model_scores.keys())[-1]
        scores = model_scores[main_model]
        fig, ax = plt.subplots(figsize=(8, 8))
        n_bins = 20
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_means = []
        bin_fracs = []
        for i in range(n_bins):
            mask = (scores >= bin_edges[i]) & (scores < bin_edges[i + 1])
            if mask.sum() > 0:
                bin_means.append(scores[mask].mean())
                bin_fracs.append(y_test[mask].mean())
        ax.plot(bin_means, bin_fracs, "o-", color="#5B8DEF", linewidth=2, label="Model")
        ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
        ax.set_xlabel("Mean Predicted Score", fontsize=12)
        ax.set_ylabel("Observed Fraud Fraction", fontsize=12)
        ax.set_title("Calibration Curve", fontsize=14)
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        cal_path = str(FIGURES_DIR / "calibration_curve.png")
        fig.savefig(cal_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        saved.append(cal_path)

    return saved


# ─────────────────────────────────────────────────────────
# Markdown table generation
# ─────────────────────────────────────────────────────────

def generate_results_tables(all_results: Dict[str, Dict[str, Any]]) -> str:
    """Generate markdown tables from all model results."""
    lines = ["# Evaluation Results\n"]

    # Overall comparison table
    lines.append("## Overall Model Comparison\n")
    header = "| Model | PR-AUC | 95% CI | ROC-AUC | Recall@1% | Recall@0.5% | P@R=0.8 | P@R=0.9 | HN-FPR |"
    separator = "|-------|--------|--------|---------|-----------|-------------|---------|---------|--------|"
    lines.append(header)
    lines.append(separator)

    for name, result in all_results.items():
        ov = result.get("overall", {})
        pr = ov.get("pr_auc", {})
        if isinstance(pr, dict):
            pr_val = pr.get("point", float("nan"))
            ci = f"[{pr.get('ci_lo', 'N/A')}, {pr.get('ci_hi', 'N/A')}]"
        else:
            pr_val = pr
            ci = "N/A"
        row = f"| {name} | {_fmt(pr_val)} | {ci} | {_fmt(ov.get('roc_auc'))} | " \
              f"{_fmt(ov.get('recall_at_1pct'))} | {_fmt(ov.get('recall_at_0_5pct'))} | " \
              f"{_fmt(ov.get('precision_at_recall_0_8'))} | {_fmt(ov.get('precision_at_recall_0_9'))} | " \
              f"{_fmt(result.get('hard_negative_fpr'))} |"
        lines.append(row)

    lines.append("")

    # Per-scenario table for the best model
    if all_results:
        best_name = list(all_results.keys())[-1]
        best = all_results[best_name]
        per_sc = best.get("per_scenario", {})
        if per_sc:
            lines.append(f"\n## Per-Scenario Results ({best_name})\n")
            header2 = "| Scenario | N | N_Fraud | PR-AUC | Recall@1% | P@R=0.8 |"
            sep2 = "|----------|---|---------|--------|-----------|---------|"
            lines.append(header2)
            lines.append(sep2)
            for sc in sorted(per_sc.keys()):
                sc_data = per_sc[sc]
                pr2 = sc_data.get("pr_auc", {})
                pr2_val = pr2.get("point", float("nan")) if isinstance(pr2, dict) else pr2
                row2 = f"| {sc} | {sc_data.get('n_total', 0)} | {sc_data.get('n_fraud', 0)} | " \
                       f"{_fmt(pr2_val)} | {_fmt(sc_data.get('recall_at_1pct'))} | " \
                       f"{_fmt(sc_data.get('precision_at_recall_0_8'))} |"
                lines.append(row2)

    return "\n".join(lines)


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float) and np.isnan(val):
        return "N/A"
    return f"{val:.4f}"
