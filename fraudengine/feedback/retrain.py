"""Automated retraining pipeline with delayed feedback ingestion and champion/challenger promotion."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.feedback.label_store import LabelStore
from fraudengine.models.registry import ModelRegistry

logger = logging.getLogger(__name__)
CACHE_DIR = ROOT / "data" / "cache"
MODELS_DIR = ROOT / "models_v2"
RESULTS_DIR = ROOT / "results_v2"


def run_retraining(
    min_labels: int = 10,
    min_pr_auc_delta: float = 0.005,
    seed: int = 42,
) -> Dict[str, Any]:
    """Execute automated model retraining with delayed analyst feedback labels."""
    logger.info("=== Starting Automated Model Retraining Job ===")
    registry = ModelRegistry()
    label_store = LabelStore()

    # 1. Fetch newly confirmed analyst labels
    confirmed_labels = label_store.get_all_labels()
    logger.info(f"Retrieved {len(confirmed_labels)} confirmed labels from LabelStore")

    # 2. Load cached training and validation features
    train_path = CACHE_DIR / "train_features.parquet"
    val_path = CACHE_DIR / "val_features.parquet"

    if not train_path.exists() or not val_path.exists():
        raise FileNotFoundError("Train or Val feature caches not found. Run feature precomputation first.")

    train_df = pd.read_parquet(train_path)
    val_df = pd.read_parquet(val_path)

    # 3. Augment training set with confirmed feedback if available
    n_augmented = 0
    if len(confirmed_labels) > 0 and "txn_id" in train_df.columns:
        for txn_id, entry in confirmed_labels.items():
            mask = train_df["txn_id"] == txn_id
            if mask.any():
                train_df.loc[mask, "label"] = entry.get("label", 1)
                n_augmented += 1
    logger.info(f"Updated {n_augmented} existing training transactions with ground-truth feedback")

    # 4. Feature columns
    flist_path = MODELS_DIR / "v2.0.0" / "feature_list.json"
    if flist_path.exists():
        with open(flist_path) as f:
            feature_cols = json.load(f)
    else:
        from fraudengine.models.train_v2 import MODEL_FEATURE_NAMES
        feature_cols = MODEL_FEATURE_NAMES

    available_cols = [c for c in feature_cols if c in train_df.columns and c in val_df.columns]
    X_tr = train_df[available_cols].fillna(0).to_numpy(dtype=np.float32)
    y_tr = train_df["label"].to_numpy(dtype=int)

    X_val = val_df[available_cols].fillna(0).to_numpy(dtype=np.float32)
    y_val = val_df["label"].to_numpy(dtype=int)

    # 5. Train Challenger XGBoost Model
    pos = y_tr.sum()
    neg = len(y_tr) - pos
    spw = float(neg / max(1, pos))

    logger.info(f"Training challenger model on {len(X_tr):,} samples (pos={pos:,}, neg={neg:,}) ...")
    challenger_xgb = XGBClassifier(
        n_estimators=250,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=min(spw, 50.0),
        tree_method="hist",
        eval_metric="aucpr",
        random_state=seed,
        n_jobs=-1,
    )
    challenger_xgb.fit(X_tr, y_tr)

    # Evaluate challenger
    val_preds_raw = challenger_xgb.predict_proba(X_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(val_preds_raw, y_val)
    val_preds = calibrator.predict(val_preds_raw)

    challenger_pr_auc = float(average_precision_score(y_val, val_preds))
    challenger_roc_auc = float(roc_auc_score(y_val, val_preds))

    # Recall at 1%
    k_alert = max(1, int(len(y_val) * 0.01))
    cutoff = np.sort(val_preds)[::-1][min(k_alert - 1, len(val_preds) - 1)]
    challenger_rec_1pct = float(((val_preds >= cutoff) & (y_val == 1)).sum() / max(1, y_val.sum()))

    challenger_metrics = {
        "pr_auc": round(challenger_pr_auc, 4),
        "roc_auc": round(challenger_roc_auc, 4),
        "recall_at_1pct": round(challenger_rec_1pct, 4),
        "training_samples": len(X_tr),
        "feedback_labels_applied": n_augmented,
    }
    logger.info(f"Challenger validation metrics: {challenger_metrics}")

    # 6. Save Challenger artifacts
    challenger_version = f"v2.{int(time.time())}.0"
    challenger_dir = MODELS_DIR / challenger_version
    challenger_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(challenger_xgb, challenger_dir / "xgboost_model.joblib")
    joblib.dump(calibrator, challenger_dir / "calibrator.joblib")
    with open(challenger_dir / "feature_list.json", "w") as f:
        json.dump(available_cols, f, indent=2)

    # 7. Register and evaluate promotion against Champion
    registry.register_model(
        version=challenger_version,
        model_path=str(challenger_dir),
        metrics=challenger_metrics,
        stage="challenger",
        notes=f"Automated retrain run on {n_augmented} feedback labels",
    )

    promo_result = registry.promote_challenger(
        challenger_version=challenger_version,
        min_pr_auc_delta=min_pr_auc_delta,
    )

    retrain_summary = {
        "timestamp": time.time(),
        "challenger_version": challenger_version,
        "metrics": challenger_metrics,
        "promotion_result": promo_result,
        "active_champion": registry.get_champion_version(),
    }

    out_file = RESULTS_DIR / "retrain_log.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(retrain_summary, f, indent=2)

    logger.info(f"Retraining complete! Summary saved to {out_file}")
    return retrain_summary


if __name__ == "__main__":
    run_retraining()
