# seed_redis.py
# Rebuilds the 24-hour velocity state at the handoff point (step 600) so live
# scoring starts from the same history the model was trained with.
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import redis

DATA = "data/PS_20174392719_1491204439457_log.csv"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
HANDOFF_STEP = 600        # replay starts at step 601
WINDOW_HOURS = 24
KEY_TTL_S = WINDOW_HOURS * 3600 + 3600

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

df = pd.read_csv(DATA, usecols=["step", "amount", "nameOrig", "nameDest"])
# Same window the scorer uses at step 601: events with step > 601 - 24 = 577
df = df[(df.step > HANDOFF_STEP - WINDOW_HOURS) & (df.step <= HANDOFF_STEP)]

pipe = r.pipeline(transaction=False)
rows = 0
for row in df.itertuples(index=False):
    key = f"vel:{row.nameOrig}"
    ts_ms = int((BASE_TIME + timedelta(hours=int(row.step))).timestamp() * 1000)
    member = f"{uuid.uuid4()}|{row.nameDest}|{float(row.amount)}"
    pipe.zadd(key, {member: ts_ms})
    pipe.expire(key, KEY_TTL_S)
    rows += 1
    if rows % 10_000 == 0:
        pipe.execute()
pipe.execute()
print(f"Seeded {rows:,} events into Redis for steps 577-600.")