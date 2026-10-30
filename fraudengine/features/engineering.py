"""Feature engineering module - computes features from transactions."""
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from fraudengine.features.store import FeatureStore, VelocityFeatures, BehaviouralProfile, create_feature_store


TYPE_CODES = {"CASH_IN": 0, "CASH_OUT": 1, "DEBIT": 2, "PAYMENT": 3, "TRANSFER": 4}

FEATURE_GROUPS = {
    "base": [
        "amount", "type_code", "amount_to_balance", "orig_drained",
        "new_balance_to_old", "balance_change_ratio"
    ],
    "velocity": [
        "count_1h", "sum_1h", "distinct_payees_1h", "amount_vs_sum_1h",
        "count_6h", "sum_6h", "distinct_payees_6h", "amount_vs_sum_6h",
        "count_24h", "sum_24h", "distinct_payees_24h", "amount_vs_sum_24h"
    ],
    "behavioural": [
        "amount_zscore", "new_payee_flag", "payee_first_seen_age",
        "hour_deviation", "time_since_last_txn", "dormancy_days",
        "device_count", "ip_prefix_count"
    ],
    "device_network": [
        "is_new_device", "accounts_per_device", "devices_per_account",
        "ip_prefix_sharing_count", "device_first_seen_age"
    ],
    "graph": [
        "payee_fan_in_1h", "payee_fan_in_24h", "payee_outflow_inflow_ratio_24h",
        "payee_pass_through_flag", "payee_first_seen_age", "is_merchant",
        "fraud_exposure_2hop", "degree", "pagerank"
    ],
    "anomaly": [
        "isolation_forest_score", "autoencoder_reconstruction_error"
    ]
}

ALL_FEATURES = [f for group in FEATURE_GROUPS.values() for f in group]


def extract_base_features(txn: Dict[str, Any]) -> Dict[str, float]:
    """Extract base features from transaction."""
    amount = txn["amount"]
    txn_type = txn.get("txn_type", "TRANSFER")
    old_bal = txn.get("old_balance_orig", 0)
    new_bal = txn.get("new_balance_orig", 0)

    type_code = TYPE_CODES.get(txn_type, -1)
    amount_to_balance = amount / (old_bal + 1.0)
    orig_drained = 1.0 if (old_bal > 0 and new_bal == 0) else 0.0
    new_balance_to_old = new_bal / (old_bal + 1.0)
    balance_change_ratio = (old_bal - new_bal) / (old_bal + 1.0)

    return {
        "amount": float(amount),
        "type_code": float(type_code),
        "amount_to_balance": float(amount_to_balance),
        "orig_drained": float(orig_drained),
        "new_balance_to_old": float(new_balance_to_old),
        "balance_change_ratio": float(balance_change_ratio)
    }


def extract_velocity_features(store: FeatureStore, txn: Dict[str, Any],
                              windows: List[int] = None) -> Dict[str, float]:
    """Extract velocity features from store (historical only, current txn not included)."""
    windows = windows or [1, 6, 24]
    account_id = txn["account_id"]
    step = txn.get("step", 0)
    amount = txn["amount"]

    vel = store.get_velocity(account_id, step, windows)

    features = {}
    for window in windows:
        v = vel[window]
        suffix = f"{window}h"
        features[f"count_{suffix}"] = float(v.count)
        features[f"sum_{suffix}"] = float(v.sum)
        features[f"distinct_payees_{suffix}"] = float(v.distinct_payees)
        features[f"amount_vs_sum_{suffix}"] = float(v.amount_vs_sum)
    return features


def extract_behavioural_features(store: FeatureStore, txn: Dict[str, Any]) -> Dict[str, float]:
    """Extract behavioural features from store."""
    account_id = txn["account_id"]
    amount = txn["amount"]
    payee_id = txn["payee_id"]
    step = txn.get("step", 0)
    device_id = txn.get("device_id", "unknown")
    ip_prefix = txn.get("ip_prefix", "unknown")
    hour_of_day = txn.get("hour_of_day", 0)

    profile = store.get_behavioural(account_id)
    if profile is None:
        return {
            "amount_zscore": 0.0,
            "new_payee_flag": 1.0,
            "payee_first_seen_age": 0.0,
            "hour_deviation": 0.0,
            "time_since_last_txn": 0.0,
            "dormancy_days": 0.0,
            "device_count": 0.0,
            "ip_prefix_count": 0.0
        }

    # Amount z-score
    if profile.amount_std > 0:
        amount_zscore = (amount - profile.amount_mean) / profile.amount_std
    else:
        amount_zscore = 0.0

    # New payee flag
    new_payee_flag = 1.0 if payee_id not in profile.known_payees else 0.0

    # Payee first seen age (approximate)
    payee_first_seen_age = float(len(profile.known_payees))

    # Hour deviation
    total_txns = sum(profile.hour_of_day_counts.values())
    if total_txns > 0:
        expected = total_txns / 24.0
        actual = profile.hour_of_day_counts.get(hour_of_day, 0)
        hour_deviation = (actual - expected) / (expected + 1.0)
    else:
        hour_deviation = 0.0

    # Time since last txn
    time_since_last_txn = float(step - profile.last_txn_step) if profile.last_txn_step >= 0 else 0.0

    # Dormancy (days since last txn)
    dormancy_days = time_since_last_txn / 24.0

    # Device and IP counts
    device_count = float(len(profile.known_devices))
    ip_prefix_count = float(len(profile.known_ip_prefixes))

    return {
        "amount_zscore": float(amount_zscore),
        "new_payee_flag": float(new_payee_flag),
        "payee_first_seen_age": float(payee_first_seen_age),
        "hour_deviation": float(hour_deviation),
        "time_since_last_txn": float(time_since_last_txn),
        "dormancy_days": float(dormancy_days),
        "device_count": device_count,
        "ip_prefix_count": ip_prefix_count
    }


