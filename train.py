# train.py
import json
import os
from collections import Counter, deque

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from xgboost import XGBClassifier

from features import FEATURES, TYPE_CODES, WINDOW_HOURS, add_derived

DATA = "data/PS_20174392719_1491204439457_log.csv"
OUT_DIR = "model"

TRAIN_END = 500   # steps 1..500 train
VAL_END = 600     # steps 501..600 validation, 601+ test
REVIEW_RECALL = 0.85
BLOCK_PRECISION = 0.70


def load() -> pd.DataFrame:
    cols = ["step", "type", "amount", "nameOrig", "oldbalanceOrg",
            "newbalanceOrig", "nameDest", "isFraud"]
    dtypes = {
        "step": "int32",
        "type": "category",
        "amount": "float32",
        "nameOrig": "category",
        "oldbalanceOrg": "float32",
        "newbalanceOrig": "float32",
        "nameDest": "category",
        "isFraud": "int8",
    }
    df = pd.read_csv(DATA, usecols=cols, dtype=dtypes)
    df = df.rename(columns={
        "type": "txn_type",
        "nameOrig": "account_id",
        "nameDest": "payee_id",
        "oldbalanceOrg": "old_balance_orig",
        "newbalanceOrig": "new_balance_orig",
        "isFraud": "label",
    })
    return df


def add_velocity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rolling 24-step window per account, using only past and current rows.
    Matches the Redis logic in scorer.py: keep events with step > now - window,
    count and sum include the current transaction.
    Sorting by account then step keeps per-account state small in memory.
    """
    df = df.sort_values(["account_id", "step"], kind="stable").reset_index(drop=True)
    n = len(df)
    accs = df["account_id"].to_numpy()
    pays = df["payee_id"].to_numpy()
    amts = df["amount"].to_numpy()
    steps = df["step"].to_numpy()

    cnt = np.zeros(n)
    sm = np.zeros(n)
    pc = np.zeros(n)

    prev = None
    dq, ct, total = deque(), Counter(), 0.0
    for i in range(n):
        if accs[i] != prev:
            prev = accs[i]
            dq, ct, total = deque(), Counter(), 0.0

        dq.append((steps[i], pays[i], amts[i]))
        ct[pays[i]] += 1
        total += amts[i]

        cutoff = steps[i] - WINDOW_HOURS
        while dq and dq[0][0] <= cutoff:
            _, p, a = dq.popleft()
            total -= a
            ct[p] -= 1
            if ct[p] == 0:
                del ct[p]

        cnt[i] = len(dq)
        sm[i] = total
        pc[i] = len(ct)

    df["count_24h"] = cnt
    df["sum_24h"] = sm
    df["distinct_payees_24h"] = pc
    return df


def pick_thresholds(y_true, probs):
    prec, rec, thr = precision_recall_curve(y_true, probs)
    # precision/recall have one extra trailing entry relative to thresholds
    review_idx = np.where(rec[:-1] >= REVIEW_RECALL)[0]
    block_idx = np.where(prec[:-1] >= BLOCK_PRECISION)[0]
    review_t = float(thr[review_idx.max()]) if len(review_idx) else 0.1
    block_t = float(thr[block_idx.min()]) if len(block_idx) else 0.9
    return min(review_t, block_t), max(review_t, block_t)


def report(name, y, p, review_t, block_t):
    pred_review = p >= review_t
    pred_block = p >= block_t
    tp = int(((pred_review) & (y == 1)).sum())
    fp = int(((pred_review) & (y == 0)).sum())
    fn = int(((~pred_review) & (y == 1)).sum())
    print(f"\n[{name}]")
    print(f"  PR-AUC:                {average_precision_score(y, p):.4f}")
    print(f"  ROC-AUC:               {roc_auc_score(y, p):.4f}")
    print(f"  REVIEW  (>= {review_t:.3f}) recall={tp/(tp+fn+1e-9):.3f} precision={tp/(tp+fp+1e-9):.3f}")
    print(f"  BLOCK   (>= {block_t:.3f}) flagged={int(pred_block.sum())} "
          f"precision={((pred_block)&(y==1)).sum()/(pred_block.sum()+1e-9):.3f}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Loading PaySim...")
    df = load()
    print(f"  {len(df):,} rows, fraud rate {df.label.mean():.4%}")

    print("Computing velocity features (this takes a minute or two)...")
    df = add_velocity(df)
    df = add_derived(df)

    train = df[df.step <= TRAIN_END]
    val = df[(df.step > TRAIN_END) & (df.step <= VAL_END)]
    test = df[df.step > VAL_END]
    print(f"  train={len(train):,} val={len(val):,} test={len(test):,}")

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
    model.fit(
        train[FEATURES], train.label,
        eval_set=[(val[FEATURES], val.label)],
        verbose=50,
    )

    p_val = model.predict_proba(val[FEATURES])[:, 1]
    review_t, block_t = pick_thresholds(val.label, p_val)

    p_test = model.predict_proba(test[FEATURES])[:, 1]
    report("validation", val.label.to_numpy(), p_val, review_t, block_t)
    report("test (held out)", test.label.to_numpy(), p_test, review_t, block_t)

    print("\nFeature importance (gain):")
    for name, g in sorted(model.get_booster().get_score(importance_type="gain").items(),
                          key=lambda x: -x[1]):
        print(f"  {name:22s} {g:.1f}")

    model.save_model(f"{OUT_DIR}/fraud_xgb.json")
    config = {
        "features": FEATURES,
        "type_codes": TYPE_CODES,
        "window_hours": WINDOW_HOURS,
        "review_threshold": review_t,
        "block_threshold": block_t,
    }
    with open(f"{OUT_DIR}/config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nSaved model and config to {OUT_DIR}/")


if __name__ == "__main__":
    main()