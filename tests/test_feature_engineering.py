"""Tests for feature engineering."""
import pytest
import numpy as np

from fraudengine.features.store import InMemoryFeatureStore
from fraudengine.features.engineering import (
    compute_all_features, update_stores, extract_base_features,
    extract_velocity_features, extract_behavioural_features,
    extract_device_network_features, extract_graph_features,
    ALL_FEATURES, FEATURE_GROUPS
)


class TestFeatureEngineering:
    """Tests for feature extraction functions."""

    def setup_method(self):
        self.store = InMemoryFeatureStore(windows=[1, 6, 24])

    def teardown_method(self):
        self.store.close()

    def test_base_features(self):
        """Base features extracted correctly."""
        txn = {
            "amount": 1000.0,
            "txn_type": "TRANSFER",
            "old_balance_orig": 5000.0,
            "new_balance_orig": 4000.0,
        }
        features = extract_base_features(txn)

        assert features["amount"] == 1000.0
        assert features["type_code"] == 4.0  # TRANSFER
        assert abs(features["amount_to_balance"] - 1000/5001) < 1e-9
        assert features["orig_drained"] == 0.0
        assert abs(features["new_balance_to_old"] - 4000/5001) < 1e-9
        assert abs(features["balance_change_ratio"] - 1000/5001) < 1e-9

    def test_base_features_drained(self):
        """orig_drained flag works."""
        txn = {
            "amount": 5000.0,
            "txn_type": "TRANSFER",
            "old_balance_orig": 5000.0,
            "new_balance_orig": 0.0,
        }
        features = extract_base_features(txn)
        assert features["orig_drained"] == 1.0

    def test_velocity_features(self):
        """Velocity features from store (historical only)."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        self.store.update_velocity("ACC001", "PAY002", 200.0, step=11, txn_id="txn2")
        self.store.update_velocity("ACC001", "PAY001", 300.0, step=12, txn_id="txn3")

        txn = {"account_id": "ACC001", "step": 12, "amount": 400.0}
        features = extract_velocity_features(self.store, txn, windows=[1, 6, 24])

        v = features
        assert v["count_1h"] == 2  # steps 11,12
        assert v["sum_1h"] == 500.0  # 200+300
        assert v["distinct_payees_1h"] == 2  # PAY001, PAY002
        assert abs(v["amount_vs_sum_1h"] - 300.0/501.0) < 1e-9

    def test_behavioural_features_new_account(self):
        """Behavioural features for new account."""
        txn = {
            "account_id": "ACC001", "amount": 100.0,
            "payee_id": "PAY001", "step": 10,
            "device_id": "DEV001", "ip_prefix": "192.168.1",
            "hour_of_day": 12
        }
        features = extract_behavioural_features(self.store, txn)

        assert features["amount_zscore"] == 0.0
        assert features["new_payee_flag"] == 1.0
        assert features["dormancy_days"] == 0.0
        assert features["device_count"] == 0.0

    def test_behavioural_features_existing_account(self):
        """Behavioural features for existing account."""
        self.store.update_behavioural("ACC001", 100.0, 10, "PAY001", "DEV001", "192.168.1", 12)
        self.store.update_behavioural("ACC001", 200.0, 11, "PAY002", "DEV001", "192.168.1", 13)

        txn = {
            "account_id": "ACC001", "amount": 500.0,
            "payee_id": "PAY003", "step": 12,
            "device_id": "DEV001", "ip_prefix": "192.168.1",
            "hour_of_day": 14
        }
        features = extract_behavioural_features(self.store, txn)

        assert abs(features["amount_zscore"] - 7.0) < 1e-6
        assert features["new_payee_flag"] == 1.0
        assert features["dormancy_days"] == 1/24
        assert features["device_count"] == 1.0
        assert features["time_since_last_txn"] == 1.0

    def test_device_network_features(self):
        """Device/network features."""
        self.store.update_device_info("DEV001", "ACC001", "192.168.1.0/24")
        self.store.update_device_info("DEV001", "ACC002", "192.168.1.0/24")

        txn = {"account_id": "ACC001", "device_id": "DEV001", "ip_prefix": "192.168.1.0/24", "step": 10}
        features = extract_device_network_features(self.store, txn)

        assert features["is_new_device"] == 0.0
        assert features["accounts_per_device"] == 2.0
        assert features["ip_prefix_sharing_count"] == 1.0

    def test_device_network_new_device(self):
        """New device flag."""
        txn = {"account_id": "ACC001", "device_id": "DEV999", "ip_prefix": "10.0.0.0/8", "step": 10}
        features = extract_device_network_features(self.store, txn)

        assert features["is_new_device"] == 1.0
        assert features["accounts_per_device"] == 0.0

    def test_graph_features(self):
        """Graph features from payee info."""
        self.store.update_payee_info("PAY001", "ACC001", 100.0, 10, 0)
        self.store.update_payee_info("PAY001", "ACC002", 200.0, 11, 1)

        txn = {"payee_id": "PAY001", "account_id": "ACC003", "amount": 300.0, "step": 12}
        features = extract_graph_features(self.store, txn)

        assert features["payee_fan_in_1h"] == 2.0
        assert features["payee_fan_in_24h"] == 2.0
        assert features["is_merchant"] == 0.0
        assert features["fraud_exposure_2hop"] == 1.0
        assert abs(features["payee_outflow_inflow_ratio_24h"] - 0) < 1e-9

    def test_graph_features_merchant(self):
        """Merchant flag for M-prefixed payees."""
        txn = {"payee_id": "M12345", "account_id": "ACC001", "amount": 100.0, "step": 10}
        features = extract_graph_features(self.store, txn)
        assert features["is_merchant"] == 1.0

    def test_compute_all_features(self):
        """Full feature computation."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, 10, "txn1")
        self.store.update_behavioural("ACC001", 100.0, 10, "PAY001", "DEV001", "192.168.1", 12)
        self.store.update_device_info("DEV001", "ACC001", "192.168.1.0/24")
        self.store.update_payee_info("PAY001", "ACC001", 100.0, 10, 0)

        txn = {
            "txn_id": "txn_new", "account_id": "ACC001", "payee_id": "PAY002",
            "amount": 200.0, "ts": "2026-01-01T10:00:00Z", "step": 11,
            "txn_type": "TRANSFER", "old_balance_orig": 4800.0, "new_balance_orig": 4600.0,
            "device_id": "DEV001", "ip_prefix": "192.168.1.0/24", "hour_of_day": 12,
            "label": 0
        }

        features = compute_all_features(self.store, txn)

        expected_features = [f for f in ALL_FEATURES if not f.startswith("isolation_forest") and not f.startswith("autoencoder")]
        for feat in expected_features:
            assert feat in features, f"Missing feature: {feat}"

        assert features["amount"] == 200.0
        assert features["orig_drained"] == 0.0
        assert features["count_1h"] == 1.0
        assert features["new_payee_flag"] == 1.0
        assert features["is_new_device"] == 0.0

    def test_update_stores(self):
        """update_stores updates all stores."""
        txn = {
            "txn_id": "txn1", "account_id": "ACC001", "payee_id": "PAY001",
            "amount": 100.0, "step": 10, "label": 0,
            "device_id": "DEV001", "ip_prefix": "192.168.1.0/24", "hour_of_day": 12
        }
        update_stores(self.store, txn)

        vel = self.store.get_velocity("ACC001", 10, [24])
        assert vel[24].count == 1

        beh = self.store.get_behavioural("ACC001")
        assert beh.n_txns == 1
        assert beh.amount_mean == 100.0

        dev = self.store.get_device_info("DEV001")
        assert "ACC001" in dev["accounts"]

        pay = self.store.get_payee_info("PAY001")
        assert "ACC001" in pay["senders"]
        assert pay["total_inflow"] == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])