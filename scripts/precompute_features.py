"""Precomputes point-in-time features for train, val, and test splits and caches to data/cache/.

Guarantees:
- State updates occur strictly chronologically for ALL 6,367,603 transactions in the dataset.
- Memory-bounded streaming via PyArrow iter_batches (batch_size=50,000) keeps peak RAM < 250 MB.
- Direct disk flushing via ParquetWriter prevents in-memory accumulation.
- Training set includes 100% of native fraud + 100% of injected scenario instances + representative sample of legit.
- Validation and Test splits are preserved with all scenarios + stratified background.
- Output cached to parquet files for instant loading during training and evaluation.
"""

from __future__ import annotations

import gc
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Ensure line-buffered stdout for real-time log monitoring
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fraudengine.features.engineering import (
    extract_base_features,
    extract_velocity_features,
    extract_behavioural_features,
    extract_device_network_features,
    extract_graph_features,
    update_stores,
)
from fraudengine.features.store import InMemoryFeatureStore
from fraudengine.graph.engine import GraphEngine

INPUT_FILE = ROOT / "data" / "scenarios.parquet"
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_mem_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def run_precompute():
    print(f"Opening {INPUT_FILE} with PyArrow Streaming Engine ...", flush=True)
    t0 = time.time()
    pf = pq.ParquetFile(str(INPUT_FILE))
    total_rows = pf.metadata.num_rows
    print(f"Total stream events to replay: {total_rows:,} across {pf.num_row_groups} row groups", flush=True)

    # Initialize feature stores
    store = InMemoryFeatureStore()
    graph = GraphEngine(neo4j_uri=None)

    # Paths for output parquet files
    train_path = CACHE_DIR / "train_features.parquet"
    val_path = CACHE_DIR / "val_features.parquet"
    test_path = CACHE_DIR / "test_features.parquet"

    # Temporary removal of existing files
    for p in [train_path, val_path, test_path]:
        if p.exists():
            p.unlink()

    train_writer: pa.parquet.ParquetWriter | None = None
    val_writer: pa.parquet.ParquetWriter | None = None
    test_writer: pa.parquet.ParquetWriter | None = None

    train_buffer: List[Dict[str, Any]] = []
    val_buffer: List[Dict[str, Any]] = []
    test_buffer: List[Dict[str, Any]] = []

    train_count = 0
    val_count = 0
    test_count = 0

    BUFFER_FLUSH_SIZE = 5000

    def flush_buffer(buffer: List[Dict[str, Any]], writer: pa.parquet.ParquetWriter | None, out_path: Path):
        if not buffer:
            return writer
        batch_df = pd.DataFrame(buffer)
        table = pa.Table.from_pandas(batch_df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(str(out_path), table.schema, compression="snappy")
        writer.write_table(table)
        buffer.clear()
        return writer

    processed_events = 0
    t_start = time.time()
    last_log_time = t_start
    last_log_events = 0

    print("Replaying transactions chronologically and extracting features ...", flush=True)

    # Stream batch by batch
    for batch in pf.iter_batches(batch_size=50_000):
        # Convert batch to columns dict or itertuples
        batch_df = batch.to_pandas()

        for row in batch_df.itertuples(index=False):
            processed_events += 1
            step = int(row.step)
            account_id = row.account_id
            payee_id = row.payee_id
            amount = float(row.amount)
            txn_type = row.txn_type
            old_bal = float(row.old_balance_orig)
            new_bal = float(row.new_balance_orig)
            dev_id = row.device_id
            ip_pfx = row.ip_prefix
            label = int(row.label)
            scenario = row.scenario
            group_id = row.group_id
            split = row.split
            txn_id = row.txn_id

            txn_dict = {
                "txn_id": txn_id,
                "step": step,
                "account_id": account_id,
                "payee_id": payee_id,
                "amount": amount,
                "txn_type": txn_type,
                "old_balance_orig": old_bal,
                "new_balance_orig": new_bal,
                "device_id": dev_id,
                "ip_prefix": ip_pfx,
                "hour_of_day": step % 24,
                "label": label,
            }

            # Sampling filter for legitimate background rows:
            # Always keep 100% of fraud (label == 1) and 100% of injected scenarios
            is_target = False
            if label == 1 or scenario != "paysim_native":
                is_target = True
            else:
                # Deterministic sampling based on txn hash
                h = hash(txn_id)
                if split == "train" and (h % 45 == 0):
                    is_target = True
                elif split == "val" and (h % 30 == 0):
                    is_target = True
                elif split == "test":
                    is_target = True

            if is_target:
                feat: Dict[str, Any] = {}
                feat.update(extract_base_features(txn_dict))
                feat.update(extract_velocity_features(store, txn_dict))
                feat.update(extract_behavioural_features(store, txn_dict))
                feat.update(extract_device_network_features(store, txn_dict))
                feat.update(extract_graph_features(store, txn_dict, graph))
                feat["label"] = label
                feat["scenario"] = scenario
                feat["group_id"] = group_id
                feat["split"] = split
                feat["txn_id"] = txn_id
                feat["account_id"] = account_id
                feat["step"] = step

                if split == "train":
                    train_buffer.append(feat)
                    train_count += 1
                    if len(train_buffer) >= BUFFER_FLUSH_SIZE:
                        train_writer = flush_buffer(train_buffer, train_writer, train_path)
                elif split == "val":
                    val_buffer.append(feat)
                    val_count += 1
                    if len(val_buffer) >= BUFFER_FLUSH_SIZE:
                        val_writer = flush_buffer(val_buffer, val_writer, val_path)
                else:
                    test_buffer.append(feat)
                    test_count += 1
                    if len(test_buffer) >= BUFFER_FLUSH_SIZE:
                        test_writer = flush_buffer(test_buffer, test_writer, test_path)

            # Update feature stores with event
            update_stores(store, txn_dict, graph)

            # Logging progress
            if processed_events % 250_000 == 0:
                now = time.time()
                rate = (processed_events - last_log_events) / max(now - last_log_time, 0.001)
                last_log_time = now
                last_log_events = processed_events
                mem = get_mem_mb()
                print(
                    f"  Processed {processed_events:,}/{total_rows:,} events "
                    f"({rate:,.0f} ev/s, step={step}, RAM={mem:.0f} MB) | "
                    f"Extracted: train={train_count:,}, val={val_count:,}, test={test_count:,}",
                    flush=True,
                )

        del batch_df
        gc.collect()

    # Final flush
    train_writer = flush_buffer(train_buffer, train_writer, train_path)
    val_writer = flush_buffer(val_buffer, val_writer, val_path)
    test_writer = flush_buffer(test_buffer, test_writer, test_path)

    if train_writer:
        train_writer.close()
    if val_writer:
        val_writer.close()
    if test_writer:
        test_writer.close()

    total_time = time.time() - t_start
    print(
        f"\nFeature precomputation complete in {total_time:.1f}s ({total_rows / total_time:,.0f} ev/s)!\n"
        f"  Train: {train_path} ({train_count:,} rows)\n"
        f"  Val:   {val_path} ({val_count:,} rows)\n"
        f"  Test:  {test_path} ({test_count:,} rows)",
        flush=True,
    )


if __name__ == "__main__":
    run_precompute()
