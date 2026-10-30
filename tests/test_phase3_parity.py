"""Phase 3 Test (b): Parity test between InMemoryFeatureStore and RedisFeatureStore.

Replays a 20,000-event sequence through both stores and verifies that features
match to 1e-9 across all feature groups.
Isolation rule: uses prefix 'fraud:v2:test_parity:', never FLUSHALL.
"""

import pytest
import redis
import numpy as np

from fraudengine.features.store import InMemoryFeatureStore, RedisFeatureStore
from fraudengine.features.engineering import compute_all_features, update_stores


def get_redis_client():
    hosts = []
    try:
        import subprocess
        out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=2).strip()
        if out:
            hosts.append(out.split()[0])
    except Exception:
        pass
    hosts.extend(["127.0.0.1", "localhost"])

    for host in hosts:
        try:
            r = redis.Redis(host=host, port=6379, decode_responses=True, socket_timeout=5)
            r.ping()
            return r, host
        except Exception:
            continue
    return None, None


class TestFeatureStoreParity:
    """Verify exact parity between InMemory and Redis backends."""

    def cleanup_test_keys(self, r: redis.Redis, prefix: str):
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor=cursor, match=f"{prefix}*", count=1000)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break

    def test_20k_event_parity(self):
        r, active_host = get_redis_client()
        if r is None:
            pytest.skip("Redis server not available at localhost:6379")

        test_prefix = "fraud:v2:test_parity:"
        self.cleanup_test_keys(r, test_prefix)

        in_mem_store = InMemoryFeatureStore(windows=[1, 6, 24])
        redis_store = RedisFeatureStore(
            redis_client=r,
            key_prefix=test_prefix,
            windows=[1, 6, 24]
        )

        n_events = 20000
        rng = np.random.RandomState(42)

        # 50 accounts, 100 payees, 10 devices, 5 IPs
        accounts = [f"ACC_{i:03d}" for i in range(50)]
        payees = [f"PAY_{i:03d}" for i in range(100)]
        devices = [f"DEV_{i:03d}" for i in range(10)]
        ips = [f"192.168.1.{i}" for i in range(5)]

        max_diff = 0.0
        worst_feature = ""

        try:
            step = 10
            for i in range(n_events):
                if i % 100 == 0:
                    step += 1

                account_id = rng.choice(accounts)
                payee_id = rng.choice(payees)
                amount = round(float(rng.uniform(10.0, 5000.0)), 2)
                device_id = rng.choice(devices)
                ip_prefix = rng.choice(ips)
                hour_of_day = int(step % 24)

                txn = {
                    "txn_id": f"TXN_{i}",
                    "account_id": account_id,
                    "payee_id": payee_id,
                    "amount": amount,
                    "step": step,
                    "old_balance_orig": 10000.0,
                    "new_balance_orig": 10000.0 - amount,
                    "device_id": device_id,
                    "ip_prefix": ip_prefix,
                    "hour_of_day": hour_of_day,
                    "label": 0,
                    "txn_type": "TRANSFER",
                }

                # Compute features before updating state (point-in-time)
                feat_mem = compute_all_features(in_mem_store, txn)
                feat_redis = compute_all_features(redis_store, txn)

                step_max_diff = 0.0
                step_worst = ""
                for k in feat_mem:
                    v_mem = feat_mem[k]
                    v_red = feat_redis[k]
                    diff = abs(v_mem - v_red)
                    if diff > step_max_diff:
                        step_max_diff = diff
                        step_worst = k

                if step_max_diff > max_diff:
                    max_diff = step_max_diff
                    worst_feature = step_worst

                if step_max_diff >= 1e-9:
                    print(f"\n[DEBUG i={i}] account={account_id} step={step}")
                    print(f"mem events: {in_mem_store.velocity_state.get(account_id, [])}")
                    raw_redis = redis_store.r.zrange(redis_store._velocity_key(account_id), 0, -1, withscores=True)
                    print(f"redis zset: {raw_redis}")
                    print(f"mem {step_worst}: {feat_mem[step_worst]}")
                    print(f"redis {step_worst}: {feat_redis[step_worst]}")
                    assert step_max_diff < 1e-9, f"Parity mismatch on {step_worst}: mem={feat_mem[step_worst]}, redis={feat_redis[step_worst]}, diff={step_max_diff}"

                # Update state
                update_stores(in_mem_store, txn)
                update_stores(redis_store, txn)

            print(f"\nCompleted 20k event parity test. Max diff across all features: {max_diff:.2e}")
            assert max_diff < 1e-9

        finally:
            in_mem_store.close()
            redis_store.close()
            self.cleanup_test_keys(r, test_prefix)
