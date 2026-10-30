"""Core scoring API - no Kafka dependency. Supports v1 models and v2 model bundles."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.isotonic import IsotonicRegression

from fraudengine.config import config
from fraudengine.features.engineering import (
    ALL_FEATURES,
    FEATURE_GROUPS,
    compute_all_features,
    update_stores,
)
from fraudengine.features.store import FeatureStore, create_feature_store
from fraudengine.models.anomaly import ANOMALY_FEATURE_NAMES, AnomalyPipeline
from fraudengine.rules.engine import RuleHit, RulesEngine
from fraudengine.scoring.audit import AuditLog
from fraudengine.scoring.case_bundle import CaseBundleExporter

logger = logging.getLogger(__name__)


@dataclass
class Reason:
    """A single reason for a decision."""
    title: str
    explanation: str
    severity: str  # "low", "medium", "high", "critical"
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """Scoring decision output."""
    txn_id: str
    account_id: str
    score: float
    tier: str  # "ALLOW", "STEP_UP", "REVIEW", "BLOCK"
    reasons: List[Reason]
    summary: str
    recommended_action: str
    latency_ms: float
    feature_snapshot: Dict[str, float]
    model_version: str
    config_hash: str
    rule_hits: List[Dict[str, Any]] = field(default_factory=list)
    model_score: float = 0.0
    detection_source: str = "Normal"  # "Rule", "Model", "Both", "Normal"
    rules_enabled: bool = True
    model_enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reasons"] = [asdict(r) if isinstance(r, Reason) else r for r in self.reasons]
        return d


class Scorer:
    """Core fraud scoring engine - no Kafka dependency."""

    def __init__(
        self,
        model_path: str,
        feature_store: Optional[FeatureStore] = None,
        thresholds: Optional[Dict[str, float]] = None,
        model_version: str = "2.0.0",
        rules_engine: Optional[RulesEngine] = None,
        audit_log: Optional[AuditLog] = None,
        case_exporter: Optional[CaseBundleExporter] = None,
        graph_engine: Optional[Any] = None,
        blocklist_checker: Optional[Any] = None,
    ):
        self.model_path = model_path
        self.feature_store = feature_store or create_feature_store("memory")
        self.graph_engine = graph_engine
        self.blocklist_checker = blocklist_checker
        self.model_version = model_version
        self.rules_engine = rules_engine or RulesEngine()
        self.audit_log = audit_log
        self.case_exporter = case_exporter
        self.anomaly_pipeline: Optional[AnomalyPipeline] = None
        self.calibrator: Optional[IsotonicRegression] = None
        self.shap_explainer = None

        self._load_model()

        # Thresholds
        if thresholds is not None:
            self.thresholds = thresholds
        elif hasattr(self, "_loaded_thresholds") and self._loaded_thresholds:
            self.thresholds = self._loaded_thresholds
        else:
            self.thresholds = {
                "allow_max": 0.1,
                "step_up_max": 0.3,
                "review_max": 0.7,
                "block_min": 0.7,
            }

        self.rules_enabled: bool = True
        self.model_enabled: bool = True
        self._compute_config_hash()

    def _load_model(self) -> None:
        """Load model artifacts supporting both single-file v1 and directory v2 bundles."""
        p = Path(self.model_path)

        if p.is_dir():
            # v2 model bundle directory
            xgb_joblib = p / "xgboost_model.joblib"
            xgb_json = p / "xgboost_model.json"
            if xgb_joblib.exists():
                self.model = joblib.load(str(xgb_joblib))
            elif xgb_json.exists():
                self.model = xgb.XGBClassifier()
                self.model.load_model(str(xgb_json))
            else:
                raise FileNotFoundError(f"No XGBoost model found in {p}")

            # Calibrator
            calib_path = p / "calibrator.joblib"
            if calib_path.exists():
                self.calibrator = joblib.load(str(calib_path))

            # Anomaly pipeline
            anomaly_dir = p / "anomaly_pipeline"
            if anomaly_dir.exists():
                try:
                    self.anomaly_pipeline = AnomalyPipeline.load(str(anomaly_dir))
                except Exception as e:
                    logger.warning(f"Could not load anomaly pipeline: {e}")

            # Feature list
            flist_path = p / "feature_list.json"
            if flist_path.exists():
                with open(flist_path) as f:
                    self.feature_names = json.load(f)
            else:
                self.feature_names = ALL_FEATURES

            # Thresholds
            thresh_path = p / "thresholds.json"
            if thresh_path.exists():
                with open(thresh_path) as f:
                    t = json.load(f)
                    self._loaded_thresholds = {
                        "allow_max": t.get("tier_allow_max", 0.1),
                        "step_up_max": t.get("tier_step_up_max", 0.3),
                        "review_max": t.get("tier_review_max", 0.7),
                        "block_min": t.get("tier_block_min", 0.7),
                    }
        else:
            # v1 legacy single file format
            if str(p).endswith(".pkl"):
                model_data = pd.read_pickle(str(p))
                self.model = model_data["model"]
                self.calibrator = model_data.get("calibrator")
                self.feature_names = model_data.get("feature_names", ALL_FEATURES)
            else:
                self.model = xgb.Booster()
                self.model.load_model(str(p))
                self.calibrator = None
                self.feature_names = ALL_FEATURES

    def _compute_config_hash(self) -> None:
        """Compute hash of model config for audit trail."""
        self.config_hash = hashlib.md5(
            f"{self.model_version}{self.thresholds}".encode()
        ).hexdigest()[:16]

    def _init_shap_explainer(self) -> None:
        """Lazily initialize SHAP TreeExplainer."""
        if self.shap_explainer is None and hasattr(self.model, "get_booster"):
            try:
                import shap
                self.shap_explainer = shap.TreeExplainer(self.model)
            except Exception as e:
                logger.debug(f"SHAP explainer init skipped: {e}")

    def _compute_reasons(
        self, features: Dict[str, float], rule_hits: List[RuleHit], top_k: int = 3
    ) -> List[Reason]:
        """Compute plain-English reasons from SHAP contributions + rule hits."""
        reasons: List[Reason] = []

        # 1. Add rule hits first (they provide high-confidence evidence)
        for hit in rule_hits:
            reasons.append(
                Reason(
                    title=hit.title,
                    explanation=hit.explanation,
                    severity=hit.severity,
                    evidence=hit.evidence,
                )
            )

        # 2. Add SHAP feature contributions if more reasons needed
        feature_values = {k: features.get(k, 0.0) for k in self.feature_names}
        self._init_shap_explainer()
        shap_vals_dict = {}
        if self.shap_explainer is not None:
            try:
                X_mat = np.array([[features.get(f, 0.0) for f in self.feature_names]], dtype=np.float32)
                sv = self.shap_explainer(X_mat)
                vals = sv.values[0] if hasattr(sv, "values") else (sv[0] if isinstance(sv, list) else sv[0])
                for idx, fname in enumerate(self.feature_names):
                    if idx < len(vals):
                        shap_vals_dict[fname] = float(vals[idx])
            except Exception as e:
                logger.debug(f"SHAP explanation failed: {e}")

        # Template dictionary for human-readable reasons
        templates = {
            "payee_fan_in_24h": ("High Payee Fan-In", "Payee received funds from {val:.0f} distinct senders in the last 24 hours"),
            "payee_outflow_inflow_ratio_24h": ("Pass-Through Pattern", "Payee forwarded {val:.0%} of incoming funds within 24 hours"),
            "orig_drained": ("Account Balance Drained", "Entire balance was depleted in a single transaction"),
            "is_new_device": ("New Device Used", "Transaction originated from a device never before linked to this account"),
            "amount_zscore": ("Unusual Amount", "Transaction amount is {val:.1f} standard deviations above this account's historical mean"),
            "fraud_exposure_2hop": ("Fraud Exposure", "Account is within 2 hops of {val:.0f} confirmed fraudulent entities"),
            "dormancy_days": ("Dormant Reactivation", "Account was inactive for {val:.0f} days prior to this transaction"),
            "isolation_forest_score": ("Behavioral Anomaly", "Unusual velocity and behavioural feature signature (percentile: {val:.2f})"),
            "autoencoder_reconstruction_error": ("Reconstruction Anomaly", "High reconstruction error indicating an outlier transaction pattern ({val:.2f})"),
            "count_1h": ("Velocity Spike (1h)", "Account executed {val:.0f} transactions within the last hour"),
            "sum_24h": ("Daily Outflow Spike", "Total outflow of ₹{val:.0f} in 24 hours exceeds normal profile"),
        }

        # Sort feature contributions using real SHAP values if present, or heuristic weights
        contributions = []
        for feat, val in feature_values.items():
            if feat in templates:
                shap_val = shap_vals_dict.get(feat)
                if shap_val is not None:
                    if shap_val > 0.0:  # Positively contributed to fraud score
                        contributions.append((shap_val, feat, val, round(shap_val, 4)))
                else:
                    # Fallback importance weighting
                    weight = 1.0
                    if feat in ("orig_drained", "is_new_device") and val > 0.5:
                        weight = 2.0
                    elif feat in ("payee_fan_in_24h", "fraud_exposure_2hop") and val > 2.0:
                        weight = 2.5
                    elif feat == "amount_zscore" and abs(val) > 2.0:
                        weight = 2.0
                    elif feat in ("isolation_forest_score", "autoencoder_reconstruction_error") and val > 0.9:
                        weight = 2.2
                    if weight > 1.0:
                        contributions.append((weight * abs(val), feat, val, None))

        contributions.sort(reverse=True)
        for _, feat, val, s_val in contributions:
            if len(reasons) >= top_k:
                break
            title, template = templates[feat]
            # Avoid duplicate titles
            if not any(r.title == title for r in reasons):
                ev = {feat: val}
                if s_val is not None:
                    ev["shap_importance"] = s_val
                reasons.append(
                    Reason(
                        title=title,
                        explanation=template.format(val=val),
                        severity="high" if (s_val is not None and s_val > 0.5) or val > 2.0 else "medium",
                        evidence=ev,
                    )
                )

        return reasons[:top_k]

    def _get_tier(self, score: float, rule_hits: List[RuleHit]) -> str:
        """Map score and rule hits to decision tier (fusion)."""
        # Critical rule hit forces BLOCK
        if any(h.severity == "critical" for h in rule_hits):
            return "BLOCK"

        # High rule hits
        high_rule_count = sum(1 for h in rule_hits if h.severity == "high")
        if high_rule_count >= 2 or score >= self.thresholds.get("block_min", 0.7):
            return "BLOCK"
        elif score >= self.thresholds.get("review_max", 0.7) or (high_rule_count >= 1 and score >= self.thresholds.get("step_up_max", 0.3)):
            return "REVIEW"
        elif score >= self.thresholds.get("step_up_max", 0.3) or high_rule_count >= 1:
            return "STEP_UP"
        else:
            return "ALLOW"

    def _get_summary(self, tier: str, reasons: List[Reason]) -> str:
        """Generate plain-English summary."""
        if tier == "ALLOW":
            return "Transaction appears normal; activity is consistent with account history."
        elif tier == "STEP_UP":
            top_reason = reasons[0].explanation if reasons else "unusual device or location"
            return f"Step-up authentication required: {top_reason}."
        elif tier == "REVIEW":
            top_reason = reasons[0].explanation if reasons else "unusual velocity or network pattern"
            return f"Flagged for analyst review: {top_reason}."
        else:  # BLOCK
            top_reason = reasons[0].explanation if reasons else "high confidence fraud signature"
            return f"Critical risk detected: {top_reason}."

    def _get_action(self, tier: str) -> str:
        """Get recommended action for tier."""
        actions = {
            "ALLOW": "Process normally",
            "STEP_UP": "Request additional authentication (e.g., OTP or biometric verification)",
            "REVIEW": "Hold funds for manual analyst review within 1 hour",
            "BLOCK": "Decline transaction immediately and freeze account pending investigation",
        }
        return actions.get(tier, "Process normally")

    def score(
        self,
        txn: Dict[str, Any],
        rules_enabled: Optional[bool] = None,
        model_enabled: Optional[bool] = None,
    ) -> Decision:
        """Score a single transaction with point-in-time features, rules, model, and audit."""
        start_time = time.perf_counter()
        use_rules = self.rules_enabled if rules_enabled is None else rules_enabled
        use_model = self.model_enabled if model_enabled is None else model_enabled

        # 0. Redis blocklist check BEFORE scoring in the hot path
        if self.blocklist_checker is not None:
            blocked_info = self.blocklist_checker(txn) if callable(self.blocklist_checker) else self.blocklist_checker.check(txn)
            if blocked_info:
                tier, reason_title, reason_expl = blocked_info
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                decision = Decision(
                    txn_id=txn.get("txn_id", "unknown"),
                    account_id=txn.get("account_id", "unknown"),
                    score=1.0 if tier == "BLOCK" else 0.75,
                    tier=tier,
                    rule_hits=[
                        {
                            "rule_id": "RULE_BLOCKLIST_PRECHECK",
                            "name": "Blocklist Pre-Score Filter",
                            "severity": "critical" if tier == "BLOCK" else "high",
                        }
                    ],
                    reasons=[
                        Reason(
                            title=reason_title,
                            explanation=reason_expl,
                            severity="critical" if tier == "BLOCK" else "high",
                            evidence={"account_id": txn.get("account_id"), "pre_check": True},
                        )
                    ],
                    summary=f"Instant blocklist pre-filter: {reason_expl}",
                    recommended_action="Decline transaction immediately and freeze account" if tier == "BLOCK" else "Hold funds for investigation",
                    feature_snapshot={"blocklist_intercept": 1.0},
                    latency_ms=round(latency_ms, 3),
                    model_version=self.model_version,
                    config_hash=self.config_hash,
                    model_score=1.0 if tier == "BLOCK" else 0.75,
                    detection_source="Rule",
                    rules_enabled=use_rules,
                    model_enabled=use_model,
                )
                if self.audit_log:
                    try:
                        self.audit_log.append(decision.to_dict())
                    except Exception as e:
                        logger.warning(f"Audit log write failed: {e}")
                return decision

        # 1. Compute base + velocity + behavioural + device + graph features
        features = compute_all_features(
            self.feature_store, txn, graph_engine=self.graph_engine
        )

        # 2. Add anomaly scores if pipeline loaded
        if self.anomaly_pipeline is not None:
            anomaly_vec = np.array(
                [[features.get(f, 0.0) for f in ANOMALY_FEATURE_NAMES]],
                dtype=np.float32,
            )
            r_if, r_ae = self.anomaly_pipeline.score(anomaly_vec)
            features["isolation_forest_score"] = float(r_if[0])
            features["autoencoder_reconstruction_error"] = float(r_ae[0])

        # 3. Evaluate rules
        rule_hits = self.rules_engine.evaluate(features, txn) if use_rules else []

        # 4. Model score
        if use_model:
            X = np.array([[features.get(f, 0.0) for f in self.feature_names]], dtype=np.float32)
            if hasattr(self.model, "predict_proba"):
                raw_prob = float(self.model.predict_proba(X)[0, 1])
            else:
                dmatrix = xgb.DMatrix(X)
                raw_prob = float(self.model.predict(dmatrix)[0])

            # 5. Calibration
            if self.calibrator is not None:
                cal_prob = float(self.calibrator.predict([raw_prob])[0])
                # Isotonic step-function calibrator collapses raw probabilities < 0.058 to 0.0.
                # Preserve raw model probability floor when raw_prob > 0 to avoid flattening small transfers.
                prob = max(cal_prob, raw_prob) if cal_prob == 0.0 and raw_prob > 0.0 else cal_prob
            else:
                prob = raw_prob
        else:
            raw_prob = 0.0
            prob = 0.0

        model_score_val = round(prob, 4)

        # 6. Tier fusion
        tier = self._get_tier(prob, rule_hits)

        # Detection source determination
        has_rules = len(rule_hits) > 0
        has_model = prob >= self.thresholds.get("step_up_max", 0.3)
        if has_rules and has_model:
            detection_source = "Both"
        elif has_rules:
            detection_source = "Rule"
        elif has_model:
            detection_source = "Model"
        else:
            detection_source = "Normal"

        # 7. Reasons (only for non-ALLOW to protect latency)
        reasons: List[Reason] = []
        if tier != "ALLOW":
            reasons = self._compute_reasons(features, rule_hits)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        decision = Decision(
            txn_id=str(txn.get("txn_id", "unknown")),
            account_id=str(txn.get("account_id", "unknown")),
            score=model_score_val,
            tier=tier,
            reasons=reasons,
            summary=self._get_summary(tier, reasons),
            recommended_action=self._get_action(tier),
            latency_ms=round(latency_ms, 2),
            feature_snapshot=features,
            model_version=self.model_version,
            config_hash=self.config_hash,
            rule_hits=[asdict(h) for h in rule_hits],
            model_score=model_score_val,
            detection_source=detection_source,
            rules_enabled=use_rules,
            model_enabled=use_model,
        )

        # 8. Append to audit log
        if self.audit_log is not None:
            try:
                self.audit_log.append(decision.to_dict())
            except Exception as e:
                logger.warning(f"Audit log write failed: {e}")

        # 9. Case bundle export for REVIEW/BLOCK
        if tier in ("REVIEW", "BLOCK") and self.case_exporter is not None:
            try:
                self.case_exporter.export(
                    decision_dict=decision.to_dict(),
                    features=features,
                    graph_engine=self.graph_engine,
                )
            except Exception as e:
                logger.warning(f"Case bundle export failed: {e}")

        # 10. Update state stores
        update_stores(self.feature_store, txn, graph_engine=self.graph_engine)

        return decision

    def score_batch(self, txns: List[Dict[str, Any]]) -> List[Decision]:
        """Score a batch of transactions."""
        return [self.score(txn) for txn in txns]

    def close(self) -> None:
        """Close connections."""
        self.feature_store.close()
        if self.graph_engine is not None and hasattr(self.graph_engine, "close"):
            self.graph_engine.close()