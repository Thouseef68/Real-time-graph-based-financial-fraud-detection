"""Feature and score drift monitor using Population Stability Index (PSI).

PSI Guidelines:
- PSI < 0.1: No significant drift (Baseline and production distributions match)
- 0.1 <= PSI < 0.2: Moderate drift (Warning; monitor trends)
- PSI >= 0.2: Significant drift (Critical; triggers model retraining alert)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RESULTS_DIR = ROOT / "results_v2"


def calculate_psi(
    baseline: np.ndarray,
    target: np.ndarray,
    num_buckets: int = 10,
    epsilon: float = 1e-4,
) -> float:
    """Compute Population Stability Index (PSI) between baseline and target distributions."""
    baseline = np.asarray(baseline, dtype=float)
    target = np.asarray(target, dtype=float)

    # Filter out NaNs/infs
    baseline = baseline[np.isfinite(baseline)]
    target = target[np.isfinite(target)]

    if len(baseline) == 0 or len(target) == 0:
        return 0.0

    # Determine quantile bucket edges from baseline
    quantiles = np.linspace(0, 100, num_buckets + 1)
    bucket_edges = np.percentile(baseline, quantiles)
    bucket_edges[0] = -np.inf
    bucket_edges[-1] = np.inf

    # In case of constant or low-cardinality features, ensure strictly monotonic edges
    unique_edges = np.unique(bucket_edges)
    if len(unique_edges) < 2:
        return 0.0

    # Frequency counts
    base_counts, _ = np.histogram(baseline, bins=unique_edges)
    target_counts, _ = np.histogram(target, bins=unique_edges)

    # Fractions with Laplace smoothing
    base_fractions = (base_counts + epsilon) / (len(baseline) + epsilon * len(base_counts))
    target_fractions = (target_counts + epsilon) / (len(target) + epsilon * len(target_counts))

    # PSI calculation: sum((target - base) * ln(target / base))
    psi_value = np.sum((target_fractions - base_fractions) * np.log(target_fractions / base_fractions))
    return float(max(0.0, psi_value))


def interpret_psi(psi_val: float) -> Tuple[str, str]:
    """Returns (status, alert_level)."""
    if psi_val < 0.1:
        return "stable", "normal"
    elif psi_val < 0.2:
        return "moderate_drift", "warning"
    else:
        return "significant_drift", "critical"


class DriftMonitor:
    """Evaluates PSI across features and scores, producing structured monitoring reports."""

    def __init__(self, baseline_df: pd.DataFrame, feature_names: Optional[List[str]] = None):
        self.baseline_df = baseline_df
        if feature_names is None:
            from fraudengine.features.engineering import ALL_FEATURES
            self.feature_names = [f for f in ALL_FEATURES if f in baseline_df.columns]
        else:
            self.feature_names = [f for f in feature_names if f in baseline_df.columns]

    def evaluate_drift(
        self,
        current_df: pd.DataFrame,
        baseline_scores: Optional[np.ndarray] = None,
        current_scores: Optional[np.ndarray] = None,
        is_simulation: bool = False,
    ) -> Dict[str, Any]:
        """Compute drift across all monitored features and scores."""
        feature_results = {}
        high_drift_features = []

        for feat in self.feature_names:
            if feat not in current_df.columns:
                continue
            b_vals = self.baseline_df[feat].to_numpy()
            c_vals = current_df[feat].to_numpy()

            psi = calculate_psi(b_vals, c_vals)
            status, severity = interpret_psi(psi)

            feature_results[feat] = {
                "psi": round(psi, 4),
                "status": status,
                "severity": severity,
                "drift_flag": psi >= 0.2,
            }
            if psi >= 0.2:
                high_drift_features.append(feat)

        # Score drift
        score_drift = None
        if baseline_scores is not None and current_scores is not None:
            s_psi = calculate_psi(baseline_scores, current_scores)
            s_status, s_severity = interpret_psi(s_psi)
            score_drift = {
                "psi": round(s_psi, 4),
                "status": s_status,
                "severity": s_severity,
                "drift_flag": s_psi >= 0.2,
            }

        mean_feature_psi = float(np.mean([f["psi"] for f in feature_results.values()])) if feature_results else 0.0

        report = {
            "is_simulation": is_simulation,
            "simulation_label": "demo simulation" if is_simulation else "production traffic",
            "sample_size": len(current_df),
            "baseline_size": len(self.baseline_df),
            "mean_feature_psi": round(mean_feature_psi, 4),
            "score_drift": score_drift,
            "high_drift_count": len(high_drift_features),
            "high_drift_features": high_drift_features,
            "overall_status": "critical" if (high_drift_features or (score_drift and score_drift["drift_flag"])) else ("warning" if mean_feature_psi >= 0.1 else "healthy"),
            "features": feature_results,
        }

        # Save report
        out_path = RESULTS_DIR / "drift_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)

        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cache_dir = ROOT / "data" / "cache"
    val_path = cache_dir / "val_features.parquet"
    test_path = cache_dir / "test_features.parquet"
    if val_path.exists() and test_path.exists():
        val_df = pd.read_parquet(val_path)
        test_df = pd.read_parquet(test_path)
        monitor = DriftMonitor(baseline_df=val_df)
        rep = monitor.evaluate_drift(test_df, is_simulation=False)
        print(f"Drift check complete: Mean PSI = {rep['mean_feature_psi']}, Status = {rep['overall_status']}")
        print(f"Report saved to {RESULTS_DIR / 'drift_report.json'}")

