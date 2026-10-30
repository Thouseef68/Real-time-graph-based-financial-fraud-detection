"""Tests for feature store implementations."""
import pytest
import numpy as np

from fraudengine.features.store import InMemoryFeatureStore, VelocityFeatures, BehaviouralProfile


class TestInMemoryFeatureStore:
    """Tests for InMemoryFeatureStore."""

    def setup_method(self):
        self.store = InMemoryFeatureStore(windows=[1, 6, 24])

    def teardown_method(self):
        self.store.close()

    def test_velocity_empty_account(self):
        """Velocity for unknown account returns zeros."""
        vel = self.store.get_velocity("ACC001", step=100)
        for window in [1, 6, 24]:
            v = vel[window]
            assert v.count == 0
            assert v.sum == 0.0
            assert v.distinct_payees == 0
            assert v.amount_vs_sum == 0.0

    def test_velocity_single_txn(self):
        """Single transaction adds to velocity."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        vel = self.store.get_velocity("ACC001", step=10)
        for window in [1, 6, 24]:
            v = vel[window]
            assert v.count == 1
            assert v.sum == 100.0
            assert v.distinct_payees == 1
            assert abs(v.amount_vs_sum - 100.0/101.0) < 1e-9

    def test_velocity_multiple_txns_same_payee(self):
        """Multiple txns to same payee increment count but not distinct_payees."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        self.store.update_velocity("ACC001", "PAY001", 200.0, step=11, txn_id="txn2")
        vel = self.store.get_velocity("ACC001", step=11)
        v = vel[24]
        assert v.count == 2
        assert v.sum == 300.0
        assert v.distinct_payees == 1
        assert abs(v.amount_vs_sum - 200.0/301.0) < 1e-9

    def test_velocity_multiple_txns_different_payees(self):
        """Multiple txns to different payees increment both."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        self.store.update_velocity("ACC001", "PAY002", 200.0, step=11, txn_id="txn2")
        vel = self.store.get_velocity("ACC001", step=11)
        v = vel[24]
        assert v.count == 2
        assert v.sum == 300.0
        assert v.distinct_payees == 2

    def test_velocity_window_expiry(self):
        """Events outside window are excluded."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=40, txn_id="txn1")
        self.store.update_velocity("ACC001", "PAY002", 200.0, step=59, txn_id="txn2")

        vel = self.store.get_velocity("ACC001", step=60, windows=[1, 24])
        assert vel[1].count == 1
        assert vel[1].sum == 200.0
        assert vel[24].count == 2
        assert vel[24].sum == 300.0

    def test_velocity_distinct_accounts(self):
        """Velocity is per-account."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        self.store.update_velocity("ACC002", "PAY001", 200.0, step=10, txn_id="txn2")

        vel1 = self.store.get_velocity("ACC001", step=10)
        vel2 = self.store.get_velocity("ACC002", step=10)

        assert vel1[24].count == 1
        assert vel2[24].count == 1

    def test_behavioural_new_account(self):
        """Behavioural profile for new account returns None."""
        profile = self.store.get_behavioural("ACC001")
        assert profile is None

    def test_behavioural_first_txn(self):
        """First transaction initializes profile."""
        self.store.update_behavioural(
            "ACC001", amount=100.0, step=10, payee_id="PAY001",
            device_id="DEV001", ip_prefix="192.168.1", hour_of_day=12
        )
        profile = self.store.get_behavioural("ACC001")
        assert profile is not None
        assert profile.n_txns == 1
        assert profile.amount_mean == 100.0
        assert profile.amount_std == 0.0
        assert profile.last_txn_step == 10
        assert "PAY001" in profile.known_payees
        assert "DEV001" in profile.known_devices
        assert "192.168.1" in profile.known_ip_prefixes
        assert profile.hour_of_day_counts[12] == 1

    def test_behavioural_welford_mean_std(self):
        """Welford's algorithm correctly computes mean and std."""
        amounts = [100.0, 200.0, 300.0]
        for i, amt in enumerate(amounts):
            self.store.update_behavioural(
                "ACC001", amount=amt, step=10+i, payee_id="PAY001",
                device_id="DEV001", ip_prefix="192.168.1", hour_of_day=12
            )

        profile = self.store.get_behavioural("ACC001")
        assert profile.n_txns == 3
        assert abs(profile.amount_mean - 200.0) < 1e-9
        expected_std = np.std(amounts, ddof=0)
        assert abs(profile.amount_std - expected_std) < 1e-6

    def test_device_info_new_device(self):
        """Device info for new device returns empty."""
        info = self.store.get_device_info("DEV001")
        assert info["accounts"] == set()
        assert info["ip_prefixes"] == set()
        assert info["first_seen_step"] is None

    def test_device_info_update(self):
        """Device info updates correctly."""
        self.store.update_device_info("DEV001", "ACC001", "192.168.1.0/24")
        info = self.store.get_device_info("DEV001")
        assert "ACC001" in info["accounts"]
        assert "192.168.1.0/24" in info["ip_prefixes"]

    def test_payee_info_new_payee(self):
        """Payee info for new payee returns defaults."""
        info = self.store.get_payee_info("PAY001")
        assert info["senders"] == set()
        assert info["total_inflow"] == 0.0
        assert info["is_merchant"] is False
        assert info["fraud_senders"] == set()

    def test_payee_info_merchant_flag(self):
        """Merchant payees (M prefix) are flagged."""
        info = self.store.get_payee_info("M12345")
        assert info["is_merchant"] is True

    def test_payee_info_update(self):
        """Payee info updates correctly."""
        self.store.update_payee_info("PAY001", "ACC001", 100.0, step=10, is_fraud=0)
        info = self.store.get_payee_info("PAY001")
        assert "ACC001" in info["senders"]
        assert info["total_inflow"] == 100.0

    def test_payee_info_fraud_sender(self):
        """Fraud senders are tracked separately."""
        self.store.update_payee_info("PAY001", "ACC001", 100.0, step=10, is_fraud=1)
        info = self.store.get_payee_info("PAY001")
        assert "ACC001" in info["fraud_senders"]


class TestPointInTime:
    """Tests for point-in-time correctness."""

    def setup_method(self):
        self.store = InMemoryFeatureStore(windows=[1, 6, 24])

    def teardown_method(self):
        self.store.close()

    def test_velocity_pit(self):
        """Velocity at step t doesn't include events after t."""
        self.store.update_velocity("ACC001", "PAY001", 100.0, step=10, txn_id="txn1")
        self.store.update_velocity("ACC001", "PAY002", 200.0, step=20, txn_id="txn2")
        self.store.update_velocity("ACC001", "PAY003", 300.0, step=30, txn_id="txn3")

        vel = self.store.get_velocity("ACC001", step=20, windows=[24])
        assert vel[24].count == 2
        assert vel[24].sum == 300.0

        vel = self.store.get_velocity("ACC001", step=30, windows=[24])
        assert vel[24].count == 3
        assert vel[24].sum == 600.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])