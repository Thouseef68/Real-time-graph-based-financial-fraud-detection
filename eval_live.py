# eval_live.py
import json
import time

import numpy as np
from confluent_kafka import Consumer
from sklearn.metrics import average_precision_score, roc_auc_score

cfg = json.load(open("model/config.json"))
REVIEW_T, BLOCK_T = cfg["review_threshold"], cfg["block_threshold"]
IDLE_SECONDS = 60   # stop after this long with no new decisions

consumer = Consumer({
    "bootstrap.servers": "localhost:9092",
    "group.id": f"evaluator_{int(time.time())}",   # fresh group, reads from the start
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
})
consumer.subscribe(["decisions"])

labels, scores = [], []
last_msg = time.time()
print("Reading decisions... (stops after 60s with no new messages)")
while time.time() - last_msg < IDLE_SECONDS:
    msg = consumer.poll(1.0)
    if msg is None or msg.error():
        continue
    last_msg = time.time()
    d = json.loads(msg.value())
    labels.append(d["label"])
    scores.append(d["score"])
consumer.close()

y = np.array(labels)
p = np.array(scores)
review = p >= REVIEW_T
block = p >= BLOCK_T

tp = int((review & (y == 1)).sum())
fp = int((review & (y == 0)).sum())
fn = int((~review & (y == 1)).sum())
block_tp = int((block & (y == 1)).sum())

print(f"\nLive decisions scored: {len(y):,}  fraud: {int(y.sum())} ({y.mean():.4%})")
print(f"PR-AUC:  {average_precision_score(y, p):.4f}")
print(f"ROC-AUC: {roc_auc_score(y, p):.4f}")
print(f"REVIEW (>= {REVIEW_T:.3f}): recall={tp/(tp+fn+1e-9):.3f} "
      f"precision={tp/(tp+fp+1e-9):.3f} flagged={int(review.sum())}")
print(f"BLOCK  (>= {BLOCK_T:.3f}): precision={block_tp/(block.sum()+1e-9):.3f} "
      f"flagged={int(block.sum())}")