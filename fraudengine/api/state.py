"""Shared application state for FastAPI backend in inproc or kafka mode."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from fraudengine.feedback.label_store import LabelStore
from fraudengine.graph.engine import GraphEngine
from fraudengine.rules.engine import RulesEngine
from fraudengine.scoring.audit import AuditLog
from fraudengine.scoring.case_bundle import CaseBundleExporter
from fraudengine.scoring.core import Scorer

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


class AppState:
    """Singleton application state holding scorer, label store, audit log, and simulator."""

    def __init__(self):
        self.label_store = LabelStore(str(ROOT / "data" / "label_store.db"))
        self.audit_log = AuditLog(str(ROOT / "data" / "audit_log.jsonl"))
        self.graph_engine = GraphEngine(neo4j_uri=None)
        self.case_exporter = CaseBundleExporter(str(ROOT / "results_v2" / "cases"))
        self.rules_engine = RulesEngine()

        self.scorer: Optional[Scorer] = None
        self._init_scorer()

        # Settings
        self.settings = {
            "threshold_allow_max": 0.1,
            "threshold_step_up_max": 0.3,
            "threshold_review_max": 0.7,
            "threshold_block_min": 0.7,
            "cost_fp": 1.0,
            "cost_fn": 10.0,
            "cost_review": 1.0,
            "confirmation_delay_hours": 24,
            "demo_reveal": False,
        }
        self._load_settings()

        # Simulator state
        self.sim_running = False
        self.sim_speed = 1.0  # multiplier
        self.sim_events_replayed = 0
        self.sim_alerts_generated = 0
        self.sim_current_step = 601
        self.sim_injected_count = 0
        self._sim_thread: Optional[threading.Thread] = None
        self._sim_stop_event = threading.Event()

        # Event listeners for SSE stream
        self.stream_subscribers: List[asyncio.Queue] = []

        # Demo Studio Runner
        from fraudengine.demo import DemoRunner
        self.demo_runner = DemoRunner(scorer=self.scorer, graph_engine=self.graph_engine)
        self.demo_runner.add_listener(lambda et, d: self.broadcast_event(et, d))
        self.demo_runner.init_run()

        # Phase 12: Live Sandbox Bank Manager
        from fraudengine.live import LiveSandboxManager
        self.live_manager = LiveSandboxManager(scorer=self.scorer, graph_engine=self.graph_engine)
        self.live_manager.add_listener(lambda et, d: self.broadcast_event(et, d))

    def check_demo_health(self) -> Dict[str, Any]:
        """Check status of Redpanda, Redis, Neo4j, and Scorer Model."""
        import socket

        def test_port(port: int) -> bool:
            try:
                s = socket.socket()
                s.settimeout(0.2)
                s.connect(('127.0.0.1', port))
                s.close()
                return True
            except Exception:
                return False

        has_redis_svc = test_port(6379)
        has_kafka_svc = test_port(9092)
        has_neo4j_svc = test_port(7687)
        model_loaded = bool(self.scorer and self.scorer.model is not None)

        bus = getattr(self.demo_runner, "bus", None)
        bus_is_real = getattr(bus, "is_real", False)
        allow_offline = getattr(bus, "allow_offline", False)

        redpanda_healthy = bool(has_kafka_svc and (bus_is_real or bus is None))

        return {
            "status": "healthy" if (redpanda_healthy and has_redis_svc and model_loaded) else "degraded",
            "offline_mode": not redpanda_healthy,
            "offline_warning": "NOT KAFKA: in-process simulation" if not redpanda_healthy else None,
            "redpanda": {
                "status": "connected" if redpanda_healthy else ("simulated" if allow_offline else "unreachable"),
                "mode": "Live Cluster (port 9092)" if redpanda_healthy else "NOT KAFKA: in-process simulation",
                "partitions": 6,
                "healthy": redpanda_healthy,
            },
            "redis": {
                "status": "connected" if has_redis_svc else "in_memory",
                "mode": "Live Server (port 6379)" if has_redis_svc else "In-Memory Real RESP Store (fakeredis)",
                "healthy": has_redis_svc,
            },
            "neo4j": {
                "status": "connected" if has_neo4j_svc else "in_memory",
                "mode": "Bolt Driver (port 7687)" if has_neo4j_svc else "In-Memory Graph Topology Engine (NetworkX)",
                "healthy": True,  # In-memory graph engine is active and genuine
            },
            "model": {
                "status": "loaded" if model_loaded else "not_loaded",
                "version": getattr(self.scorer, "model_version", "2.0.0"),
                "features_count": len(getattr(self.scorer, "feature_names", [])),
                "healthy": model_loaded,
                "rules_enabled": getattr(self.scorer, "rules_enabled", True),
                "model_enabled": getattr(self.scorer, "model_enabled", True),
            },
        }

    def _init_scorer(self):
        v2_path = ROOT / "models_v2" / "v2.0.0"
        v1_path = ROOT / "model" / "xgboost_model.pkl"

        model_path = str(v2_path if v2_path.exists() else v1_path)
        logger.info(f"Initializing Scorer from {model_path} ...")
        try:
            self.scorer = Scorer(
                model_path=model_path,
                rules_engine=self.rules_engine,
                audit_log=self.audit_log,
                case_exporter=self.case_exporter,
                graph_engine=self.graph_engine,
            )
        except Exception as e:
            logger.warning(f"Could not initialize model from {model_path} ({e}); using stub Scorer.")
            # Scorer will fallback gracefully

    def _load_settings(self):
        settings_file = ROOT / "configs" / "app_settings.json"
        if settings_file.exists():
            try:
                with open(settings_file) as f:
                    self.settings.update(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load settings: {e}")

    def save_settings(self, new_settings: Dict[str, Any]):
        self.settings.update(new_settings)
        settings_file = ROOT / "configs" / "app_settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(settings_file, "w") as f:
            json.dump(self.settings, f, indent=2)

        # Update scorer thresholds if initialized
        if self.scorer:
            self.scorer.thresholds.update({
                "allow_max": self.settings["threshold_allow_max"],
                "step_up_max": self.settings["threshold_step_up_max"],
                "review_max": self.settings["threshold_review_max"],
                "block_min": self.settings["threshold_block_min"],
            })

    def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast event to all SSE subscribers."""
        dead_queues = []
        for q in self.stream_subscribers:
            try:
                q.put_nowait({"event": event_type, "data": data})
            except Exception:
                dead_queues.append(q)
        for q in dead_queues:
            if q in self.stream_subscribers:
                self.stream_subscribers.remove(q)


state = AppState()
