# baselines.py
# Compares XGBoost against simple baselines and runs feature ablations,
# all on the same time-based split used in train.py.
import json
import os

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from features import FEATURES, add_derived
from train import TRAIN_END, VAL_END, add_velocity, load

CACHE = "data/features_cache.pkl"
OUT_DIR = "results"

VELOCITY = ["count_24h", "sum_24h", "distinct_payees_24h", "amount_vs_sum_24h"]
DRAIN = ["orig_drained", "amount_to_balance"]


def get_data() -> pd.DataFrame:
    if os.path.exists(CACHE):
        print(f"Loading cached features from {CACHE}")
        return pd.read_pickle(CACHE)
    print("Computing features (first run only, a few minutes)...")
    df = add_derived(add_velocity(load()))
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    df.to_pickle(CACHE)
    return df


def metrics(y, p) -> dict:
    prec, rec, _ = precision_recall_curve(y, p)
    ok = rec >= 0.90
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "roc_auc": float(roc_auc_score(y, p)),
        "precision_at_recall_90": float(prec[ok].max()) if ok.any() else 0.0,
    }


def train_xgb(train: pd.DataFrame, val: pd.DataFrame, feats: list[str]):
    neg, pos = (train.label == 0).sum(), (train.label == 1).sum()
    model = XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=neg / pos,
        eval_metric="aucpr",
        tree_method="hist",
        early_stopping_rounds=30,
    )
    model.fit(train[feats], train.label,
              eval_set=[(val[feats], val.label)], verbose=False)
    return model


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = get_data()
    train = df[df.step <= TRAIN_END]
    val = df[(df.step > TRAIN_END) & (df.step <= VAL_END)]
    test = df[df.step > VAL_END]
    y = test.label.to_numpy()

    print(f"Test split: {len(test):,} rows, fraud rate {y.mean():.4%}\n")
    results = {}

    # Rule baselines: binary scores, no learning
    results["rule: orig_drained only"] = metrics(
        y, (test.orig_drained == 1).astype(float).to_numpy())

    # Logistic regression on the same features
    lr = make_pipeline(StandardScaler(),
                       LogisticRegression(max_iter=1000, class_weight="balanced"))
    lr.fit(train[FEATURES], train.label)
    results["logistic regression (all features)"] = metrics(
        y, lr.predict_proba(test[FEATURES])[:, 1])

    # XGBoost ablations
    variants = {
        "xgboost: all features": FEATURES,
        "xgboost: without drain features": [f for f in FEATURES if f not in DRAIN],
        "xgboost: without velocity features": [f for f in FEATURES if f not in VELOCITY],
        "xgboost: without drain + velocity": [f for f in FEATURES
                                              if f not in DRAIN and f not in VELOCITY],
    }
    best_iters = {}
    for name, feats in variants.items():
        print(f"Training {name} ({len(feats)} features)...")
        m = train_xgb(train, val, feats)
        best_iters[name] = int(m.best_iteration)
        results[name] = metrics(y, m.predict_proba(test[feats])[:, 1])

    print(f"\n{'model':42s} {'PR-AUC':>8s} {'ROC-AUC':>8s} {'P@R=0.90':>9s}")
    print("-" * 70)
    for name, r in results.items():
        print(f"{name:42s} {r['pr_auc']:8.4f} {r['roc_auc']:8.4f} "
              f"{r['precision_at_recall_90']:9.4f}")

    with open(f"{OUT_DIR}/baselines.json", "w") as f:
        json.dump({"results": results, "best_iterations": best_iters,
                   "test_fraud_rate": float(y.mean())}, f, indent=2)
    print(f"\nSaved to {OUT_DIR}/baselines.json")


if __name__ == "__main__":
    main()