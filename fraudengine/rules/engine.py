"""Phase 6: YAML-configurable rules engine.

Records rule hits and provides velocity caps, new-device + large-amount detection,
blocklist, and scenario-specific pattern rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RuleHit:
    """Record of a rule that fired."""
    rule_id: str
    rule_name: str
    title: str
    explanation: str
    severity: str  # "low", "medium", "high", "critical"
    evidence: Dict[str, Any] = field(default_factory=dict)


DEFAULT_RULES_CONFIG = {
    "rules": {
        "velocity_cap_1h": {
            "enabled": True,
            "threshold_count": 10,
            "threshold_amount": 50000.0,
            "severity": "high",
            "title": "High-frequency transactions",
            "explanation": "More than {count} transactions in the last hour totalling ₹{amount:.0f}",
        },
        "velocity_cap_24h": {
            "enabled": True,
            "threshold_count": 50,
            "threshold_amount": 200000.0,
            "severity": "medium",
            "title": "Elevated daily activity",
            "explanation": "More than {count} transactions in the last 24 hours",
        },
        "new_device_large_amount": {
            "enabled": True,
            "amount_threshold": 10000.0,
            "severity": "high",
            "title": "Large amount from new device",
            "explanation": "Transaction of ₹{amount:.0f} from a device not previously seen for this account",
        },
        "dormant_reactivation": {
            "enabled": True,
            "dormancy_threshold_days": 14.0,
            "amount_threshold": 5000.0,
            "severity": "high",
            "title": "Dormant account reactivated",
            "explanation": "Account dormant for {days:.0f} days suddenly sending ₹{amount:.0f}",
        },
        "high_fan_in": {
            "enabled": True,
            "threshold_senders_24h": 10,
            "severity": "high",
            "title": "Unusual number of incoming senders",
            "explanation": "Payee received funds from {count} distinct senders in 24 hours",
        },
        "pass_through": {
            "enabled": True,
            "outflow_ratio_threshold": 0.8,
            "min_inflow": 1000.0,
            "severity": "high",
            "title": "Pass-through account detected",
            "explanation": "Account forwarded {ratio:.0%} of incoming funds within 24 hours",
        },
        "account_drained": {
            "enabled": True,
            "severity": "medium",
            "title": "Account balance drained to zero",
            "explanation": "Full account balance of ₹{amount:.0f} was transferred out",
        },
        "amount_zscore": {
            "enabled": True,
            "threshold": 3.0,
            "severity": "medium",
            "title": "Unusual transaction amount",
            "explanation": "Transaction amount is {zscore:.1f} standard deviations from this account's average",
        },
        "blocklist": {
            "enabled": True,
            "accounts": [],
            "devices": [],
            "severity": "critical",
            "title": "Blocklisted entity",
            "explanation": "Transaction involves a blocklisted {entity_type}",
        },
    }
}


class RulesEngine:
    """YAML-configurable rules engine for fraud detection."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or DEFAULT_RULES_CONFIG
        self.rules = self.config.get("rules", {})

    @classmethod
    def from_yaml(cls, yaml_path: str) -> RulesEngine:
        with open(yaml_path) as f:
            config = yaml.safe_load(f)
        return cls(config=config)

    def evaluate(self, features: Dict[str, float], txn: Optional[Dict[str, Any]] = None) -> List[RuleHit]:
        """Evaluate all rules against a transaction's features."""
        hits: List[RuleHit] = []
        txn = txn or {}

        # Velocity cap 1h
        rule = self.rules.get("velocity_cap_1h", {})
        if rule.get("enabled"):
            count_1h = features.get("count_1h", 0)
            sum_1h = features.get("sum_1h", 0)
            if count_1h >= rule["threshold_count"] or sum_1h >= rule["threshold_amount"]:
                hits.append(RuleHit(
                    rule_id="velocity_cap_1h",
                    rule_name="Velocity Cap (1h)",
                    title=rule["title"],
                    explanation=rule["explanation"].format(count=int(count_1h), amount=sum_1h),
                    severity=rule["severity"],
                    evidence={"count_1h": count_1h, "sum_1h": sum_1h},
                ))

        # Velocity cap 24h
        rule = self.rules.get("velocity_cap_24h", {})
        if rule.get("enabled"):
            count_24h = features.get("count_24h", 0)
            sum_24h = features.get("sum_24h", 0)
            if count_24h >= rule["threshold_count"] or sum_24h >= rule["threshold_amount"]:
                hits.append(RuleHit(
                    rule_id="velocity_cap_24h",
                    rule_name="Velocity Cap (24h)",
                    title=rule["title"],
                    explanation=rule["explanation"].format(count=int(count_24h)),
                    severity=rule["severity"],
                    evidence={"count_24h": count_24h, "sum_24h": sum_24h},
                ))

        # New device + large amount
        rule = self.rules.get("new_device_large_amount", {})
        if rule.get("enabled"):
            is_new = features.get("is_new_device", 0)
            amount = features.get("amount", 0)
            if is_new > 0.5 and amount >= rule["amount_threshold"]:
                hits.append(RuleHit(
                    rule_id="new_device_large_amount",
                    rule_name="New Device + Large Amount",
                    title=rule["title"],
                    explanation=rule["explanation"].format(amount=amount),
                    severity=rule["severity"],
                    evidence={"is_new_device": is_new, "amount": amount},
                ))

        # Dormant reactivation
        rule = self.rules.get("dormant_reactivation", {})
        if rule.get("enabled"):
            dormancy = features.get("dormancy_days", 0)
            amount = features.get("amount", 0)
            if dormancy >= rule["dormancy_threshold_days"] and amount >= rule["amount_threshold"]:
                hits.append(RuleHit(
                    rule_id="dormant_reactivation",
                    rule_name="Dormant Reactivation",
                    title=rule["title"],
                    explanation=rule["explanation"].format(days=dormancy, amount=amount),
                    severity=rule["severity"],
                    evidence={"dormancy_days": dormancy, "amount": amount},
                ))

        # High fan-in
        rule = self.rules.get("high_fan_in", {})
        if rule.get("enabled"):
            fan_in = features.get("payee_fan_in_24h", 0)
            is_merchant = features.get("is_merchant", 0)
            if fan_in >= rule["threshold_senders_24h"] and is_merchant < 0.5:
                hits.append(RuleHit(
                    rule_id="high_fan_in",
                    rule_name="High Fan-In",
                    title=rule["title"],
                    explanation=rule["explanation"].format(count=int(fan_in)),
                    severity=rule["severity"],
                    evidence={"payee_fan_in_24h": fan_in},
                ))

        # Pass-through
        rule = self.rules.get("pass_through", {})
        if rule.get("enabled"):
            ratio = features.get("payee_outflow_inflow_ratio_24h", 0)
            pass_flag = features.get("payee_pass_through_flag", 0)
            if pass_flag > 0.5 and ratio >= rule["outflow_ratio_threshold"]:
                hits.append(RuleHit(
                    rule_id="pass_through",
                    rule_name="Pass-Through Account",
                    title=rule["title"],
                    explanation=rule["explanation"].format(ratio=ratio),
                    severity=rule["severity"],
                    evidence={"outflow_inflow_ratio": ratio},
                ))

        # Account drained
        rule = self.rules.get("account_drained", {})
        if rule.get("enabled"):
            drained = features.get("orig_drained", 0)
            amount = features.get("amount", 0)
            if drained > 0.5:
                hits.append(RuleHit(
                    rule_id="account_drained",
                    rule_name="Account Drained",
                    title=rule["title"],
                    explanation=rule["explanation"].format(amount=amount),
                    severity=rule["severity"],
                    evidence={"orig_drained": drained, "amount": amount},
                ))

        # Amount z-score
        rule = self.rules.get("amount_zscore", {})
        if rule.get("enabled"):
            zscore = features.get("amount_zscore", 0)
            if abs(zscore) >= rule["threshold"]:
                hits.append(RuleHit(
                    rule_id="amount_zscore",
                    rule_name="Unusual Amount",
                    title=rule["title"],
                    explanation=rule["explanation"].format(zscore=zscore),
                    severity=rule["severity"],
                    evidence={"amount_zscore": zscore},
                ))

        # Blocklist
        rule = self.rules.get("blocklist", {})
        if rule.get("enabled"):
            account_id = txn.get("account_id", "")
            device_id = txn.get("device_id", "")
            if account_id in rule.get("accounts", []):
                hits.append(RuleHit(
                    rule_id="blocklist_account",
                    rule_name="Blocklisted Account",
                    title=rule["title"],
                    explanation=rule["explanation"].format(entity_type="account"),
                    severity=rule["severity"],
                    evidence={"account_id": account_id},
                ))
            if device_id in rule.get("devices", []):
                hits.append(RuleHit(
                    rule_id="blocklist_device",
                    rule_name="Blocklisted Device",
                    title=rule["title"],
                    explanation=rule["explanation"].format(entity_type="device"),
                    severity=rule["severity"],
                    evidence={"device_id": device_id},
                ))

        return hits
