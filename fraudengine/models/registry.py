"""Model registry with promotion rules and rollback support.

Manages model lifecycle across stages:
- champion: Active production model
- challenger: Newly evaluated model candidate
- archived: Historical model versions available for rollback
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models_v2"
REGISTRY_FILE = MODELS_DIR / "registry.json"


@dataclass
class ModelVersion:
    version: str
    stage: str  # "champion", "challenger", "archived"
    model_path: str
    metrics: Dict[str, Any]
    created_at: float
    promoted_at: Optional[float] = None
    config_hash: Optional[str] = None
    notes: Optional[str] = None


class ModelRegistry:
    """Manages models, champion/challenger promotions, and rollbacks."""

    def __init__(self, registry_file: Path = REGISTRY_FILE):
        self.registry_file = Path(registry_file)
        self.models_dir = self.registry_file.parent
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.versions: Dict[str, ModelVersion] = {}
        self._load()

    def _load(self) -> None:
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r") as f:
                    data = json.load(f)
                    for ver, item in data.get("versions", {}).items():
                        self.versions[ver] = ModelVersion(**item)
            except Exception as e:
                logger.error(f"Failed to load registry: {e}")
        else:
            # Seed default if v2.0.0 exists
            v2_path = self.models_dir / "v2.0.0"
            if v2_path.exists():
                self.versions["v2.0.0"] = ModelVersion(
                    version="v2.0.0",
                    stage="champion",
                    model_path=str(v2_path),
                    metrics={"pr_auc": 0.892, "recall_at_1pct": 0.954},
                    created_at=time.time(),
                    promoted_at=time.time(),
                    notes="Baseline v2 champion model",
                )
                self._save()

    def _save(self) -> None:
        data = {
            "updated_at": time.time(),
            "active_champion": self.get_champion_version(),
            "versions": {k: asdict(v) for k, v in self.versions.items()},
        }
        with open(self.registry_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_champion(self) -> Optional[ModelVersion]:
        for v in self.versions.values():
            if v.stage == "champion":
                return v
        return None

    def get_champion_version(self) -> Optional[str]:
        champ = self.get_champion()
        return champ.version if champ else None

    def list_models(self) -> List[Dict[str, Any]]:
        return [asdict(v) for v in sorted(self.versions.values(), key=lambda x: x.created_at, reverse=True)]

    def register_model(
        self,
        version: str,
        model_path: str,
        metrics: Dict[str, Any],
        stage: str = "challenger",
        config_hash: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ModelVersion:
        mv = ModelVersion(
            version=version,
            stage=stage,
            model_path=str(model_path),
            metrics=metrics,
            created_at=time.time(),
            promoted_at=time.time() if stage == "champion" else None,
            config_hash=config_hash,
            notes=notes,
        )
        if stage == "champion":
            for v in self.versions.values():
                if v.stage == "champion":
                    v.stage = "archived"
        self.versions[version] = mv
        self._save()
        logger.info(f"Registered model {version} as {stage}")
        return mv

    def promote_challenger(
        self,
        challenger_version: str,
        min_pr_auc_delta: float = 0.005,
    ) -> Dict[str, Any]:
        """Champion/Challenger promotion rule.
        
        Promotes challenger to champion if:
        challenger.pr_auc >= champion.pr_auc + min_pr_auc_delta
        """
        if challenger_version not in self.versions:
            return {"promoted": False, "reason": f"Version {challenger_version} not found"}

        challenger = self.versions[challenger_version]
        champion = self.get_champion()

        if champion is None:
            challenger.stage = "champion"
            challenger.promoted_at = time.time()
            self._save()
            return {"promoted": True, "reason": "No existing champion, promoted automatically"}

        c_pr = challenger.metrics.get("pr_auc", 0.0)
        curr_pr = champion.metrics.get("pr_auc", 0.0)
        delta = c_pr - curr_pr

        if delta >= min_pr_auc_delta:
            champion.stage = "archived"
            challenger.stage = "champion"
            challenger.promoted_at = time.time()
            self._save()
            msg = f"Promoted {challenger_version} (PR-AUC {c_pr:.4f} vs champion {curr_pr:.4f}, delta +{delta:.4f} >= {min_pr_auc_delta})"
            logger.info(msg)
            return {"promoted": True, "delta": round(delta, 4), "reason": msg}
        else:
            msg = f"Challenger {challenger_version} rejected (PR-AUC {c_pr:.4f} vs champion {curr_pr:.4f}, delta +{delta:.4f} < {min_pr_auc_delta})"
            logger.info(msg)
            return {"promoted": False, "delta": round(delta, 4), "reason": msg}

    def rollback(self, target_version: Optional[str] = None) -> Dict[str, Any]:
        """Rollback champion to a previous archived version."""
        current_champion = self.get_champion()
        if not current_champion:
            return {"success": False, "reason": "No active champion to rollback from"}

        if target_version:
            if target_version not in self.versions:
                return {"success": False, "reason": f"Target version {target_version} not found"}
            candidate = self.versions[target_version]
        else:
            # Find the most recently promoted archived model
            archived = [v for v in self.versions.values() if v.stage == "archived" and v.version != current_champion.version]
            if not archived:
                return {"success": False, "reason": "No archived model version available for rollback"}
            candidate = max(archived, key=lambda x: x.promoted_at or x.created_at)

        current_champion.stage = "archived"
        candidate.stage = "champion"
        candidate.promoted_at = time.time()
        self._save()
        msg = f"Successfully rolled back from {current_champion.version} to {candidate.version}"
        logger.info(msg)
        return {"success": True, "previous_version": current_champion.version, "active_version": candidate.version, "reason": msg}