def extract_device_network_features(store: FeatureStore, txn: Dict[str, Any]) -> Dict[str, float]:
    """Extract device/network features from store."""
    device_id = txn.get("device_id", "unknown")
    account_id = txn["account_id"]
    ip_prefix = txn.get("ip_prefix", "unknown")
    step = txn.get("step", 0)

    device_info = store.get_device_info(device_id)

    is_new_device = 1.0 if account_id not in device_info["accounts"] else 0.0
    accounts_per_device = float(len(device_info["accounts"]))
    devices_per_account = 1.0  # Would need account->devices mapping
    ip_prefix_sharing_count = float(len(device_info["ip_prefixes"]))
    device_first_seen_age = 0.0 if device_info["first_seen_step"] is None else float(step - device_info["first_seen_step"])

    return {
        "is_new_device": float(is_new_device),
        "accounts_per_device": accounts_per_device,
        "devices_per_account": devices_per_account,
        "ip_prefix_sharing_count": ip_prefix_sharing_count,
        "device_first_seen_age": device_first_seen_age
    }


def extract_graph_features(store: FeatureStore, txn: Dict[str, Any],
                          txn_history: Optional[pd.DataFrame] = None,
                          graph_engine: Optional[Any] = None) -> Dict[str, float]:
    """Extract graph features from graph_engine or store."""
    if graph_engine is not None:
        return graph_engine.compute_graph_features(txn["account_id"], txn["payee_id"], txn.get("step", 0))

    payee_id = txn["payee_id"]
    account_id = txn["account_id"]
    amount = txn["amount"]
    step = txn.get("step", 0)
    is_fraud = txn.get("label", 0)

    payee_info = store.get_payee_info(payee_id)

    # Payee fan-in (distinct senders in windows)
    payee_fan_in_1h = float(len(payee_info["senders"]))
    payee_fan_in_24h = float(len(payee_info["senders"]))

    # Payee outflow/inflow ratio
    total_inflow = payee_info["total_inflow"]
    total_outflow = payee_info["total_outflow"]
    payee_outflow_inflow_ratio_24h = total_outflow / (total_inflow + 1.0)

    # Pass-through flag
    payee_pass_through_flag = 1.0 if payee_outflow_inflow_ratio_24h > 0.8 and total_inflow > 0 else 0.0

    # Payee first seen age
    payee_first_seen_age = 0.0 if payee_info["first_seen_step"] is None else float(step - payee_info["first_seen_step"])

    # Is merchant
    is_merchant = 1.0 if payee_info["is_merchant"] else 0.0

    # Fraud exposure within 2 hops (simplified)
    fraud_exposure_2hop = float(len(payee_info["fraud_senders"]))

    # Degree and PageRank
    degree = float(len(payee_info["senders"]))
    pagerank = 0.0

    return {
        "payee_fan_in_1h": payee_fan_in_1h,
        "payee_fan_in_24h": payee_fan_in_24h,
        "payee_outflow_inflow_ratio_24h": payee_outflow_inflow_ratio_24h,
        "payee_pass_through_flag": payee_pass_through_flag,
        "payee_first_seen_age": payee_first_seen_age,
        "is_merchant": is_merchant,
        "fraud_exposure_2hop": fraud_exposure_2hop,
        "degree": degree,
        "pagerank": pagerank
    }


def compute_all_features(store: FeatureStore, txn: Dict[str, Any],
                        txn_history: Optional[pd.DataFrame] = None,
                        graph_engine: Optional[Any] = None) -> Dict[str, float]:
    """Compute all features for a transaction."""
    features = {}
    features.update(extract_base_features(txn))
    features.update(extract_velocity_features(store, txn))
    features.update(extract_behavioural_features(store, txn))
    features.update(extract_device_network_features(store, txn))
    features.update(extract_graph_features(store, txn, txn_history, graph_engine=graph_engine))
    return features


def update_stores(store: FeatureStore, txn: Dict[str, Any],
                 graph_engine: Optional[Any] = None) -> None:
    """Update all stores with a new transaction."""
    account_id = txn["account_id"]
    payee_id = txn["payee_id"]
    amount = txn["amount"]
    step = txn.get("step", 0)
    txn_id = txn.get("txn_id", str(hash(frozenset(txn.items()))))
    is_fraud = txn.get("label", 0)
    device_id = txn.get("device_id", "unknown")
    ip_prefix = txn.get("ip_prefix", "unknown")
    hour_of_day = txn.get("hour_of_day", 0)

    store.update_velocity(account_id, payee_id, amount, step, txn_id)
    store.update_behavioural(account_id, amount, step, payee_id, device_id, ip_prefix, hour_of_day)
    store.update_device_info(device_id, account_id, ip_prefix, step=step)
    store.update_payee_info(payee_id, account_id, amount, step, is_fraud)

    if graph_engine is not None:
        graph_engine.update_transaction(
            account_id=account_id, payee_id=payee_id, amount=amount,
            step=step, device_id=device_id, ip_prefix=ip_prefix, label=is_fraud
        )