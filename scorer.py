# scorer.py
import json
import os
from datetime import datetime

import pandas as pd
import redis
import xgboost as xgb
from confluent_kafka import Consumer, Producer
from xgboost import XGBClassifier

from features import FEATURES, WINDOW_HOURS, add_derived

BOOTSTRAP = "localhost:9092"
IN_TOPIC = "transactions"
OUT_TOPIC = "decisions"
GROUP_ID = os.getenv("SCORER_GROUP", "scorer")

WINDOW_MS = WINDOW_HOURS * 3600 * 1000
KEY_TTL_S = WINDOW_HOURS * 3600 + 3600

with open("model/config.json") as f:
    CONFIG = json.load(f)
REVIEW_T = CONFIG["review_threshold"]
BLOCK_T = CONFIG["block_threshold"]

model = XGBClassifier()
model.load_model("model/fraud_xgb.json")
booster = model.get_booster()

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

consumer = Consumer({
    "bootstrap.servers": BOOTSTRAP,
    "group.id": GROUP_ID,
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
})
consumer.subscribe([IN_TOPIC])
producer = Producer({"bootstrap.servers": BOOTSTRAP})


def to_epoch_ms(iso_ts: str) -> int:
    return int(datetime.fromisoformat(iso_ts).timestamp() * 1000)


def velocity_features(txn: dict) -> dict:
    key = f"vel:{txn['account_id']}"
    now_ms = to_epoch_ms(txn["ts"])
    cutoff_ms = now_ms - WINDOW_MS
    member = f"{txn['txn_id']}|{txn['payee_id']}|{txn['amount']}"

    pipe = r.pipeline(transaction=True)
    pipe.zadd(key, {member: now_ms})
    pipe.zremrangebyscore(key, 0, cutoff_ms)
    pipe.zrange(key, 0, -1)
    pipe.expire(key, KEY_TTL_S)
    _, _, members, _ = pipe.execute()

    payees = set()
    total = 0.0
    for m in members:
        _, payee, amount = m.split("|")
        payees.add(payee)
        total += float(amount)

    return {
        "count_24h": len(members),
        "sum_24h": round(total, 2),
        "distinct_payees_24h": len(payees),
    }


def build_row(txn: dict, vel: dict) -> pd.DataFrame:
    row = pd.DataFrame([{
        "amount": txn["amount"],
        "txn_type": txn["txn_type"],
        "old_balance_orig": txn["old_balance_orig"],
        "new_balance_orig": txn["new_balance_orig"],
        **vel,
    }])
    return add_derived(row)


def explain(row: pd.DataFrame, top_k: int = 3) -> list[str]:
    """
    Per-feature contributions from XGBoost's built-in SHAP-style output
    (pred_contribs). Values are in log-odds: positive pushes toward fraud.
    """
    contribs = booster.predict(xgb.DMatrix(row[FEATURES]), pred_contribs=True)[0]
    per_feature = list(zip(FEATURES, contribs[:-1]))  # last entry is the bias
    per_feature.sort(key=lambda x: -x[1])
    return [
        f"{name}={row[name].iloc[0]:.4g} (+{c:.2f})"
        for name, c in per_feature[:top_k] if c > 0
    ]


def decide(p: float) -> str:
    if p >= BLOCK_T:
        return "BLOCK"
    if p >= REVIEW_T:
        return "REVIEW"
    return "ALLOW"


def delivery_report(err, msg):
    if err is not None:
        print(f"Decision delivery failed: {err}")


def main():
    print(f"Scorer running (review>={REVIEW_T:.3f}, block>={BLOCK_T:.3f}). Ctrl+C to stop.")
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"Consumer error: {msg.error()}")
                continue

            try:
                txn = json.loads(msg.value())
                txn["txn_type"], txn["old_balance_orig"], txn["new_balance_orig"]  # schema check
            except (json.JSONDecodeError, TypeError, KeyError):
                print(f"Skipping malformed message at offset {msg.offset()}")
                consumer.commit(message=msg, asynchronous=False)
                continue

            vel = velocity_features(txn)
            row = build_row(txn, vel)
            p = float(model.predict_proba(row[FEATURES])[0, 1])
            decision = {
                "txn_id": txn["txn_id"],
                "account_id": txn["account_id"],
                "payee_id": txn["payee_id"],
                "amount": txn["amount"],
                "ts": txn["ts"],
                "step": txn.get("step"),
                "features": {**vel, "orig_drained": int(row["orig_drained"].iloc[0])},
                "score": round(p, 4),
                "decision": decide(p),
                "reasons": explain(row),
                "label": txn.get("label"),  # evaluation only
            }

            producer.produce(OUT_TOPIC, key=txn["account_id"],
                             value=json.dumps(decision), callback=delivery_report)
            producer.poll(0)
            consumer.commit(message=msg, asynchronous=False)

            if decision["decision"] != "ALLOW":
                print(f"{decision['decision']:6} step={decision['step']} "
                      f"{txn['account_id']} p={p:.3f} {decision['reasons']}")
    except KeyboardInterrupt:
        pass
    finally:
        producer.flush()
        consumer.close()
        print("Scorer stopped.")


if __name__ == "__main__":
    main()