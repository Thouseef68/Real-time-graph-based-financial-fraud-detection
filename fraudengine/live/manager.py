"""Live Sandbox Manager orchestrating rooms, network IP detection, and live transfer pipelines."""

from __future__ import annotations

import logging
import socket
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import yaml

from fraudengine.demo.bus import DemoMessageBus
from fraudengine.demo.containment import ContainmentPolicy
from fraudengine.demo.redis_store import DemoRedisStore
from fraudengine.graph.engine import GraphEngine
from fraudengine.live.room import SandboxRoom, Participant
from fraudengine.scoring.core import Decision, Reason, RuleHit, Scorer

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
PROFILE_CONFIG = ROOT / "configs" / "live_profile.yaml"


def get_local_lan_ip() -> str:
    """Detects local LAN IPv4 address (e.g. 192.168.x.x) for phone QR join."""
    # Try connecting a dummy socket to an external address to get default outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Fallback to hostname lookup
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


class LiveSandboxManager:
    """Central engine managing live rooms, participant transfers, real-time scoring, and analyst controls."""

    def __init__(
        self,
        scorer: Scorer,
        graph_engine: GraphEngine,
        redis_store: Optional[DemoRedisStore] = None,
        bus: Optional[DemoMessageBus] = None,
    ):
        self.scorer = scorer
        self.graph_engine = graph_engine
        self.redis_store = redis_store or DemoRedisStore(prefix="live:sandbox:")
        self.bus = bus or DemoMessageBus(run_id="live_sandbox")
        self.containment = ContainmentPolicy(redis_store=self.redis_store, graph_engine=self.graph_engine)

        self.rooms: Dict[str, SandboxRoom] = {}
        self.listeners: List[Callable[[str, Dict[str, Any]], None]] = []

        # Load live demo sensitivity profile
        self.profile = self._load_profile()

        # Connect redis deltas and kafka bus messages to live stream listeners
        self.redis_store.on_delta(self._on_redis_delta)
        self.bus.on_message(self._on_kafka_message)

        # Pre-seed default room MULE42 for immediate demo readiness
        self.create_room(room_code="MULE42")

    def _load_profile(self) -> Dict[str, Any]:
        if PROFILE_CONFIG.exists():
            try:
                with open(PROFILE_CONFIG, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                logger.warning(f"Could not parse live_profile.yaml ({e}); using defaults")
        return {
            "profile_name": "demo_sensitivity",
            "time_compression": {"scale_factor": 60.0, "base_sim_step": 700},
            "thresholds": {
                "min_fan_in_senders": 3,
                "min_pass_through_ratio": 0.70,
                "burst_velocity_count": 3,
                "max_transfer_amount": 50000.0,
                "default_starting_balance": 10000.0,
                "rate_limit_max_txns": 5,
                "rate_limit_window_seconds": 10.0,
                "room_ttl_seconds": 7200,
            },
        }

    def add_listener(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        self.listeners.append(callback)

    def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        for cb in self.listeners:
            try:
                cb(event_type, data)
            except Exception as e:
                logger.debug(f"Live listener error: {e}")

    def _on_redis_delta(self, delta: Dict[str, Any]) -> None:
        self.emit("redis_delta", delta)

    def _on_kafka_message(self, msg: Dict[str, Any]) -> None:
        self.emit("kafka_message", msg)

    # ─────────────────────────────────────────────────────────────
    # Room Management
    # ─────────────────────────────────────────────────────────────

    def create_room(self, room_code: Optional[str] = None, scale_factor: Optional[float] = None) -> SandboxRoom:
        code = (room_code or f"MULE{random.randint(10, 99)}").upper()
        scale = scale_factor if scale_factor is not None else self.profile["time_compression"]["scale_factor"]
        starting_bal = self.profile["thresholds"]["default_starting_balance"]
        ttl = self.profile["thresholds"]["room_ttl_seconds"]

        room = SandboxRoom(
            room_code=code,
            scale_factor=scale,
            starting_balance=starting_bal,
            ttl_seconds=ttl,
        )
        self.rooms[code] = room
        logger.info(f"Created Sandbox Room [{code}] with scale factor {scale}x")
        self.emit("room_created", room.to_dict())
        return room

    def get_room(self, room_code: str, auto_create: bool = False) -> Optional[SandboxRoom]:
        code = room_code.upper()
        room = self.rooms.get(code)
        if room and room.is_expired():
            self.wipe_room(code)
            return None
        if not room and (auto_create or code == "MULE42"):
            # Auto-create room so participants joining with any code immediately succeed
            return self.create_room(room_code=code)
        return room

    def get_room_dict(self, room_code: str) -> Optional[Dict[str, Any]]:
        room = self.get_room(room_code)
        if not room:
            return None
        d = room.to_dict()
        for p in d.get("participants", []):
            acc_id = p["account_id"]
            if self.redis_store.is_account_blocked(acc_id):
                p["engine_status"] = "BLOCKED"
            elif self.redis_store.is_account_held(acc_id):
                p["engine_status"] = "HELD"
            elif self.redis_store.is_account_monitored(acc_id):
                p["engine_status"] = "MONITORING"
            else:
                p["engine_status"] = "NORMAL"

            p["fan_in_count"] = self.redis_store.get_fan_in_count(acc_id)
            inflow = self.redis_store.get_inflow(acc_id)
            outflow = self.redis_store.get_outflow(acc_id)
            p["inflow"] = inflow
            p["outflow"] = outflow
            p["pass_through"] = round(outflow / inflow, 2) if inflow > 0 else 0.0
        return d

    def get_live_debug_state(self, room_code: str) -> Dict[str, Any]:
        """Return live inspection state: Kafka messages, Redis keys, and latest decision."""
        keys = self.redis_store.get_all_keys()
        key_vals = {}
        for k in keys:
            t = self.redis_store.client.type(k)
            t_str = t.decode() if isinstance(t, bytes) else str(t)
            if t_str == "set":
                raw = list(self.redis_store.client.smembers(k))
                val = [x.decode() if isinstance(x, bytes) else str(x) for x in raw]
            elif t_str == "zset":
                raw = self.redis_store.client.zrange(k, 0, -1, withscores=True)
                val = [(x[0].decode() if isinstance(x[0], bytes) else str(x[0]), x[1]) for x in raw]
            elif t_str == "hash":
                raw = self.redis_store.client.hgetall(k)
                val = {k2.decode() if isinstance(k2, bytes) else str(k2): v.decode() if isinstance(v, bytes) else str(v) for k2, v in raw.items()}
            else:
                raw = self.redis_store.client.get(k)
                val = raw.decode() if isinstance(raw, bytes) else str(raw)
            key_vals[k] = val

        room = self.get_room(room_code)
        return {
            "room_code": room_code,
            "kafka_messages": getattr(self.bus, "published_events", [])[-10:],
            "redis_keys": key_vals,
            "transfers_count": len(room.transfers) if room else 0,
            "recent_transfers": room.transfers[-5:] if room else [],
        }

    def list_rooms(self) -> List[Dict[str, Any]]:
        # Clean up expired
        expired = [c for c, r in self.rooms.items() if r.is_expired()]
        for c in expired:
            self.wipe_room(c)
        return [r.to_dict() for r in self.rooms.values()]

    def wipe_room(self, room_code: str) -> bool:
        code = room_code.upper()
        room = self.rooms.pop(code, None)
        if room:
            room.recorder.save()
            # 1. Clean up all Redis keys for this room
            try:
                if hasattr(self.redis_store, "client") and self.redis_store.client is not None:
                    prefix_pattern = f"live:sandbox:{code}:*"
                    keys = self.redis_store.client.keys(prefix_pattern)
                    if keys:
                        self.redis_store.client.delete(*keys)
                self.redis_store.reset()
            except Exception as e:
                logger.warning(f"Error deleting Redis keys for room {code}: {e}")

            # 2. Clean up graph nodes for participants in this room
            if hasattr(self.graph_engine, "g"):
                for p in room.participants.values():
                    if p.account_id in self.graph_engine.g:
                        try:
                            self.graph_engine.g.remove_node(p.account_id)
                        except Exception:
                            pass
                    if p.device_id in self.graph_engine.g:
                        try:
                            self.graph_engine.g.remove_node(p.device_id)
                        except Exception:
                            pass

            self.emit("room_wiped", {"room_code": code})
            logger.info(f"Wiped Sandbox Room [{code}] with zero residue.")
            return True
        return False

    def get_room_join_info(
        self,
        room_code: str,
        port: int = 5173,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        room = self.get_room(room_code)
        join_token = room.join_token if room else ""

        # Priority 1: Direct request base_url passed in from live client request
        import os
        public_base = (base_url or "").strip().rstrip("/")
        
        # If public_base is localhost or 127.0.0.1, check Render or env vars
        if not public_base or "localhost" in public_base or "127.0.0.1" in public_base:
            render_ext = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
            if render_ext:
                public_base = render_ext

        if not public_base or "localhost" in public_base or "127.0.0.1" in public_base:
            env_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
            if env_base:
                public_base = env_base

        if not public_base or "localhost" in public_base or "127.0.0.1" in public_base:
            env_file = ROOT / ".env"
            if env_file.exists():
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("PUBLIC_BASE_URL="):
                                public_base = line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
                                break
                except Exception:
                    pass

        # If we have a valid public base (not localhost), use it for universal internet join
        if public_base and not ("127.0.0.1" in public_base or "localhost" in public_base):
            join_url = f"{public_base}/app?room={room_code.upper()}&token={join_token}"
            host_display = public_base
            is_tunnel = True
        else:
            lan_ip = get_local_lan_ip()
            join_url = f"http://{lan_ip}:{port}/app?room={room_code.upper()}&token={join_token}"
            host_display = f"http://{lan_ip}:{port}"
            is_tunnel = False

        return {
            "room_code": room_code.upper(),
            "join_token": join_token,
            "lan_ip": get_local_lan_ip(),
            "port": port,
            "join_url": join_url,
            "host_display": host_display,
            "is_public_tunnel": bool(is_tunnel),
            "profile_name": self.profile.get("profile_name", "demo_sensitivity"),
        }

    # ─────────────────────────────────────────────────────────────
    # Live Transfer Execution Pipeline
    # ─────────────────────────────────────────────────────────────

    def execute_transfer(
        self,
        room_code: str,
        sender_id: str,
        receiver_id: str,
        amount: float,
        note: str = "",
        idempotency_key: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_id: Optional[str] = None,
        session_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        room = self.get_room(room_code)
        if not room:
            return {"status": "ERROR", "customer_message": "Room not found or expired.", "error_code": "ROOM_NOT_FOUND"}

        # 1. Idempotency Check
        if idempotency_key:
            cached = room.check_idempotency(idempotency_key)
            if cached:
                logger.info(f"Idempotency hit for key {idempotency_key}")
                return cached

        # 2. Token Isolation & Ownership Verification (A participant cannot send from another account)
        if session_token:
            auth_account = room.token_to_account.get(session_token)
            if not auth_account or auth_account != sender_id:
                return {
                    "status": "DECLINED",
                    "customer_message": "Unauthorized: session token does not permit transfers from this account.",
                    "error_code": "UNAUTHORIZED_TOKEN",
                }

        # 3. Basic Validation
        sender = room.get_participant(sender_id)
        receiver = room.get_participant(receiver_id)
        if not sender:
            return {"status": "ERROR", "customer_message": "Sender account not found in room.", "error_code": "INVALID_SENDER"}
        if not receiver:
            return {"status": "ERROR", "customer_message": "Recipient account not found in room.", "error_code": "INVALID_RECEIVER"}

        # Rate Limit Check per token and per network prefix
        prefix = sender.network_prefix or "127.0.0.0/24"
        allowed, rl_msg = room.check_rate_limits(session_token or sender_id, prefix)
        if not allowed:
            return {
                "status": "DECLINED",
                "customer_message": rl_msg,
                "error_code": "RATE_LIMITED",
            }
        if sender_id == receiver_id:
            return {"status": "DECLINED", "customer_message": "Cannot transfer funds to your own account.", "error_code": "SELF_TRANSFER"}
        if amount <= 0:
            return {"status": "DECLINED", "customer_message": "Transfer amount must be greater than zero.", "error_code": "INVALID_AMOUNT"}

        max_amount = self.profile["thresholds"]["max_transfer_amount"]
        if amount > max_amount:
            return {
                "status": "DECLINED",
                "customer_message": f"Transfer exceeds sandbox limit of ₹{max_amount:,.2f}.",
                "error_code": "EXCEEDS_MAX_LIMIT",
            }

        if sender.balance < amount:
            return {
                "status": "DECLINED",
                "customer_message": f"Insufficient virtual funds. Current balance is ₹{sender.balance:,.2f}.",
                "error_code": "INSUFFICIENT_FUNDS",
            }

        # 4. Point-in-Time Clock Calculation
        current_step = room.clock.current_step
        current_hour = room.clock.current_hour_of_day
        sim_timestamp = room.clock.simulated_timestamp
        wall_start = time.perf_counter()

        txn_id = f"TXN_{room.room_code}_{int(time.time()*1000)}"
        effective_device = device_id or sender.device_id
        effective_network = sender.network_label or "Campus-WiFi"

        # 5. Pre-Scoring Redis Blocklist Filter in Hot Path (< 0.1ms)
        is_blocked = self.redis_store.is_account_blocked(sender_id) or self.redis_store.is_device_blocked(effective_device)
        is_held = self.redis_store.is_account_held(sender_id)

        if is_blocked:
            latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 3)
            room.money_saved += amount
            decline_resp = {
                "status": "DECLINED",
                "customer_message": "Payment declined by bank security systems.",
                "txn_id": txn_id,
                "amount": amount,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "tier": "BLOCK",
                "reason": "Pre-Score Blocklist Filter: Account or Device active in Redis blocklist",
                "latency_ms": latency_ms,
                "profile": "demo_sensitivity",
            }
            if idempotency_key:
                room.record_idempotency(idempotency_key, decline_resp)
            room.recorder.record_event("transfer_declined", decline_resp)
            self.emit("decision", {
                "txn_id": txn_id,
                "score": 1.0,
                "tier": "BLOCK",
                "summary": f"Transfer blocked by pre-score filter for account {sender_id}.",
                "latency_ms": latency_ms,
                "reasons": [{"title": "Redis Blocklist Intercept", "description": "Account/device actively blocked.", "feature": "blocklist", "value": 1.0}],
            })
            return decline_resp

        if is_held:
            latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 3)
            room.money_held += amount
            held_resp = {
                "status": "HELD",
                "customer_message": "Payment held for compliance review. Funds have been temporarily frozen.",
                "txn_id": txn_id,
                "amount": amount,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "tier": "HOLD",
                "reason": "Containment Hold: Account held due to graph link with confirmed mule ring",
                "latency_ms": latency_ms,
                "profile": "demo_sensitivity",
            }
            if idempotency_key:
                room.record_idempotency(idempotency_key, held_resp)
            room.recorder.record_event("transfer_held", held_resp)
            return held_resp

        # 6. Real Kafka & Redis State Mutation
        txn_msg = {
            "txn_id": txn_id,
            "account_id": sender_id,
            "payee_id": receiver_id,
            "amount": float(amount),
            "step": current_step,
            "hour_of_day": current_hour,
            "txn_type": "TRANSFER",
            "device_id": effective_device,
            "ip_prefix": effective_network,
            "timestamp": sim_timestamp,
        }
        self.bus.publish_transaction(txn_msg)
        self.redis_store.record_velocity(sender_id, amount, current_step, txn_id)
        # Register payee inflow in Redis for fan-in tracking
        self.redis_store.record_fan_in(receiver_id, sender_id, txn_id=txn_id, amount=amount)

        # 7. Update Dynamic Graph Topology
        self.graph_engine.update_transaction(
            account_id=sender_id,
            payee_id=receiver_id,
            amount=amount,
            device_id=effective_device,
            ip_prefix=effective_network,
            label=0,
            step=current_step,
        )
        self.emit("graph_delta", {
            "nodes": [
                {"data": {"id": sender_id, "label": sender.display_name, "type": "account"}},
                {"data": {"id": receiver_id, "label": receiver.display_name, "type": "account"}},
                {"data": {"id": effective_device, "label": effective_device, "type": "device"}},
                {"data": {"id": effective_network, "label": effective_network, "type": "ip_prefix"}},
            ],
            "edges": [
                {"data": {"source": sender_id, "target": receiver_id, "type": "TRANSFER", "amount": amount}},
                {"data": {"source": sender_id, "target": effective_device, "type": "USED_DEVICE"}},
                {"data": {"source": effective_device, "target": effective_network, "type": "ON_IP"}},
            ],
        })

        # 8. Demo Sensitivity Rule Evaluation (Small Cohort Thresholds)
        # Check payee fan-in in Redis
        fan_in_count = self.redis_store.get_fan_in_count(receiver_id)
        min_fan_in = self.profile["thresholds"]["min_fan_in_senders"]

        # Check sender pass-through ratio
        inflow = self.redis_store.get_inflow(sender_id)
        outflow = self.redis_store.get_outflow(sender_id) + amount
        pass_through_ratio = (outflow / max(1.0, inflow)) if inflow > 0 else 0.0
        min_pass_through = self.profile["thresholds"]["min_pass_through_ratio"]

        # 9. Scorer Execution (XGBoost v2 + SHAP)
        decision = self.scorer.score(txn_msg)
        tier = decision.tier
        reasons = list(decision.reasons)

        # Elevate to REVIEW or BLOCK if demo sensitivity conditions match
        is_demo_pass_through = (inflow >= 2000.0 and pass_through_ratio >= min_pass_through)
        is_demo_fan_in = (fan_in_count >= min_fan_in)

        if is_demo_pass_through:
            tier = "BLOCK"
            reasons.insert(0, Reason(
                title="Rapid Pass-Through Layering",
                explanation=f"Account forwarded {pass_through_ratio*100:.1f}% of received inflow within the window.",
                severity="critical",
                evidence={"pass_through_ratio": pass_through_ratio},
            ))
        elif is_demo_fan_in:
            if tier == "ALLOW":
                tier = "REVIEW"
            reasons.insert(0, Reason(
                title="High Payee Fan-In Accumulation",
                explanation=f"Recipient accumulated transfers from {fan_in_count} distinct senders.",
                severity="high",
                evidence={"fan_in_count": float(fan_in_count)},
            ))

        latency_ms = round((time.perf_counter() - wall_start) * 1000.0, 3)

        rule_hit_present = is_demo_pass_through or is_demo_fan_in or len(getattr(decision, "rule_hits", [])) > 0
        model_hit_present = getattr(decision, "model_score", decision.score) >= 0.3
        if rule_hit_present and model_hit_present:
            det_src = "Both"
        elif rule_hit_present:
            det_src = "Rule"
        elif model_hit_present:
            det_src = "Model"
        else:
            det_src = "Normal"

        decision_dict = {
            "txn_id": txn_id,
            "score": round(max(0.92 if tier == "BLOCK" else (0.65 if tier == "REVIEW" else decision.score), decision.score), 4),
            "model_score": getattr(decision, "model_score", decision.score),
            "detection_source": det_src,
            "rule_hits": getattr(decision, "rule_hits", []),
            "tier": tier,
            "summary": "Transfer flagged by real-time demo sensitivity rules." if (is_demo_pass_through or is_demo_fan_in) else decision.summary,
            "action": "Immediate Fraud Freeze" if tier == "BLOCK" else ("Queue for Review" if tier == "REVIEW" else "Authorize"),
            "reasons": [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in reasons],
            "latency_ms": latency_ms,
            "profile": "demo_sensitivity",
            "timestamp": time.time(),
        }
        self.bus.publish_decision(decision_dict)
        self.emit("decision", decision_dict)

        # 10. Ledger Update & Customer-Safe Response
        if tier == "BLOCK":
            # Auto containment on confirmed block
            room.money_saved += amount
            containment_res = self.containment.execute_containment(sender_id, reason="Live Demo: Confirmed mule pass-through")
            self.emit("containment_action", containment_res)

            resp = {
                "status": "DECLINED",
                "customer_message": "Payment declined by bank security systems.",
                "txn_id": txn_id,
                "amount": amount,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "tier": "BLOCK",
                "latency_ms": latency_ms,
                "profile": "demo_sensitivity",
            }
        elif tier == "REVIEW":
            # Place in analyst case queue, hold money in transit
            room.money_held += amount
            case_id = f"CASE_{txn_id}"
            case_data = {
                "case_id": case_id,
                "txn": txn_msg,
                "decision": decision_dict,
                "amount": amount,
                "sender_display": sender.display_name,
                "receiver_display": receiver.display_name,
            }
            room.add_case_to_queue(case_id, case_data)
            self.emit("live_case", case_data)

            resp = {
                "status": "HELD",
                "customer_message": "Payment received and held for routine compliance verification.",
                "txn_id": txn_id,
                "amount": amount,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "tier": "REVIEW",
                "latency_ms": latency_ms,
                "profile": "demo_sensitivity",
            }
        else:
            # ALLOW: Settle ledger balances
            sender.balance -= amount
            receiver.balance += amount
            room.money_moved += amount

            resp = {
                "status": "PROCESSED",
                "customer_message": "Payment sent successfully.",
                "txn_id": txn_id,
                "amount": amount,
                "sender_id": sender_id,
                "receiver_id": receiver_id,
                "sender_balance": sender.balance,
                "tier": "ALLOW",
                "latency_ms": latency_ms,
                "profile": "demo_sensitivity",
            }

        # Log transfer in room history
        room.transfers.append({
            "txn_id": txn_id,
            "sender_id": sender_id,
            "sender_name": sender.display_name,
            "receiver_id": receiver_id,
            "receiver_name": receiver.display_name,
            "amount": amount,
            "note": note,
            "status": resp["status"],
            "tier": tier,
            "score": decision_dict.get("score", 0.0),
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        })

        if idempotency_key:
            room.record_idempotency(idempotency_key, resp)

        room.recorder.record_event("transfer_completed", {
            "txn_id": txn_id,
            "sender": sender_id,
            "receiver": receiver_id,
            "amount": amount,
            "decision": decision_dict,
            "response": resp,
        })

        self.emit("ledger_update", {
            "totals": {
                "money_moved": room.money_moved,
                "money_held": room.money_held,
                "money_saved": room.money_saved,
            },
            "last_transfer": resp,
        })
        return resp

    # ─────────────────────────────────────────────────────────────
    # Analyst Actions (Console Controls)
    # ─────────────────────────────────────────────────────────────

    def approve_case(self, room_code: str, case_id: str) -> Dict[str, Any]:
        room = self.get_room(room_code)
        if not room or case_id not in room.case_queue:
            return {"status": "ERROR", "message": "Case not found"}

        case = room.case_queue[case_id]
        if case["status"] != "PENDING":
            return {"status": "ERROR", "message": f"Case already {case['status']}"}

        sender = room.get_participant(case["txn"]["account_id"])
        receiver = room.get_participant(case["txn"]["payee_id"])
        amount = case["amount"]

        if sender and receiver and sender.balance >= amount:
            sender.balance -= amount
            receiver.balance += amount
            room.money_moved += amount
            room.money_held = max(0.0, room.money_held - amount)

        case["status"] = "APPROVED"
        case["resolved_at"] = time.time()
        room.recorder.record_event("case_approved", {"case_id": case_id, "amount": amount})
        self.emit("case_resolved", case)
        return {"status": "SUCCESS", "message": f"Case {case_id} approved. Funds settled."}

    def block_case(self, room_code: str, case_id: str) -> Dict[str, Any]:
        room = self.get_room(room_code)
        if not room or case_id not in room.case_queue:
            return {"status": "ERROR", "message": "Case not found"}

        case = room.case_queue[case_id]
        if case["status"] != "PENDING":
            return {"status": "ERROR", "message": f"Case already {case['status']}"}

        sender_id = case["txn"]["account_id"]
        amount = case["amount"]
        room.money_held = max(0.0, room.money_held - amount)
        room.money_saved += amount

        # Block account in Redis and execute containment
        self.redis_store.block_account(sender_id)
        containment_res = self.containment.execute_containment(sender_id, reason="Analyst manual escalation")

        case["status"] = "BLOCKED"
        case["resolved_at"] = time.time()
        room.recorder.record_event("case_blocked", {"case_id": case_id, "containment": containment_res})
        self.emit("case_resolved", case)
        self.emit("containment_action", containment_res)
        return {"status": "SUCCESS", "message": f"Account {sender_id} blocked and containment executed."}

    def release_hold(self, room_code: str, account_id: str) -> Dict[str, Any]:
        room = self.get_room(room_code)
        if not room:
            return {"status": "ERROR", "message": "Room not found"}

        self.redis_store.unhold_account(account_id)
        room.recorder.record_event("hold_released", {"account_id": account_id})
        self.emit("hold_released", {"account_id": account_id})
        return {"status": "SUCCESS", "message": f"Hold released for account {account_id}"}

    def get_live_debug_state(self, room_code: str) -> Dict[str, Any]:
        room = self.get_room(room_code)
        if not room:
            return {"status": "ERROR", "message": "Room not found"}

        raw_keys: Dict[str, Any] = {}
        prefix = f"{self.redis_store.prefix}*"
        if hasattr(self.redis_store, "client") and self.redis_store.client:
            try:
                for k in self.redis_store.client.keys(prefix):
                    k_str = k.decode() if isinstance(k, bytes) else str(k)
                    k_type = self.redis_store.client.type(k_str)
                    if k_type == "set":
                        raw_keys[k_str] = [m.decode() if isinstance(m, bytes) else str(m) for m in self.redis_store.client.smembers(k_str)]
                    elif k_type == "string":
                        val = self.redis_store.client.get(k_str)
                        raw_keys[k_str] = val.decode() if isinstance(val, bytes) else str(val)
                    else:
                        raw_keys[k_str] = str(k_type)
            except Exception:
                pass

        kafka_msgs = getattr(self.bus, "published_events", [])

        return {
            "room_code": room_code,
            "participants": [p.to_dict() for p in room.participants.values()],
            "transfers": room.transfers,
            "redis_keys": raw_keys,
            "kafka_messages": kafka_msgs,
        }

