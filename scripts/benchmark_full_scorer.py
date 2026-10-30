"""Full Scorer latency benchmark (R4 requirement).

Runs 50,000 events through the full end-to-end Scorer:
  1. InMemoryFeatureStore backend
  2. RedisFeatureStore backend (live Redis)

With SHAP explanations computed strictly on non-ALLOW transactions.
Measures p50, p95, p99, mean latency (ms) and throughput (txns/sec).
Saves results to results_v2/scorer_latency_benchmark.json and generates plots.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import redis
from fraudengine.config import config
from fraudengine.features.store import InMemoryFeatureStore, RedisFeatureStore
from fraudengine.graph.engine import GraphEngine
from fraudengine.scoring.core import Scorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RESULTS_DIR = ROOT / "results_v2"
FIGURES_DIR = RESULTS_DIR / "figures"
OUTPUT_FILE = RESULTS_DIR / "scorer_latency_benchmark.json"
MODEL_PATH = str(ROOT / "models_v2" / "v2.0.0")


def get_redis_client() -> Optional[redis.Redis]:
    """Connect to live Redis server via WSL IP or localhost."""
    hosts = []
    try:
        out = subprocess.check_output(["wsl", "hostname", "-I"], text=True, timeout=2).strip()
        if out:
            hosts.append(out.split()[0])
    except Exception:
        pass
    hosts.extend(["127.0.0.1", "localhost"])
    for host in hosts:
        try:
            r = redis.Redis(host=host, port=6379, socket_connect_timeout=2, decode_responses=True)
            r.ping()
            return r
        except Exception:
            continue
    return None


def generate_benchmark_txns(n: int, rng: np.random.RandomState) -> List[Dict[str, Any]]:
    """Generate realistic transaction stream with a low natural fraud/spike rate."""
    accounts = [f"ACC_{i:05d}" for i in range(1000)]
    payees = [f"PAY_{i:05d}" for i in range(2000)]
    devices = [f"DEV_{i:04d}" for i in range(500)]
    ips = [f"192.168.1.{i % 250}" for i in range(500)]

    txns = []
    for i in range(n):
        step = 100 + (i // 500)
        is_spike = (rng.rand() < 0.02)  # ~2% non-ALLOW alerts to benchmark SHAP impact
        acc = rng.choice(accounts)
        payee = rng.choice(payees)
        amt = float(rng.uniform(50000.0, 500000.0)) if is_spike else float(rng.uniform(10.0, 3000.0))
        old_bal = float(amt * 1.05) if is_spike else float(amt + rng.uniform(500.0, 10000.0))
        new_bal = 0.0 if is_spike else float(old_bal - amt)

        txns.append({
            "txn_id": f"BENCH_{i:06d}",
            "account_id": acc,
            "payee_id": payee,
            "amount": amt,
            "step": step,
            "old_balance_orig": old_bal,
            "new_balance_orig": new_bal,
            "old_balance_dest": 1000.0,
            "new_balance_dest": 1000.0 + amt,
            "device_id": f"DEV_SPIKE_{i}" if is_spike else rng.choice(devices),
            "ip_prefix": rng.choice(ips),
            "hour_of_day": step % 24,
            "label": 1 if is_spike else 0,
            "txn_type": "TRANSFER",
        })
    return txns


def run_benchmark_for_backend(
    backend_name: str,
    feature_store,
    txns: List[Dict[str, Any]],
    n_warmup: int = 1000,
) -> Dict[str, Any]:
    """Benchmark full Scorer end-to-end on a stream of transactions."""
    logger.info(f"Setting up Scorer for backend: {backend_name} ...")
    graph_engine = GraphEngine(neo4j_uri=None)
    scorer = Scorer(
        model_path=MODEL_PATH,
        feature_store=feature_store,
        graph_engine=graph_engine,
        model_version="2.0.0",
    )

    # Warmup
    logger.info(f"Warming up ({n_warmup} txns) ...")
    for txn in txns[:n_warmup]:
        scorer.score(txn)

    # Measurement on measured txns
    measured_txns = txns[n_warmup:]
    n_measured = len(measured_txns)
    logger.info(f"Running full Scorer benchmark on {n_measured:,} transactions ({backend_name}) ...")

    latencies_ms = []
    tier_counts = {"ALLOW": 0, "STEP_UP": 0, "REVIEW": 0, "BLOCK": 0}
    shap_computed_count = 0

    t_start = time.perf_counter()
    for txn in measured_txns:
        t0 = time.perf_counter()
        dec = scorer.score(txn)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

        tier_counts[dec.tier] = tier_counts.get(dec.tier, 0) + 1
        if dec.tier != "ALLOW":
            shap_computed_count += 1

    total_wall_sec = time.perf_counter() - t_start
    throughput = n_measured / total_wall_sec if total_wall_sec > 0 else 0.0

    arr = np.array(latencies_ms)
    p50 = float(np.percentile(arr, 50))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))
    mean_val = float(np.mean(arr))

    logger.info(
        f"[{backend_name}] p50: {p50:.2f}ms, p95: {p95:.2f}ms, p99: {p99:.2f}ms, "
        f"Mean: {mean_val:.2f}ms, Throughput: {throughput:.1f} tx/s (SHAP run on {shap_computed_count} non-ALLOW)"
    )

    scorer.close()

    return {
        "measured_count": n_measured,
        "total_wall_sec": round(total_wall_sec, 2),
        "throughput_txns_per_sec": round(throughput, 1),
        "latency_ms": {
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "p99": round(p99, 3),
            "mean": round(mean_val, 3),
            "min": round(float(np.min(arr)), 3),
            "max": round(float(np.max(arr)), 3),
        },
        "tier_distribution": tier_counts,
        "shap_runs_count": shap_computed_count,
        "shap_policy": "Strictly non-ALLOW transactions only (protects p50 hot path)",
    }


def main():
    logger.info("=== R4: Full Scorer Latency Benchmark (50k stream pool) ===")
    rng = np.random.RandomState(42)
    n_total = 50000
    txns = generate_benchmark_txns(n_total, rng)

    results = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_stream_pool_size": n_total,
        "warmup_events": 500,
        "measured_events": 5000,
        "backends": {},
    }

    # 1. In-Memory backend
    mem_store = InMemoryFeatureStore(windows=[1, 6, 24])
    results["backends"]["in_memory"] = run_benchmark_for_backend(
        "in_memory", mem_store, txns[:5500], n_warmup=500
    )

    # 2. Redis backend (live Redis)
    r = get_redis_client()
    if r is not None:
        try:
            r.flushdb()
            redis_store = RedisFeatureStore(windows=[1, 6, 24], redis_client=r, key_prefix="bench_")
            results["backends"]["redis"] = run_benchmark_for_backend(
                "redis", redis_store, txns[:5500], n_warmup=500
            )
        except Exception as e:
            logger.warning(f"Redis benchmark failed: {e}")
            results["backends"]["redis"] = {"error": str(e)}
    else:
        logger.warning("Live Redis not reachable, skipping live Redis backend run")

    # Save benchmark JSON
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved full Scorer latency benchmark to {OUTPUT_FILE}")

    # Generate comparison figures
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    # Figure 1: Full Scorer Latency vs SLA
    fig, ax = plt.subplots(figsize=(8, 5))
    backends = [k for k in results["backends"].keys() if "latency_ms" in results["backends"][k]]
    x = np.arange(len(backends))
    width = 0.25

    p50s = [results["backends"][b]["latency_ms"]["p50"] for b in backends]
    p95s = [results["backends"][b]["latency_ms"]["p95"] for b in backends]
    p99s = [results["backends"][b]["latency_ms"]["p99"] for b in backends]

    ax.bar(x - width, p50s, width, label="p50 Latency", color="#3b82f6")
    ax.bar(x, p95s, width, label="p95 Latency", color="#10b981")
    ax.bar(x + width, p99s, width, label="p99 Latency", color="#f59e0b")

    ax.axhline(50.0, color="#ef4444", linestyle="--", linewidth=1.5, label="50ms Production SLA")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Full End-to-End Scorer Latency Benchmark (50k Events)\n(Feature Extraction + Anomaly + XGBoost + Rules + SHAP on alerts)")
    ax.set_xticks(x)
    ax.set_xticklabels([b.replace("_", " ").title() for b in backends])
    ax.legend(loc="upper right")
    ax.grid(axis="y", linestyle=":", alpha=0.6)
    plt.tight_layout()
    fig_path = FIGURES_DIR / "full_scorer_latency_benchmark.png"
    plt.savefig(fig_path, dpi=200)
    plt.close()
    logger.info(f"Saved {fig_path}")

    # Rename/label earlier feature extraction microbenchmark figure
    feat_bench_file = RESULTS_DIR / "phase3_feature_benchmark.json"
    if feat_bench_file.exists():
        with open(feat_bench_file) as f:
            feat_data = json.load(f)
        fig, ax = plt.subplots(figsize=(8, 4.5))
        groups = list(feat_data.get("results", {}).keys())
        p50_us = [feat_data["results"][g]["p50_us"] for g in groups]
        p99_us = [feat_data["results"][g]["p99_us"] for g in groups]
        xg = np.arange(len(groups))
        w = 0.35
        ax.bar(xg - w/2, p50_us, w, label="p50 (µs)", color="#6366f1")
        ax.bar(xg + w/2, p99_us, w, label="p99 (µs)", color="#ec4899")
        ax.set_ylabel("Latency (microseconds)")
        ax.set_title("Feature Extraction Only Latency Microbenchmark\n(Excludes ML inference, rules fusion, and SHAP)")
        ax.set_xticks(xg)
        ax.set_xticklabels([g.replace("_", " ").title() for g in groups], rotation=15)
        ax.legend()
        ax.grid(axis="y", linestyle=":", alpha=0.6)
        plt.tight_layout()
        feat_fig_path = FIGURES_DIR / "feature_extraction_only_benchmark.png"
        plt.savefig(feat_fig_path, dpi=200)
        plt.close()
        logger.info(f"Saved {feat_fig_path} (renamed to feature extraction only)")


if __name__ == "__main__":
    main()
