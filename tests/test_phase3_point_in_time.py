"""Phase 3 Test (a): Point-in-time correctness test.

A transaction's features must be completely invariant to whether subsequent
events exist or have been truncated from the event stream.
"""

import pytest
import pandas as pd
import numpy as np

from fraudengine.features.store import InMemoryFeatureStore
from fraudengine.features.engineering import compute_all_features, update_stores


class TestPointInTimeCorrectness:
    """Validate point-in-time invariant across all feature groups."""

    def test_point_in_time_future_invariance(self):
        """Features for event k at step t must not change when future events t+1...t+N are removed."""
        # Generate a small sequence of transactions across time
        events = [
            {"txn_id": "T1", "step": 10, "account_id": "A1", "payee_id": "P1", "amount": 100.0,
             "old_balance_orig": 1000.0, "new_balance_orig": 900.0, "device_id": "D1", "ip_prefix": "192.168.1", "label": 0},
            {"txn_id": "T2", "step": 11, "account_id": "A1", "payee_id": "P2", "amount": 250.0,
             "old_balance_orig": 900.0, "new_balance_orig": 650.0, "device_id": "D1", "ip_prefix": "192.168.1", "label": 0},
            {"txn_id": "T3", "step": 12, "account_id": "A1", "payee_id": "P1", "amount": 300.0,
             "old_balance_orig": 650.0, "new_balance_orig": 350.0, "device_id": "D2", "ip_prefix": "10.0.1", "label": 0},
            {"txn_id": "T4", "step": 15, "account_id": "A1", "payee_id": "P3", "amount": 50.0,
             "old_balance_orig": 350.0, "new_balance_orig": 300.0, "device_id": "D1", "ip_prefix": "192.168.1", "label": 0},
            {"txn_id": "T5", "step": 20, "account_id": "A1", "payee_id": "P4", "amount": 80.0,
             "old_balance_orig": 300.0, "new_balance_orig": 220.0, "device_id": "D1", "ip_prefix": "192.168.1", "label": 0},
        ]

        # Target event to check is T3 (step 12)
        # Run 1: Stream contains all events T1, T2, T3, T4, T5
        store_full = InMemoryFeatureStore()
        features_full = {}
        for ev in events:
            feat = compute_all_features(store_full, ev)
            update_stores(store_full, ev)
            if ev["txn_id"] == "T3":
                features_full = feat

        # Run 2: Stream is truncated at T3 (future events T4, T5 removed)
        store_truncated = InMemoryFeatureStore()
        features_truncated = {}
        for ev in events[:3]:
            feat = compute_all_features(store_truncated, ev)
            update_stores(store_truncated, ev)
            if ev["txn_id"] == "T3":
                features_truncated = feat

        # Assert every single feature is identical
        for k in features_full:
            assert abs(features_full[k] - features_truncated[k]) < 1e-12, (
                f"Feature {k} violated point-in-time invariant: full={features_full[k]}, truncated={features_truncated[k]}"
            )
