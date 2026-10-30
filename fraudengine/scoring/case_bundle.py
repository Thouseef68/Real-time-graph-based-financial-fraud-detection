"""Phase 8A: Case bundle exporter for analyst investigation and Cytoscape.js rendering.

For each REVIEW/BLOCK decision, packages:
- Decision summary, score, tier, and recommended action
- Top-k human-readable reason cards (title, explanation, severity, evidence)
- Point-in-time feature snapshot
- 2-hop ego subgraph centered on the account (nodes, edges, node attributes, edge amounts)
- Account transaction history timeline
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CaseBundle:
    """Complete investigation bundle for analyst review and frontend visualization."""
    case_id: str
    txn_id: str
    account_id: str
    payee_id: str
    amount: float
    step: int
    score: float
    tier: str
    summary: str
    recommended_action: str
    reasons: List[Dict[str, Any]]
    rule_hits: List[Dict[str, Any]]
    features: Dict[str, float]
    subgraph: Dict[str, Any]
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, filepath: str) -> None:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    @classmethod
    def load(cls, filepath: str) -> CaseBundle:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


class CaseBundleExporter:
    """Exports case bundles for non-ALLOW decisions."""

    def __init__(self, output_dir: str = "results_v2/cases"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        decision_dict: Dict[str, Any],
        features: Dict[str, float],
        graph_engine: Optional[Any] = None,
        timeline: Optional[List[Dict[str, Any]]] = None,
    ) -> CaseBundle:
        """Create and export a case bundle for a given decision."""
        txn_id = decision_dict.get("txn_id", "unknown")
        account_id = decision_dict.get("account_id", "unknown")
        tier = decision_dict.get("tier", "REVIEW")
        score = float(decision_dict.get("score", 0.0))

        # Action recommendation rationale
        if tier == "BLOCK":
            recommended_action = "Block transaction immediately and lock account pending identity verification."
        elif tier == "REVIEW":
            recommended_action = "Hold funds for manual analyst investigation of payee history and device linkage."
        elif tier == "STEP_UP":
            recommended_action = "Trigger step-up 2FA / biometric authentication to the primary registered device."
        else:
            recommended_action = "Allow transaction to proceed."

        # Extract 2-hop ego subgraph
        if graph_engine is not None and hasattr(graph_engine, "get_2hop_subgraph"):
            subgraph = graph_engine.get_2hop_subgraph(account_id, max_nodes=100)
        else:
            subgraph = {
                "center_account": account_id,
                "node_count": 1,
                "edge_count": 0,
                "nodes": [{"data": {"id": account_id, "label": account_id, "type": "account"}}],
                "edges": [],
            }

        bundle = CaseBundle(
            case_id=f"case_{txn_id}",
            txn_id=txn_id,
            account_id=account_id,
            payee_id=decision_dict.get("payee_id", features.get("payee_id", "unknown")),
            amount=float(features.get("amount", decision_dict.get("amount", 0.0))),
            step=int(features.get("step", decision_dict.get("step", 0))),
            score=score,
            tier=tier,
            summary=decision_dict.get("summary", ""),
            recommended_action=recommended_action,
            reasons=decision_dict.get("reasons", []),
            rule_hits=decision_dict.get("rule_hits", []),
            features=features,
            subgraph=subgraph,
            timeline=timeline or [],
            created_at=decision_dict.get("timestamp", ""),
        )

        out_path = self.output_dir / f"{txn_id}.json"
        bundle.save(str(out_path))
        return bundle
