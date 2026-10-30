"""Phase 5: Run complete evaluation experiment.

Produces:
  results_v2/phase5_evaluation.json      – full metrics
  results_v2/phase5_ablation.json        – ablation study
  results_v2/phase5_error_analysis.json   – top FPs and FNs
  results_v2/tables/evaluation_results.md – markdown tables
  results_v2/figures/*.png                – PR curves, etc.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.eval.runner import (
    evaluate_model,
    error_analysis,
    run_ablation_study,
    generate_figures,
    generate_results_tables,
    RESULTS_DIR,
    TABLES_DIR,
    FIGURES_DIR,
)
from fraudengine.features.engineering import FEATURE_GROUPS
from fraudengine.models.anomaly import AnomalyPipeline, ANOMALY_FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = ROOT / "data" / "cache"
MODELS_DIR = ROOT / "models_v2" / "v2.0.0"


def load_data():
    train_df = pd.read_parquet(CACHE_DIR / "train_features.parquet")
    val_df = pd.read_parquet(CACHE_DIR / "val_features.parquet")
    test_df = pd.read_parquet(CACHE_DIR / "test_features.parquet")
    logger.info(f"Loaded: train={len(train_df):,}, val={len(val_df):,}, test={len(test_df):,}")
    return train_df, val_df, test_df


def get_model_feature_names():
    flist_path = MODELS_DIR / "feature_list.json"
    if flist_path.exists():
        with open(flist_path) as f:
            return json.load(f)
    # Fallback
    from fraudengine.models.train_v2 import MODEL_FEATURE_NAMES
    return MODEL_FEATURE_NAMES


def load_v2_model():
    """Load the trained v2 model, calibrator, and anomaly pipeline."""
    model = joblib.load(str(MODELS_DIR / "xgboost_model.joblib"))
    calibrator = joblib.load(str(MODELS_DIR / "calibrator.joblib"))
    anomaly_pipeline = AnomalyPipeline.load(str(MODELS_DIR / "anomaly_pipeline"))
    with open(MODELS_DIR / "thresholds.json") as f:
        thresholds = json.load(f)
    return model, calibrator, anomaly_pipeline, thresholds


def score_with_v2(test_df, model, calibrator, anomaly_pipeline, feature_names):
    """Score test set with v2 model (XGBoost + anomaly + calibration)."""
    anomaly_features = ANOMALY_FEATURE_NAMES
    X_anomaly = test_df[anomaly_features].fillna(0).to_numpy(dtype=np.float32)
    if_scores, ae_scores = anomaly_pipeline.score(X_anomaly)

    base_features = [f for f in feature_names if f not in ("isolation_forest_score", "autoencoder_reconstruction_error")]
    X_base = test_df[base_features].fillna(0).to_numpy(dtype=np.float32)
    X_test = np.hstack([X_base, if_scores.reshape(-1, 1), ae_scores.reshape(-1, 1)])

    raw_prob = model.predict_proba(X_test)[:, 1]
    calibrated_prob = calibrator.predict(raw_prob)
    return calibrated_prob


def run_baselines(train_df, test_df, feature_names):
    """Run baseline models for comparison."""
    logger.info("Running baselines ...")
    baselines = {}

    y_train = train_df["label"].to_numpy(dtype=int)
    y_test = test_df["label"].to_numpy(dtype=int)

    base_features = [f for f in feature_names if f not in ("isolation_forest_score", "autoencoder_reconstruction_error")]
    available = [f for f in base_features if f in test_df.columns]

    X_train = train_df[available].fillna(0).to_numpy(dtype=np.float32)
    X_test = test_df[available].fillna(0).to_numpy(dtype=np.float32)

    # 1. Rule baseline: orig_drained
    if "orig_drained" in test_df.columns:
        baselines["rule_drain_only"] = test_df["orig_drained"].fillna(0).to_numpy(dtype=np.float32)

    # 2. Logistic Regression
    try:
        lr = LogisticRegression(max_iter=500, random_state=42, solver="lbfgs", class_weight="balanced")
        lr.fit(X_train, y_train)
        baselines["logistic_regression"] = lr.predict_proba(X_test)[:, 1].astype(np.float32)
    except Exception as e:
        logger.warning(f"Logistic regression failed: {e}")

    # 3. v1 XGBoost (drain features only)
    drain_features = ["amount", "type_code", "amount_to_balance", "orig_drained",
                      "new_balance_to_old", "balance_change_ratio"]
    drain_available = [f for f in drain_features if f in train_df.columns]
    if drain_available:
        pos = y_train.sum()
        neg = len(y_train) - pos
        spw = float(neg / max(1, pos))
        xgb_drain = XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.05,
                                   scale_pos_weight=min(spw, 50.0), tree_method="hist",
                                   random_state=42, n_jobs=-1)
        xgb_drain.fit(train_df[drain_available].fillna(0).to_numpy(dtype=np.float32), y_train)
        baselines["xgb_drain_only"] = xgb_drain.predict_proba(
            test_df[drain_available].fillna(0).to_numpy(dtype=np.float32)
        )[:, 1].astype(np.float32)

    # 4. XGBoost all base features (no anomaly)
    xgb_all = XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.05,
                             scale_pos_weight=min(float(neg / max(1, pos)), 50.0),
                             tree_method="hist", random_state=42, n_jobs=-1)
    xgb_all.fit(X_train, y_train)
    baselines["xgb_all_no_anomaly"] = xgb_all.predict_proba(X_test)[:, 1].astype(np.float32)

    return baselines


def main():
    t0 = time.time()
    logger.info("=== Phase 5: Evaluation Experiment ===")

    train_df, val_df, test_df = load_data()
    feature_names = get_model_feature_names()

    y_test = test_df["label"].to_numpy(dtype=int)
    scenarios = test_df["scenario"].to_numpy()
    group_ids = test_df["group_id"].fillna("none").to_numpy()
    amounts = test_df["amount"].to_numpy(dtype=np.float32) if "amount" in test_df.columns else None

    # ── Population metadata (R2 requirements) ──
    pop_metadata = {
        "train": {
            "rows": len(train_df),
            "positives": int(train_df["label"].sum()),
            "prevalence": round(float(train_df["label"].mean()), 6),
            "subsampling": "Deterministic modulo 5 on background native legitimate traffic (balanced sample without dropping rare labels)"
        },
        "val": {
            "rows": len(val_df),
            "positives": int(val_df["label"].sum()),
            "prevalence": round(float(val_df["label"].mean()), 6),
            "subsampling": "Deterministic modulo 5 on background native legitimate traffic"
        },
        "test": {
            "rows": len(test_df),
            "positives": int(test_df["label"].sum()),
            "prevalence": round(float(test_df["label"].mean()), 6),
            "subsampling": "NONE - full test split at natural prevalence (100% of test stream replayed)",
            "explanation_7676_vs_104850": (
                "The earlier 7,676 row figure was produced by applying a 1:20 (5%) modulo filter "
                "on native legitimate background rows in the test window (5,099 background + 1,600 native fraud "
                "+ 977 injected = 7,676 rows). In this remediated evaluation, the filter was removed to evaluate "
                "the entire 104,623 transactions at natural prevalence."
            )
        }
    }
    with open(RESULTS_DIR / "population_metadata.json", "w") as f:
        json.dump(pop_metadata, f, indent=2)
    logger.info(f"Population metadata: {pop_metadata}")

    # ── Load and score with v2 model ──
    model, calibrator, anomaly_pipeline, thresholds = load_v2_model()
    v2_scores = score_with_v2(test_df, model, calibrator, anomaly_pipeline, feature_names)

    # Cost-optimal threshold
    threshold = thresholds.get("cost_optimal", 0.5)

    # ── Run baselines ──
    baseline_scores = run_baselines(train_df, test_df, feature_names)

    # ── Evaluate all models ──
    all_results = {}
    all_model_scores = {}

    # Baselines
    for name, scores in baseline_scores.items():
        logger.info(f"Evaluating {name} ...")
        all_results[name] = evaluate_model(name, y_test, scores, scenarios, group_ids, amounts, threshold)
        all_model_scores[name] = scores

    # v2 model
    logger.info("Evaluating v2_xgboost_tuned ...")
    all_results["v2_xgboost_tuned"] = evaluate_model(
        "v2_xgboost_tuned", y_test, v2_scores, scenarios, group_ids, amounts, threshold
    )
    all_model_scores["v2_xgboost_tuned"] = v2_scores

    # ── Save evaluation results ──
    eval_path = RESULTS_DIR / "phase5_evaluation.json"
    with open(eval_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    logger.info(f"Saved evaluation results to {eval_path}")

    # ── Error analysis ──
    logger.info("Running error analysis ...")
    errors = error_analysis(test_df, v2_scores, threshold, list(feature_names))
    error_path = RESULTS_DIR / "phase5_error_analysis.json"
    with open(error_path, "w") as f:
        json.dump(errors, f, indent=2, default=str)
    logger.info(f"Saved error analysis to {error_path}")

    # ── Ablation study ──
    logger.info("Running ablation study ...")
    feature_groups_available = {}
    for gname, gfeats in FEATURE_GROUPS.items():
        available = [f for f in gfeats if f in train_df.columns]
        if available:
            feature_groups_available[gname] = available

    ablation = run_ablation_study(train_df, val_df, test_df, feature_groups_available)
    ablation_path = RESULTS_DIR / "phase5_ablation.json"
    with open(ablation_path, "w") as f:
        json.dump(ablation, f, indent=2, default=str)
    logger.info(f"Saved ablation results to {ablation_path}")

    # ── Generate figures ──
    logger.info("Generating figures ...")
    figure_paths = generate_figures(all_results, test_df, all_model_scores, ablation)
    logger.info(f"Generated {len(figure_paths)} figures")

    # ── Generate markdown tables ──
    md_content = generate_results_tables(all_results)
    md_path = TABLES_DIR / "evaluation_results.md"
    with open(md_path, "w") as f:
        f.write(md_content)
    logger.info(f"Saved results tables to {md_path}")

    elapsed = time.time() - t0
    logger.info(f"=== Phase 5 complete in {elapsed:.1f}s ===")

    # Print summary
    v2_overall = all_results.get("v2_xgboost_tuned", {}).get("overall", {})
    v2_pr = v2_overall.get("pr_auc", {})
    pr_val = v2_pr.get("point", "N/A") if isinstance(v2_pr, dict) else v2_pr
    logger.info(f"v2 Test PR-AUC: {pr_val}")
    logger.info(f"v2 Test ROC-AUC: {v2_overall.get('roc_auc', 'N/A')}")
    logger.info(f"v2 Recall@1%: {v2_overall.get('recall_at_1pct', 'N/A')}")


if __name__ == "__main__":
    main()
