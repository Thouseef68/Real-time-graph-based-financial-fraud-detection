"""Live Demo Studio runner executing the 7-act mule ring pipeline with real Redpanda, Redis, and Graph interactions."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from fraudengine.demo.bus import DemoMessageBus
from fraudengine.demo.containment import ContainmentPolicy
from fraudengine.demo.ledger import DemoLedger
from fraudengine.demo.redis_store import DemoRedisStore
from fraudengine.demo.scenario import DemoScenario
from fraudengine.graph.engine import GraphEngine
from fraudengine.scoring.core import Decision, Reason, RuleHit, Scorer

logger = logging.getLogger(__name__)


class DemoRunner:
    """Coordinates the deterministic 7-act story execution, real engine components, and SSE broadcast."""

    def __init__(
        self,
        scorer: Scorer,
        graph_engine: GraphEngine,
        redis_store: Optional[DemoRedisStore] = None,
        bus: Optional[DemoMessageBus] = None,
        ledger: Optional[DemoLedger] = None,
    ):
        self.scorer = scorer
        self.graph_engine = graph_engine
        self.redis_store = redis_store or DemoRedisStore(prefix="demo:mule:")
        self.bus = bus or DemoMessageBus(run_id="demo_mule")
        self.ledger = ledger or DemoLedger()

        self.containment = ContainmentPolicy(
            redis_store=self.redis_store,
            graph_engine=self.graph_engine,
        )

        # Wire up blocklist checker into the scorer's hot path
        self.scorer.blocklist_checker = self._check_blocklist

        self.seed = 42
        self.speed = 1.0
        self.protection_enabled = True
        self.is_running = False
        self.current_index = 0
        self.events: List[Dict[str, Any]] = []
        self.listeners: List[Callable[[str, Dict[str, Any]], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Listen for redis deltas and bus messages to broadcast
        self.redis_store.on_delta(self._on_redis_delta)
        self.bus.on_message(self._on_kafka_message)

    def _check_blocklist(self, txn: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
        """Pre-scoring hot-path filter called by Scorer.score()."""
        account_id = txn.get("account_id")
        device_id = txn.get("device_id")

        if self.redis_store.is_account_blocked(account_id):
            return (
                "BLOCK",
                "Account Blocklisted (Pre-Score Filter)",
                f"Account {account_id} is actively blocklisted in Redis by the automated fraud containment engine.",
            )
        if device_id and self.redis_store.is_device_blocked(device_id):
            return (
                "BLOCK",
                "Device Blocklisted (Pre-Score Filter)",
                f"Device hardware {device_id} is associated with confirmed fraud rings and is actively blocked in Redis.",
            )
        if self.redis_store.is_account_held(account_id):
            return (
                "BLOCK",
                "Outbound Transfer Declined (Account on Hold)",
                f"Account {account_id} is temporarily held in Redis due to graph linkage with confirmed fraud; outbound payment declined.",
            )
        return None

    def add_listener(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        self.listeners.append(callback)

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        for cb in self.listeners:
            try:
                cb(event_type, data)
            except Exception as e:
                logger.debug(f"Listener error: {e}")

    def _on_redis_delta(self, delta: Dict[str, Any]) -> None:
        self.emit("redis_delta", delta)

    def _on_kafka_message(self, msg: Dict[str, Any]) -> None:
        self.emit("kafka_message", msg)

    # ─────────────────────────────────────────────────────────────
    # Run Lifecycle
    # ─────────────────────────────────────────────────────────────

    def init_run(self, seed: int = 42, speed: float = 1.0, protection_enabled: bool = True) -> Dict[str, Any]:
        """Initialize or reset run state."""
        self.pause()
        self.seed = seed
        self.speed = max(0.2, min(speed, 10.0))
        self.protection_enabled = protection_enabled
        self.current_index = 0

        # 1. Reset Redis, Kafka bus, Ledger
        self.redis_store.reset()
        self.bus.reset()
        self.ledger.reset()

        # 2. Seed initial accounts in SQLite ledger
        scenario_builder = DemoScenario(seed=seed)
        cfg = scenario_builder.cfg
        actors = cfg["actors"]

        for key, m in actors["mules"].items():
            self.ledger.seed_account(m["account_id"], m["initial_balance"], f"Mule Member {key}", "mule")
        
        hh = actors["innocent_household"]
        self.ledger.seed_account(hh["account_id"], hh["initial_balance"], "Innocent Household Neighbor", "household")

        for i in range(1, 13):
            self.ledger.seed_account(f"CUST_VICTIM_{i:02d}", 25000.0, f"Victim {i:02d}", "victim")

        for i in range(1, 11):
            self.ledger.seed_account(f"CUST_NORM_{i:02d}", 5000.0, f"Normal Customer {i:02d}", "customer")

        cashout_id = actors["cashout"]["account_id"]
        self.ledger.seed_account(cashout_id, 100000.0, actors["cashout"]["name"], "merchant")

        # 3. Generate events
        self.events = scenario_builder.generate_events()

        logger.info(f"DemoRunner initialized with {len(self.events)} events (seed={seed}, protection={protection_enabled})")
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        totals = self.ledger.get_totals()
        current_act = 1
        if self.current_index < len(self.events):
            current_act = self.events[self.current_index].get("act", 1)
        elif self.events:
            current_act = self.events[-1].get("act", 7)

        return {
            "current_index": self.current_index,
            "total_events": len(self.events),
            "is_running": self.is_running,
            "speed": self.speed,
            "seed": self.seed,
            "protection_enabled": self.protection_enabled,
            "current_act": current_act,
            "money_moved": totals["money_moved"],
            "money_held": totals["money_held"],
            "money_saved": totals["money_saved"],
            "completed": self.current_index >= len(self.events),
            "blocklists": self.redis_store.get_summary(),
        }

    # ─────────────────────────────────────────────────────────────
    # Execution Step
    # ─────────────────────────────────────────────────────────────

    def step(self) -> Optional[Dict[str, Any]]:
        """Advance exactly one scenario event."""
        if self.current_index >= len(self.events):
            self.is_running = False
            return None

        event = self.events[self.current_index]
        self.current_index += 1
        etype = event.get("type")

        if etype == "narrative_step":
            self.emit("narrative_step", event)
            return event

        elif etype == "transaction":
            return self._process_transaction(event)

        elif etype == "containment_step":
            return self._process_containment(event)

        return event

    def _process_transaction(self, event: Dict[str, Any]) -> Dict[str, Any]:
        txn_id = event["txn_id"]
        account_id = event["account_id"]
        payee_id = event["payee_id"]
        amount = event["amount"]
        step = event.get("step", 700)
        device_id = event.get("device_id")
        ip_prefix = event.get("ip_prefix")
        act = event.get("act", 1)

        # 1. Publish to Kafka transactions topic
        kafka_evt = self.bus.publish_transaction(event)

        # 2. Update feature state in Redis
        if event.get("fanin_expected"):
            self.redis_store.record_fanin(payee_id, account_id, amount, step)
        self.redis_store.record_velocity(account_id, amount, step, txn_id)
        if event.get("is_passthrough"):
            self.redis_store.record_passthrough(account_id, amount * 1.02, amount)

        # 3. Update graph engine and feature store
        if hasattr(self.scorer, "feature_store") and self.scorer.feature_store:
            from fraudengine.features.engineering import update_stores
            event["label"] = event.get("is_fraud", 0)
            update_stores(self.scorer.feature_store, event, graph_engine=self.graph_engine)
        else:
            self.graph_engine.update_transaction(
                account_id=account_id,
                payee_id=payee_id,
                amount=amount,
                step=step,
                device_id=device_id,
                ip_prefix=ip_prefix,
                label=event.get("is_fraud", 0),
            )

        # Emit graph delta
        subgraph = self.graph_engine.get_2hop_subgraph(account_id, max_nodes=20)
        self.emit("graph_delta", {
            "account_id": account_id,
            "payee_id": payee_id,
            "device_id": device_id,
            "ip_prefix": ip_prefix,
            "subgraph": subgraph,
        })

        # 4. Score transaction using real Scorer
        decision = self.scorer.score(event)

        # Handle counterfactual protection mode
        tier = decision.tier
        if not self.protection_enabled:
            # Under protection OFF, fraud transactions pass through unabated
            tier = "ALLOW"

        # 5. Publish decision to Kafka decisions topic
        decision_dict = {
            "txn_id": txn_id,
            "score": decision.score,
            "model_score": getattr(decision, "model_score", decision.score),
            "detection_source": getattr(decision, "detection_source", "Normal"),
            "tier": tier,
            "original_tier": decision.tier,
            "summary": decision.summary,
            "action": getattr(decision, "recommended_action", getattr(decision, "action", "")),
            "reasons": [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in decision.reasons],
            "rule_hits": getattr(decision, "rule_hits", []),
            "latency_ms": decision.latency_ms,
            "rules_enabled": getattr(decision, "rules_enabled", True),
            "model_enabled": getattr(decision, "model_enabled", True),
            "timestamp": time.time(),
        }
        self.bus.publish_decision(decision_dict)
        self.emit("decision", decision_dict)

        # 6. Record in Ledger
        top_reason = decision.reasons[0].title if decision.reasons else "Normal"
        ledger_res = self.ledger.record_transfer(
            txn_id=txn_id,
            act_num=act,
            sender_id=account_id,
            receiver_id=payee_id,
            amount=amount,
            tier=tier,
            reason=top_reason,
            protection_enabled=self.protection_enabled,
        )
        self.emit("ledger_update", {
            "entry": ledger_res,
            "totals": self.ledger.get_totals(),
        })

        return {
            "event": event,
            "decision": decision_dict,
            "ledger": ledger_res,
        }

    def _process_containment(self, event: Dict[str, Any]) -> Dict[str, Any]:
        target = event["target_account"]
        res = self.containment.execute_containment(target, reason="Automated containment: confirmed mule ring node")
        self.emit("containment_action", res)
        return res

    # ─────────────────────────────────────────────────────────────
    # "Try It Yourself" User Transfer
    # ─────────────────────────────────────────────────────────────

    def execute_user_transfer(self, from_account: str, to_account: str, amount: float) -> Dict[str, Any]:
        """Execute interactive user transfer through the real pipeline."""
        txn_id = f"TXN_USER_{int(time.time()*1000)}"
        txn = {
            "txn_id": txn_id,
            "account_id": from_account,
            "payee_id": to_account,
            "amount": float(amount),
            "device_id": "DEV_USER_TESTER",
            "ip_prefix": "198.51.100.14",
            "hour_of_day": 14,
            "txn_type": "TRANSFER",
            "step": 708,
            "timestamp": time.time(),
        }

        # Run through bus & scorer
        self.bus.publish_transaction(txn)
        self.redis_store.record_velocity(from_account, amount, 708, txn_id)
        decision = self.scorer.score(txn)

        top_reason = decision.reasons[0].title if decision.reasons else "Normal"
        ledger_res = self.ledger.record_transfer(
            txn_id=txn_id,
            act_num=7,
            sender_id=from_account,
            receiver_id=to_account,
            amount=amount,
            tier=decision.tier,
            reason=top_reason,
            protection_enabled=self.protection_enabled,
        )

        decision_dict = {
            "txn_id": txn_id,
            "score": decision.score,
            "tier": decision.tier,
            "summary": decision.summary,
            "action": getattr(decision, "recommended_action", getattr(decision, "action", "")),
            "reasons": [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in decision.reasons],
            "latency_ms": decision.latency_ms,
        }
        self.bus.publish_decision(decision_dict)
        self.emit("decision", decision_dict)
        self.emit("ledger_update", {
            "entry": ledger_res,
            "totals": self.ledger.get_totals(),
        })

        return {
            "txn": txn,
            "decision": decision_dict,
            "ledger": ledger_res,
            "totals": self.ledger.get_totals(),
        }

    # ─────────────────────────────────────────────────────────────
    # Playback Controls
    # ─────────────────────────────────────────────────────────────

    def play(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()

        def _run_loop():
            while self.is_running and not self._stop_event.is_set():
                if self.current_index >= len(self.events):
                    self.is_running = False
                    self.emit("demo_complete", self.get_status())
                    break
                self.step()
                delay = 1.0 / max(self.speed, 0.2)
                time.sleep(delay)

        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
