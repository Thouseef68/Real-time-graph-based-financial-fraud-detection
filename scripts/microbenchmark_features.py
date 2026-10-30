"""Phase 3 Test (c): Microbenchmark of per-feature-group latency.

Measures p50, p95, p99 latency (in milliseconds and microseconds) and throughput (txns/sec)
for each individual feature group as well as full feature extraction.
Outputs are saved to results_v2/phase3_feature_benchmark.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.features.engineering import (
    extract_base_features,
    extract_velocity_features,
    extract_behavioural_features,
    extract_device_network_features,
    extract_graph_features,
    compute_all_features,
    update_stores,
)
from fraudengine.features.store import InMemoryFeatureStore
from fraudengine.graph.engine import GraphEngine

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "results_v2" / "phase3_feature_benchmark.json"


def run_benchmark(n_warmup: int = 500, n_measured: int = 5000) -> Dict[str, Any]:
    print(f"Running Feature Group Latency Microbenchmark ({n_measured:,} iterations) ...")

    store = InMemoryFeatureStore(windows=[1, 6, 24])
    graph_engine = GraphEngine(neo4j_uri=None)  # Hot-path in-memory graph
    rng = np.random.RandomState(42)

    # Pre-populate state with warmup transactions so profiles and velocities are warm
    accounts = [f"ACC_{i:04d}" for i in range(100)]
    payees = [f"PAY_{i:04d}" for i in range(200)]
    devices = [f"DEV_{i:04d}" for i in range(50)]
    ips = [f"192.168.1.{i}" for i in range(20)]

    for i in range(n_warmup):
        step = 10 + (i // 50)
        txn = {
            "txn_id": f"WARM_{i}",
            "account_id": rng.choice(accounts),
            "payee_id": rng.choice(payees),
            "amount": float(rng.uniform(10.0, 3000.0)),
            "step": step,
            "old_balance_orig": 10000.0,
            "new_balance_orig": 8000.0,
            "device_id": rng.choice(devices),
            "ip_prefix": rng.choice(ips),
            "hour_of_day": step % 24,
            "label": 0,
            "txn_type": "TRANSFER",
        }
        update_stores(store, txn, graph_engine=graph_engine)

    # Benchmark test transaction pool
    test_txns = []
    for i in range(n_measured):
        step = 50 + (i // 100)
        test_txns.append({
            "txn_id": f"BENCH_{i}",
            "account_id": rng.choice(accounts),
            "payee_id": rng.choice(payees),
            "amount": float(rng.uniform(10.0, 5000.0)),
            "step": step,
            "old_balance_orig": 12000.0,
            "new_balance_orig": 10000.0,
            "device_id": rng.choice(devices),
            "ip_prefix": rng.choice(ips),
            "hour_of_day": step % 24,
            "label": 0,
            "txn_type": "TRANSFER",
        })

    groups = {
        "base": lambda txn: extract_base_features(txn),
        "velocity": lambda txn: extract_velocity_features(store, txn),
        "behavioural": lambda txn: extract_behavioural_features(store, txn),
        "device_network": lambda txn: extract_device_network_features(store, txn),
        "graph": lambda txn: extract_graph_features(store, txn, graph_engine=graph_engine),
        "all_combined": lambda txn: compute_all_features(store, txn, graph_engine=graph_engine),
    }

    results = {}

    print(f"\n{'Feature Group':<18} | {'p50 (µs)':<10} | {'p95 (µs)':<10} | {'p99 (µs)':<10} | {'Mean (µs)':<10} | {'Throughput (tx/s)':<18}")
    print("-" * 88)

    for name, func in groups.items():
        durations = []
        for txn in test_txns:
            t0 = time.perf_counter()
            _ = func(txn)
            t1 = time.perf_counter()
            durations.append((t1 - t0) * 1e6)  # microseconds

        durations = np.array(durations)
        p50 = float(np.percentile(durations, 50))
        p95 = float(np.percentile(durations, 95))
        p99 = float(np.percentile(durations, 99))
        mean_us = float(np.mean(durations))
        throughput = float(1e6 / mean_us) if mean_us > 0 else 0.0

        results[name] = {
            "p50_us": round(p50, 2),
            "p95_us": round(p95, 2),
            "p99_us": round(p99, 2),
            "mean_us": round(mean_us, 2),
            "p50_ms": round(p50 / 1000.0, 4),
            "p95_ms": round(p95 / 1000.0, 4),
            "p99_ms": round(p99 / 1000.0, 4),
            "throughput_txns_per_sec": round(throughput, 1),
        }

        print(f"{name:<18} | {p50:<10.1f} | {p95:<10.1f} | {p99:<10.1f} | {mean_us:<10.1f} | {throughput:<18,.0f}")

    store.close()
    graph_engine.close()

    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "measured_transactions": n_measured,
        "results": results,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSaved microbenchmark results to {OUTPUT_FILE}")
    return summary


if __name__ == "__main__":
    run_benchmark()
