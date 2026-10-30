"""Phase 4: Anomaly models (IsolationForest and PyTorch Autoencoder).

Trained exclusively on legitimate training rows over velocity + behavioural features.
Anomaly scores are converted to percentile ranks calibrated on validation data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

ANOMALY_FEATURE_NAMES = [
    "count_1h", "sum_1h", "distinct_payees_1h", "amount_vs_sum_1h",
    "count_6h", "sum_6h", "distinct_payees_6h", "amount_vs_sum_6h",
    "count_24h", "sum_24h", "distinct_payees_24h", "amount_vs_sum_24h",
    "amount_zscore", "new_payee_flag", "payee_first_seen_age",
    "hour_deviation", "time_since_last_txn", "dormancy_days",
    "device_count", "ip_prefix_count",
]


class PyTorchAutoencoder(nn.Module):
    """Deep autoencoder for reconstruction error-based anomaly scoring."""

    def __init__(self, input_dim: int, hidden_dim: int = 16, latent_dim: int = 8):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, latent_dim),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, input_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        latent = self.encoder(x)
        return self.decoder(latent)


class PercentileCalibrator:
    """Calibrates continuous anomaly scores to percentile ranks in [0, 1]."""

    def __init__(self):
        self.calibration_scores: Optional[np.ndarray] = None

    def fit(self, scores: np.ndarray) -> PercentileCalibrator:
        self.calibration_scores = np.sort(np.asarray(scores, dtype=np.float32))
        return self

    def transform(self, scores: np.ndarray) -> np.ndarray:
        if self.calibration_scores is None or len(self.calibration_scores) == 0:
            return np.zeros_like(scores, dtype=np.float32)
        idx = np.searchsorted(self.calibration_scores, scores, side="right")
        return (idx / len(self.calibration_scores)).astype(np.float32)


class AnomalyPipeline:
    """Joint anomaly scoring pipeline: IsolationForest + PyTorch Autoencoder."""

    def __init__(self, random_state: int = 42):
        self.random_state = random_state
        self.feature_names = list(ANOMALY_FEATURE_NAMES)
        self.iforest = IsolationForest(
            n_estimators=100,
            max_samples="auto",
            contamination=0.01,
            random_state=random_state,
            n_jobs=-1,
        )
        self.autoencoder: Optional[PyTorchAutoencoder] = None
        self.mean: Optional[np.ndarray] = None
        self.std: Optional[np.ndarray] = None
        self.iforest_calibrator = PercentileCalibrator()
        self.ae_calibrator = PercentileCalibrator()

    def _normalize(self, X: np.ndarray, fit: bool = False) -> np.ndarray:
        if fit:
            self.mean = np.mean(X, axis=0, keepdims=True)
            self.std = np.std(X, axis=0, keepdims=True) + 1e-6
        return (X - self.mean) / self.std

    def fit(self, X_legit: np.ndarray, epochs: int = 15, batch_size: int = 256) -> AnomalyPipeline:
        """Fit IsolationForest and Autoencoder on legitimate training data only."""
        X_legit = np.nan_to_num(np.asarray(X_legit, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)

        # 1. Fit IsolationForest
        logger.info(f"Fitting IsolationForest on {len(X_legit):,} legitimate rows ...")
        self.iforest.fit(X_legit)

        # 2. Fit PyTorch Autoencoder
        logger.info(f"Fitting PyTorch Autoencoder on {len(X_legit):,} legitimate rows ...")
        X_norm = self._normalize(X_legit, fit=True)
        input_dim = X_legit.shape[1]
        torch.manual_seed(self.random_state)
        self.autoencoder = PyTorchAutoencoder(input_dim=input_dim)

        dataset = torch.utils.data.TensorDataset(torch.from_numpy(X_norm))
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)

        optimizer = torch.optim.Adam(self.autoencoder.parameters(), lr=1e-3, weight_decay=1e-5)
        criterion = nn.MSELoss()

        self.autoencoder.train()
        for epoch in range(epochs):
            for (batch_x,) in loader:
                optimizer.zero_grad()
                recon = self.autoencoder(batch_x)
                loss = criterion(recon, batch_x)
                loss.backward()
                optimizer.step()

        return self

    def calibrate_on_validation(self, X_val: np.ndarray) -> None:
        """Calibrate percentile rank mappings using validation data."""
        raw_if, raw_ae = self._raw_scores(X_val)
        self.iforest_calibrator.fit(raw_if)
        self.ae_calibrator.fit(raw_ae)

    def _raw_scores(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        X = np.nan_to_num(np.asarray(X, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        # IsolationForest: score_samples returns negative anomaly score (lower = more anomalous)
        # Invert so higher = more anomalous
        raw_if = -self.iforest.score_samples(X)

        # Autoencoder: reconstruction error MSE per row
        X_norm = self._normalize(X, fit=False)
        with torch.no_grad():
            t_x = torch.from_numpy(X_norm)
            ae_model = getattr(self, "traced_autoencoder", None) or self.autoencoder
            recon = ae_model(t_x)
            mse = torch.mean((recon - t_x) ** 2, dim=1).numpy()
        raw_ae = np.asarray(mse, dtype=np.float32)
        return raw_if, raw_ae

    def score(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Compute calibrated percentile rank scores in [0, 1] (higher = more anomalous)."""
        raw_if, raw_ae = self._raw_scores(X)
        rank_if = self.iforest_calibrator.transform(raw_if)
        rank_ae = self.ae_calibrator.transform(raw_ae)
        return rank_if, rank_ae

    def save(self, dir_path: str) -> None:
        import os
        os.makedirs(dir_path, exist_ok=True)
        joblib.dump(self.iforest, os.path.join(dir_path, "isolation_forest.joblib"))
        joblib.dump(self.iforest_calibrator, os.path.join(dir_path, "iforest_calibrator.joblib"))
        joblib.dump(self.ae_calibrator, os.path.join(dir_path, "ae_calibrator.joblib"))
        joblib.dump({"mean": self.mean, "std": self.std, "feature_names": self.feature_names},
                    os.path.join(dir_path, "ae_meta.joblib"))
        if self.autoencoder is not None:
            torch.save(self.autoencoder.state_dict(), os.path.join(dir_path, "autoencoder.pt"))

    @classmethod
    def load(cls, dir_path: str) -> AnomalyPipeline:
        import os
        pipeline = cls()
        pipeline.iforest = joblib.load(os.path.join(dir_path, "isolation_forest.joblib"))
        pipeline.iforest.n_jobs = 1
        pipeline.iforest_calibrator = joblib.load(os.path.join(dir_path, "iforest_calibrator.joblib"))
        pipeline.ae_calibrator = joblib.load(os.path.join(dir_path, "ae_calibrator.joblib"))
        meta = joblib.load(os.path.join(dir_path, "ae_meta.joblib"))
        pipeline.mean = meta["mean"]
        pipeline.std = meta["std"]
        pipeline.feature_names = meta["feature_names"]

        input_dim = len(pipeline.feature_names)
        pipeline.autoencoder = PyTorchAutoencoder(input_dim=input_dim)
        ae_path = os.path.join(dir_path, "autoencoder.pt")
        if os.path.exists(ae_path):
            pipeline.autoencoder.load_state_dict(torch.load(ae_path, map_location="cpu"))
            pipeline.autoencoder.eval()
            try:
                pipeline.traced_autoencoder = torch.jit.trace(pipeline.autoencoder, torch.zeros(1, input_dim))
            except Exception:
                pipeline.traced_autoencoder = None
        return pipeline
