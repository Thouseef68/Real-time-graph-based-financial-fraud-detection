# replay_producer.py
# Streams only held-out PaySim rows (step > 600) so live metrics are honest.
import argparse
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
from confluent_kafka import Producer

DATA = "data/PS_20174392719_1491204439457_log.csv"
TOPIC = "transactions"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
COLS = ["step", "type", "amount", "nameOrig", "oldbalanceOrg",
        "newbalanceOrig", "nameDest", "isFraud"]


def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed: {err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-step", type=int, default=600,
                    help="only stream rows with step > this (default 600, the test split)")
    ap.add_argument("--limit", type=int, default=300_000)
    ap.add_argument("--delay", type=float, default=0.0)
    args = ap.parse_args()

    producer = Producer({"bootstrap.servers": "localhost:9092", "linger.ms": 5})
    sent = 0

    for chunk in pd.read_csv(DATA, usecols=COLS, chunksize=50_000):
        chunk = chunk[chunk.step > args.start_step]
        for r in chunk.itertuples(index=False):
            if sent >= args.limit:
                break
            ts = BASE_TIME + timedelta(hours=int(r.step))
            msg = {
                "txn_id": str(uuid.uuid4()),
                "account_id": r.nameOrig,
                "payee_id": r.nameDest,
                "amount": float(r.amount),
                "ts": ts.isoformat(),
                "step": int(r.step),
                "txn_type": r.type,
                "old_balance_orig": float(r.oldbalanceOrg),
                "new_balance_orig": float(r.newbalanceOrig),
                "label": int(r.isFraud),
            }
            producer.produce(TOPIC, key=r.nameOrig, value=json.dumps(msg),
                             callback=delivery_report)
            producer.poll(0)
            sent += 1
            if args.delay:
                time.sleep(args.delay)
        if sent >= args.limit:
            break

    producer.flush()
    print(f"Streamed {sent:,} held-out transactions (step > {args.start_step}).")


if __name__ == "__main__":
    main()