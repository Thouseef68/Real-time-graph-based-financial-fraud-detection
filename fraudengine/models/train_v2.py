"""Phase 4: End-to-end model training, Optuna tuning, and calibration.

Pipeline steps:
1. Out-of-fold Anomaly Scoring:
   - Splits training data into 3 group-aware time folds.
   - Trains AnomalyPipeline (IsolationForest + PyTorch Autoencoder) on legitimate rows.
   - Injects calibrated out-of-fold percentile rank features (iforest_score, ae_error)
     into the training set to prevent optimistic stacking bias.
2. Fits final AnomalyPipeline on all legitimate training rows, calibrated on validation.
3. Optuna Hyperparameter Optimization:
   - Up to 40 trials tuning XGBoost on validation split.
   - Objective: maximize PR-AUC on held-out validation data.
4. Fits final XGBoost model over all feature groups + anomaly scores.
5. Fits Isotonic Regression calibrator on validation probabilities.
6. Computes cost-optimal and alert-budget (1%, 0.5%) thresholds on validation data.
7. Saves complete model artifact bundle to models_v2/v2.0.0/.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.config import config
from fraudengine.models.anomaly import AnomalyPipeline, ANOMALY_FEATURE_NAMES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = ROOT / "data" / "cache"
MODELS_DIR = ROOT / "models_v2" / "v2.0.0"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FEATURE_NAMES = [
    # Base
    "amount", "type_code", "amount_to_balance", "orig_drained",
    "new_balance_to_old", "balance_change_ratio",
    # Velocity
    "count_1h", "sum_1h", "distinct_payees_1h", "amount_vs_sum_1h",
    "count_6h", "sum_6h", "distinct_payees_6h", "amount_vs_sum_6h",
    "count_24h", "sum_24h", "distinct_payees_24h", "amount_vs_sum_24h",
    # Behavioural
    "amount_zscore", "new_payee_flag", "payee_first_seen_age",
    "hour_deviation", "time_since_last_txn", "dormancy_days",
    "device_count", "ip_prefix_count",
    # Device / Network
    "is_new_device", "accounts_per_device", "devices_per_account",
    "ip_prefix_sharing_count", "device_first_seen_age",
    # Graph
    "payee_fan_in_1h", "payee_fan_in_24h", "payee_outflow_inflow_ratio_24h",
    "payee_pass_through_flag", "is_merchant", "fraud_exposure_2hop", "degree", "pagerank",
    # Anomaly
    "isolation_forest_score", "autoencoder_reconstruction_error",
]


def get_git_commit_hash() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"


def compute_out_of_fold_anomaly_scores(train_df: pd.DataFrame,
                                      val_df: pd.DataFrame,
                                      random_state: int = 42) -> Tuple[np.ndarray, np.ndarray, AnomalyPipeline]:
    """Compute out-of-fold anomaly scores on train_df using 3 time-based folds, and score val_df."""
    logger.info("Computing out-of-fold anomaly scores on training data (3 time-based folds) ...")
    n_train = len(train_df)
    oof_iforest = np.zeros(n_train, dtype=np.float32)
    oof_ae = np.zeros(n_train, dtype=np.float32)

    # Time-based fold boundaries
    steps = train_df["step"].to_numpy()
    fold_masks = [
        steps <= 200,
        (steps > 200) & (steps <= 350),
        steps > 350,
    ]

    anomaly_features = ANOMALY_FEATURE_NAMES
    X_train_raw = train_df[anomaly_features].fillna(0.0).to_numpy(dtype=np.float32)

    for fold_idx, test_mask in enumerate(fold_masks):
        train_fold_mask = (~test_mask) & (train_df["label"] == 0)
        X_fold_train = X_train_raw[train_fold_mask]
        X_fold_val = X_train_raw[test_mask]

        fold_pipeline = AnomalyPipeline(random_state=random_state + fold_idx)
        # Fast fit on fold
        fold_pipeline.fit(X_fold_train, epochs=8, batch_size=256)
        fold_pipeline.calibrate_on_validation(X_fold_val)

        r_if, r_ae = fold_pipeline.score(X_fold_val)
        oof_iforest[test_mask] = r_if
        oof_ae[test_mask] = r_ae

    logger.info("Fitting final AnomalyPipeline on all legitimate training data ...")
    final_pipeline = AnomalyPipeline(random_state=random_state)
    legit_mask = train_df["label"] == 0
    final_pipeline.fit(X_train_raw[legit_mask], epochs=12, batch_size=256)

    # Calibrate final anomaly pipeline on validation data
    X_val_raw = val_df[anomaly_features].fillna(0.0).to_numpy(dtype=np.float32)
    final_pipeline.calibrate_on_validation(X_val_raw)

    val_iforest, val_ae = final_pipeline.score(X_val_raw)
    return np.column_stack([oof_iforest, oof_ae]), np.column_stack([val_iforest, val_ae]), final_pipeline


def tune_xgboost(X_train: np.ndarray, y_train: np.ndarray,
                 X_val: np.ndarray, y_val: np.ndarray,
                 n_trials: int = 35, random_state: int = 42) -> Dict[str, Any]:
    """Run Optuna hyperparameter optimization on validation PR-AUC."""
    logger.info(f"Starting Optuna hyperparameter tuning ({n_trials} trials) on validation split ...")

    # Subsample training data for fast tuning trials if large
    if len(X_train) > 100000:
        rng = np.random.RandomState(random_state)
        sub_idx = rng.choice(len(X_train), size=100000, replace=False)
        X_sub = X_train[sub_idx]
        y_sub = y_train[sub_idx]
    else:
        X_sub, y_sub = X_train, y_train

    pos_count = (y_sub == 1).sum()
    neg_count = (y_sub == 0).sum()
    default_spw = float(neg_count / max(1, pos_count))

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 150, 450, step=50),
            "max_depth": trial.suggest_int("max_depth", 4, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", 1.0, min(50.0, default_spw)),
            "tree_method": "hist",
            "eval_metric": "aucpr",
            "random_state": random_state,
            "n_jobs": -1,
        }

        clf = XGBClassifier(**params)
        clf.fit(X_sub, y_sub)
        val_preds = clf.predict_proba(X_val)[:, 1]

        # Optimize validation PR-AUC
        score = average_precision_score(y_val, val_preds)
        return float(score)

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=random_state))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    logger.info(f"Best Optuna trial: Value (Val PR-AUC) = {study.best_value:.4f}")
    logger.info(f"Best hyperparameters: {study.best_params}")
    return study.best_params


def compute_thresholds(val_calibrated_proba: np.ndarray, y_val: np.ndarray,
                       cost_fp: float = 1.0, cost_fn: float = 10.0) -> Dict[str, float]:
    """Compute 1% alert budget, 0.5% alert budget, and cost-optimal thresholds."""
    # 1% Alert Budget threshold: top 1% highest scored
    thresh_1pct = float(np.percentile(val_calibrated_proba, 99.0))
    thresh_0_5pct = float(np.percentile(val_calibrated_proba, 99.5))

    # Cost-optimal threshold sweep
    candidate_thresholds = np.linspace(0.01, 0.99, 100)
    best_cost = float("inf")
    best_thresh = 0.5

    for th in candidate_thresholds:
        preds = (val_calibrated_proba >= th).astype(int)
        fp = ((preds == 1) & (y_val == 0)).sum()
        fn = ((preds == 0) & (y_val == 1)).sum()
        cost = fp * cost_fp + fn * cost_fn
        if cost < best_cost:
            best_cost = cost
            best_thresh = float(th)

    # 4-tier decision thresholds:
    # ALLOW: prob < step_up
    # STEP_UP: step_up <= prob < review
    # REVIEW: review <= prob < block
    # BLOCK: prob >= block
    return {
        "alert_budget_1pct": thresh_1pct,
        "alert_budget_0_5pct": thresh_0_5pct,
        "cost_optimal": best_thresh,
        "tier_allow_max": round(thresh_1pct * 0.4, 4),
        "tier_step_up_max": round(thresh_1pct * 0.8, 4),
        "tier_review_max": round(thresh_1pct * 1.5, 4),
        "tier_block_min": round(thresh_1pct * 1.5, 4),
    }


def train_v2_model() -> Dict[str, Any]:
    logger.info("=== Starting Phase 4 Model Training ===")

    train_path = CACHE_DIR / "train_features.parquet"
    val_path = CACHE_DIR / "val_features.parquet"
    test_path = CACHE_DIR / "test_features.parquet"

    if not train_path.exists() or not val_path.exists():
        raise FileNotFoundError(f"Cached features not found at {train_path}. Run precompute_features.py first.")

    train_df = pd.read_parquet(train_path)
    val_df = pd.read_parquet(val_path)
    logger.info(f"Loaded train_df ({len(train_df):,} rows) and val_df ({len(val_df):,} rows)")

    # 1. Compute out-of-fold anomaly scores
    oof_train_anomaly, val_anomaly, anomaly_pipeline = compute_out_of_fold_anomaly_scores(
        train_df, val_df, random_state=42
    )

    # Assign anomaly scores into feature matrices
    base_features = [f for f in MODEL_FEATURE_NAMES if f not in ("isolation_forest_score", "autoencoder_reconstruction_error")]

    X_train_base = train_df[base_features].fillna(0.0).to_numpy(dtype=np.float32)
    X_val_base = val_df[base_features].fillna(0.0).to_numpy(dtype=np.float32)

    X_train = np.hstack([X_train_base, oof_train_anomaly])
    X_val = np.hstack([X_val_base, val_anomaly])

    y_train = train_df["label"].to_numpy(dtype=int)
    y_val = val_df["label"].to_numpy(dtype=int)

    logger.info(f"Feature matrix assembled: {X_train.shape[1]} features")

    # 2. Optuna Hyperparameter Tuning
    best_params = tune_xgboost(X_train, y_train, X_val, y_val, n_trials=35, random_state=42)

    # 3. Fit Final Champion XGBoost
    logger.info("Fitting final champion XGBoost model with best parameters ...")
    final_params = {
        **best_params,
        "tree_method": "hist",
        "eval_metric": "aucpr",
        "random_state": 42,
        "n_jobs": -1,
    }
    model = XGBClassifier(**final_params)
    model.fit(X_train, y_train)

    # 4. Calibration with Isotonic Regression on Validation
    val_raw_proba = model.predict_proba(X_val)[:, 1]
    logger.info("Fitting Isotonic Regression calibrator on validation probabilities ...")
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(val_raw_proba, y_val)
    val_calibrated_proba = calibrator.predict(val_raw_proba)

    val_pr_auc = float(average_precision_score(y_val, val_calibrated_proba))
    val_roc_auc = float(roc_auc_score(y_val, val_calibrated_proba))

    # 5. Thresholds
    thresholds = compute_thresholds(val_calibrated_proba, y_val)

    # Recall at 1% alert budget
    th_1pct = thresholds["alert_budget_1pct"]
    recall_1pct = float(((val_calibrated_proba >= th_1pct) & (y_val == 1)).sum() / (y_val == 1).sum())

    # Recall at 0.5% alert budget
    th_0_5pct = thresholds["alert_budget_0_5pct"]
    recall_0_5pct = float(((val_calibrated_proba >= th_0_5pct) & (y_val == 1)).sum() / (y_val == 1).sum())

    logger.info(f"Validation Metrics: PR-AUC = {val_pr_auc:.4f}, ROC-AUC = {val_roc_auc:.4f}, Recall@1% Alert = {recall_1pct:.4f}")

    # 6. Save Model Bundle
    logger.info(f"Saving model artifacts to {MODELS_DIR} ...")
    model.save_model(str(MODELS_DIR / "xgboost_model.json"))
    joblib.dump(model, str(MODELS_DIR / "xgboost_model.joblib"))
    joblib.dump(calibrator, str(MODELS_DIR / "calibrator.joblib"))
    anomaly_pipeline.save(str(MODELS_DIR / "anomaly_pipeline"))

    with open(MODELS_DIR / "feature_list.json", "w") as f:
        json.dump(MODEL_FEATURE_NAMES, f, indent=2)

    with open(MODELS_DIR / "thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    metrics = {
        "val_pr_auc": val_pr_auc,
        "val_roc_auc": val_roc_auc,
        "val_recall_at_1pct_alert": recall_1pct,
        "val_recall_at_0_5pct_alert": recall_0_5pct,
        "val_rows": len(val_df),
        "val_fraud_count": int((y_val == 1).sum()),
    }
    with open(MODELS_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    data_hash = hashlib.sha256((str(len(train_df)) + str(len(val_df))).encode()).hexdigest()[:16]
    metadata = {
        "model_version": "2.0.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": 42,
        "data_hash": data_hash,
        "git_commit": get_git_commit_hash(),
        "n_features": len(MODEL_FEATURE_NAMES),
        "best_hyperparameters": best_params,
        "metrics": metrics,
        "thresholds": thresholds,
    }
    with open(MODELS_DIR / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Phase 4 Model Training complete! Model bundle saved in {MODELS_DIR}")
    return metadata


if __name__ == "__main__":
    train_v2_model()
