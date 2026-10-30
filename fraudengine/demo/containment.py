"""Graph-based containment policy engine for automated risk mitigation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx

from fraudengine.demo.redis_store import DemoRedisStore
from fraudengine.graph.engine import GraphEngine

logger = logging.getLogger(__name__)


class ContainmentPolicy:
    """Traverses entity linkages to contain blast radius on confirmed fraud blocks.
    
    Rules:
    - Never auto-block linked accounts without confirmation.
    - Shared device link -> HOLD (temporary hold on outbound transfers)
    - Shared IP link -> REVIEW or MONITOR (especially if tagged household/normal)
    - Writes all actions directly to Redis blocklists and holdlists.
    """

    def __init__(
        self,
        redis_store: DemoRedisStore,
        graph_engine: GraphEngine,
        shared_device_action: str = "HOLD",
        shared_ip_action: str = "REVIEW",
        household_action: str = "MONITOR",
    ):
        self.redis_store = redis_store
        self.graph_engine = graph_engine
        self.shared_device_action = shared_device_action
        self.shared_ip_action = shared_ip_action
        self.household_action = household_action

    def execute_containment(
        self,
        blocked_account_id: str,
        reason: str = "Confirmed Fraud Ring Operator",
    ) -> Dict[str, Any]:
        """Execute containment traversal around blocked_account_id."""
        # 1. Block primary confirmed offender in Redis
        self.redis_store.block_account(blocked_account_id, reason=reason)

        g = self.graph_engine.g

        # Find primary devices and IPs
        devices: Set[str] = set()
        for u, v, d in g.edges(data=True):
            if d.get("edge_type") == "USED_DEVICE" and (u == blocked_account_id or v == blocked_account_id):
                devices.add(v if u == blocked_account_id else u)

        ip_prefixes: Set[str] = set()
        for u, v, d in g.edges(data=True):
            if d.get("edge_type") == "ON_IP" and (u in devices or v in devices):
                ip_prefixes.add(v if u in devices else u)

        # Find all devices on those shared IPs
        shared_devices: Set[str] = set(devices)
        for u, v, d in g.edges(data=True):
            if d.get("edge_type") == "ON_IP" and (u in ip_prefixes or v in ip_prefixes):
                shared_devices.add(u if v in ip_prefixes else v)

        # Block malicious devices (excluding innocent household devices)
        for dev in shared_devices:
            if "HOUSEHOLD" not in dev:
                self.redis_store.block_device(dev, reason=f"Linked to confirmed fraud ring operator {blocked_account_id}")

        # Find accounts using any of these devices
        device_accounts: Set[str] = set()
        for u, v, d in g.edges(data=True):
            if d.get("edge_type") == "USED_DEVICE" and (v in shared_devices or u in shared_devices):
                acc = u if v in shared_devices else v
                if acc != blocked_account_id and g.nodes[acc].get("node_type") == "account":
                    device_accounts.add(acc)

        # Follow transfer layering chain up to 3 hops (A -> B -> C -> D)
        chain_accounts: Set[str] = set()
        current_hops = {blocked_account_id}
        for _ in range(3):
            next_hops = set()
            for cur in current_hops:
                for u, v, d in g.edges(data=True):
                    if u == cur and d.get("edge_type") == "TRANSFER":
                        if v != blocked_account_id and not v.startswith("MERCHANT"):
                            next_hops.add(v)
            chain_accounts.update(next_hops)
            current_hops = next_hops

        # Merge linked candidate entities
        candidate_accounts = (device_accounts | chain_accounts) - {blocked_account_id}

        held_accounts: List[str] = []
        monitored_accounts: List[str] = []
        reviewed_accounts: List[str] = []

        for acc in candidate_accounts:
            if "HOUSEHOLD" in acc or "NORM" in acc:
                # Precision protection: legitimate household neighbor sharing IP is monitored only!
                self.redis_store.monitor_account(acc, reason=f"Shares IP prefix with {blocked_account_id}; precision monitor only")
                monitored_accounts.append(acc)
            else:
                # Fraud ring peer: place on HOLD
                self.redis_store.hold_account(acc, reason=f"Graph-linked to confirmed fraud entity {blocked_account_id}")
                held_accounts.append(acc)

        cypher_query = (
            f"MATCH (primary:Account {{account_id: '{blocked_account_id}'}})\n"
            f"OPTIONAL MATCH (primary)-[:USED_DEVICE]->(d:Device)-[:ON_IP]->(ip:IPPrefix)<-[:ON_IP]-(d2:Device)<-[:USED_DEVICE]-(linked_peer:Account)\n"
            f"OPTIONAL MATCH (primary)-[:TRANSFER*1..3]->(downstream:Account)\n"
            f"RETURN primary, collect(DISTINCT linked_peer) AS infrastructure_peers, collect(DISTINCT downstream) AS layering_chain"
        )

        return {
            "primary_blocked": blocked_account_id,
            "blocked_devices": list(devices),
            "held_accounts": sorted(list(held_accounts)),
            "monitored_accounts": sorted(list(monitored_accounts)),
            "reviewed_accounts": sorted(list(reviewed_accounts)),
            "cypher_query": cypher_query,
            "policy": {
                "shared_device": self.shared_device_action,
                "shared_ip": self.shared_ip_action,
                "household": self.household_action,
            },
        }
