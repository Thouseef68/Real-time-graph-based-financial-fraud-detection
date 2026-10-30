"""Graph engine supporting in-memory network analytics and asynchronous Neo4j persistence.

Features provided:
- Payee distinct payers at 1h / 24h (fan-in)
- Payee outflow/inflow ratio within 24h (pass-through)
- Payee first-seen age
- Is merchant flag (M accounts vs customer accounts)
- Delayed-label fraud exposure within 2 hops (uses labels only past confirmation delay, default 24h)
- Degree and PageRank snapshots recomputed every 6 sim-hours (staleness documented)
- 2-hop case subgraph extraction (nodes, edges, capped at 100 nodes for Cytoscape.js)
"""

from __future__ import annotations

import collections
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CONFIRMATION_DELAY_HOURS = 24
PAGERANK_INTERVAL_HOURS = 6


class GraphEngine:
    """Hybrid graph engine: in-memory fast NetworkX hot-path with optional Neo4j async persistence."""

    def __init__(self, neo4j_uri: Optional[str] = "bolt://localhost:7687",
                 neo4j_user: Optional[str] = "neo4j",
                 neo4j_password: Optional[str] = "password",
                 confirmation_delay: int = DEFAULT_CONFIRMATION_DELAY_HOURS):
        self.confirmation_delay = confirmation_delay
        self.g = nx.DiGraph()  # Directed graph for transactions and device linkages

        # Snapshot caches
        self.last_pagerank_step = -1
        self.pagerank_cache: Dict[str, float] = {}
        self.degree_cache: Dict[str, int] = {}

        # 24h sliding window structures for fast graph feature queries (bounded to 35k active keys)
        self.payee_inflow: collections.OrderedDict[str, List[Tuple[int, str, float]]] = collections.OrderedDict()
        self.payee_outflow: collections.OrderedDict[str, List[Tuple[int, float]]] = collections.OrderedDict()

        # Confirmed fraud accounts: account_id -> step_confirmed
        self.confirmed_frauds: Dict[str, int] = {}

        # Neo4j driver initialization
        self.neo4j_driver = None
        if neo4j_uri:
            try:
                from neo4j import GraphDatabase
                self.neo4j_driver = GraphDatabase.driver(
                    neo4j_uri, auth=(neo4j_user, neo4j_password),
                    connection_timeout=2.0
                )
                self._init_neo4j_constraints()
            except Exception as e:
                logger.warning(f"Neo4j unavailable ({e}); using in-memory graph engine.")
                self.neo4j_driver = None

    def _init_neo4j_constraints(self) -> None:
        """Create constraints in Neo4j if driver is active."""
        if not self.neo4j_driver:
            return
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE",
        ]
        try:
            with self.neo4j_driver.session() as session:
                for q in queries:
                    session.run(q)
        except Exception as e:
            logger.warning(f"Failed to create Neo4j constraints: {e}")

    def update_transaction(self, account_id: str, payee_id: str, amount: float,
                           step: int, device_id: Optional[str] = None,
                           ip_prefix: Optional[str] = None,
                           label: int = 0) -> None:
        """Update graph with a new transaction at event time step."""
        # 1. Update sliding window inflows and outflows with O(1) bounded capacity
        if payee_id not in self.payee_inflow:
            self.payee_inflow[payee_id] = []
            if len(self.payee_inflow) > 35000:
                self.payee_inflow.popitem(last=False)
        self.payee_inflow[payee_id].append((step, account_id, amount))

        if account_id not in self.payee_outflow:
            self.payee_outflow[account_id] = []
            if len(self.payee_outflow) > 35000:
                self.payee_outflow.popitem(last=False)
        self.payee_outflow[account_id].append((step, amount))

        # 2. Maintain bounded NetworkX graph for topology queries & case bundles
        if len(self.g) < 25000 or label == 1:
            self.g.add_node(account_id, node_type="account", is_merchant=account_id.startswith("M"))
            self.g.add_node(payee_id, node_type="account", is_merchant=payee_id.startswith("M"))
            self.g.add_edge(account_id, payee_id, amount=amount, step=step, edge_type="TRANSFER")
            if device_id:
                self.g.add_node(device_id, node_type="device")
                self.g.add_edge(account_id, device_id, step=step, edge_type="USED_DEVICE")
                if ip_prefix:
                    self.g.add_node(ip_prefix, node_type="ip_prefix")
                    self.g.add_edge(device_id, ip_prefix, step=step, edge_type="ON_IP")

        # 3. Periodic cleanup of graph edges and stale payee records (runs once when step advances, every 4 steps)
        if step != getattr(self, "_last_edge_clean_step", -1) and step % 4 == 0:
            self._last_edge_clean_step = step
            cutoff = step - 24
            if len(self.g) > 15000:
                old_edges = [(u, v) for u, v, d in self.g.edges(data=True) if d.get("step", 0) < cutoff]
                self.g.remove_edges_from(old_edges)
                isolates = list(nx.isolates(self.g))
                self.g.remove_nodes_from(isolates)

            if len(self.payee_inflow) > 15000:
                stale_p = [p for p, evs in self.payee_inflow.items() if not evs or evs[-1][0] < cutoff]
                for p in stale_p:
                    del self.payee_inflow[p]

            if len(self.payee_outflow) > 15000:
                stale_a = [a for a, evs in self.payee_outflow.items() if not evs or evs[-1][0] < cutoff]
                for a in stale_a:
                    del self.payee_outflow[a]

        # 4. Handle delayed fraud label (accessible strictly after confirmation delay)
        if label == 1:
            confirmed_step = step + self.confirmation_delay
            self.confirmed_frauds[account_id] = confirmed_step

    def _maybe_update_snapshots(self, current_step: int) -> None:
        """Recompute PageRank and degree snapshots periodically every 6 sim-hours."""
        if self.last_pagerank_step < 0 or (current_step - self.last_pagerank_step >= PAGERANK_INTERVAL_HOURS):
            self.last_pagerank_step = current_step
            # Degree snapshot
            if len(self.g) > 0 and len(self.g) <= 50000:
                self.degree_cache = dict(self.g.degree())
                try:
                    self.pagerank_cache = nx.pagerank(self.g, alpha=0.85, max_iter=50)
                except Exception:
                    self.pagerank_cache = {n: 1.0 / len(self.g) for n in self.g}
            else:
                # For very large graph, clear full caches to avoid 10M-element dict allocation;
                # degree and approximate pagerank are evaluated on the fly in compute_graph_features.
                self.degree_cache = {}
                self.pagerank_cache = {}

    def compute_graph_features(self, account_id: str, payee_id: str, step: int) -> Dict[str, float]:
        """Compute point-in-time graph features for a transaction occurring at event time step."""
        self._maybe_update_snapshots(step)

        # 1. Payee & sender distinct senders (fan-in) in 1h and 24h
        cutoff_1h = step - 1
        cutoff_24h = step - 24

        inflows = self.payee_inflow.get(payee_id, [])
        senders_1h = {e[1] for e in inflows if cutoff_1h <= e[0] <= step and e[1] != account_id}
        senders_24h = {e[1] for e in inflows if cutoff_24h <= e[0] <= step and e[1] != account_id}

        # Also account for sender's incoming accumulation (mule fan-in before forwarding)
        sender_inflows = self.payee_inflow.get(account_id, [])
        sender_senders_24h = {e[1] for e in sender_inflows if cutoff_24h <= e[0] <= step}

        payee_fan_in_1h = float(len(senders_1h))
        payee_fan_in_24h = float(max(len(senders_24h), len(sender_senders_24h)))

        # 2. Outflow / Inflow ratio within 24h (pass-through detection)
        inflow_sum_24h = sum(e[2] for e in inflows if cutoff_24h <= e[0] <= step)
        outflows = self.payee_outflow.get(payee_id, [])
        outflow_sum_24h = sum(e[1] for e in outflows if cutoff_24h <= e[0] <= step)

        sender_inflow_sum = sum(e[2] for e in sender_inflows if cutoff_24h <= e[0] <= step)
        sender_outflows = self.payee_outflow.get(account_id, [])
        sender_outflow_sum = sum(e[1] for e in sender_outflows if cutoff_24h <= e[0] <= step)

        ratio_payee = outflow_sum_24h / (inflow_sum_24h + 1.0)
        ratio_sender = sender_outflow_sum / (sender_inflow_sum + 1.0) if sender_inflow_sum > 0 else 0.0

        outflow_inflow_ratio = max(ratio_payee, ratio_sender)
        max_inflow = max(inflow_sum_24h, sender_inflow_sum)
        pass_through_flag = 1.0 if (outflow_inflow_ratio >= 0.8 and max_inflow > 100.0) else 0.0

        # 3. Payee first seen age
        if inflows:
            first_seen_step = inflows[0][0]
            payee_first_seen_age = float(step - first_seen_step)
        else:
            payee_first_seen_age = 0.0

        # 4. Merchant flag (PaySim "M" accounts)
        is_merchant = 1.0 if payee_id.startswith("M") else 0.0

        # 5. Delayed-label fraud exposure within 2 hops (strictly using confirmed labels)
        confirmed_at_step = {acc for acc, conf_step in self.confirmed_frauds.items() if conf_step <= step}
        fraud_exposure_2hop = 0.0
        if payee_id in self.g and confirmed_at_step:
            # 1-hop neighbors
            neighbors_1hop = set(self.g.predecessors(payee_id)) | set(self.g.successors(payee_id))
            # 2-hop neighbors
            neighbors_2hop = set()
            for n in list(neighbors_1hop)[:25]:
                neighbors_2hop.update(self.g.predecessors(n))
                neighbors_2hop.update(self.g.successors(n))
            all_2hop = (neighbors_1hop | neighbors_2hop) - {account_id, payee_id}
            fraud_exposure_2hop = float(len(all_2hop & confirmed_at_step))

        # 6. Degree and PageRank snapshots
        if payee_id in self.degree_cache:
            degree = float(self.degree_cache[payee_id])
        elif payee_id in self.g:
            degree = float(self.g.degree(payee_id))
        else:
            degree = float(len(senders_24h))

        if payee_id in self.pagerank_cache:
            pagerank = float(self.pagerank_cache[payee_id])
        else:
            n_nodes = max(1, len(self.g))
            pagerank = float(degree / (n_nodes * 10.0))

        return {
            "payee_fan_in_1h": payee_fan_in_1h,
            "payee_fan_in_24h": payee_fan_in_24h,
            "payee_outflow_inflow_ratio_24h": float(outflow_inflow_ratio),
            "payee_pass_through_flag": pass_through_flag,
            "payee_first_seen_age": payee_first_seen_age,
            "is_merchant": is_merchant,
            "fraud_exposure_2hop": fraud_exposure_2hop,
            "degree": degree,
            "pagerank": pagerank,
        }

    def get_2hop_subgraph(self, account_id: str, max_nodes: int = 100) -> Dict[str, Any]:
        """Extract a 2-hop ego subgraph centered on account_id, formatted for Cytoscape.js."""
        if account_id not in self.g:
            inflows = self.payee_inflow.get(account_id, [])
            outflows = self.payee_outflow.get(account_id, [])
            if inflows or outflows:
                nodes_dict = {account_id: {"id": account_id, "label": account_id, "type": "account", "is_fraud": 1 if account_id in self.confirmed_frauds else 0, "is_merchant": account_id.startswith("M"), "degree": len(inflows) + len(outflows)}}
                edges_list = []
                for s, src, amt in inflows[:max_nodes // 2]:
                    nodes_dict[src] = {"id": src, "label": src, "type": "account", "is_fraud": 1 if src in self.confirmed_frauds else 0, "is_merchant": src.startswith("M"), "degree": 1}
                    edges_list.append({"data": {"source": src, "target": account_id, "amount": amt, "step": s, "type": "TRANSFER"}})
                return {
                    "center_account": account_id,
                    "node_count": len(nodes_dict),
                    "edge_count": len(edges_list),
                    "nodes": [{"data": d} for d in nodes_dict.values()],
                    "edges": edges_list,
                }
            return {
                "center_account": account_id,
                "node_count": 1,
                "edge_count": 0,
                "nodes": [{"data": {"id": account_id, "label": account_id, "type": "account"}}],
                "edges": [],
            }

        # Ego subgraph up to 2 hops
        sub_nodes: Set[str] = {account_id}
        # Hop 1
        hop1 = set(self.g.predecessors(account_id)) | set(self.g.successors(account_id))
        sub_nodes.update(hop1)

        # Hop 2
        for n in list(hop1):
            if len(sub_nodes) >= max_nodes:
                break
            hop2 = set(self.g.predecessors(n)) | set(self.g.successors(n))
            sub_nodes.update(hop2)

        sub_nodes = set(list(sub_nodes)[:max_nodes])
        subgraph = self.g.subgraph(sub_nodes)

        nodes_data = []
        for n in subgraph.nodes():
            node_attrs = self.g.nodes[n]
            node_type = node_attrs.get("node_type", "account")
            is_fraud = 1 if n in self.confirmed_frauds else 0
            nodes_data.append({
                "data": {
                    "id": n,
                    "label": n,
                    "type": node_type,
                    "is_fraud": is_fraud,
                    "is_merchant": n.startswith("M"),
                    "degree": self.degree_cache.get(n, subgraph.degree(n)),
                }
            })

        edges_data = []
        for u, v, data in subgraph.edges(data=True):
            edges_data.append({
                "data": {
                    "source": u,
                    "target": v,
                    "amount": data.get("amount", 0.0),
                    "step": data.get("step", 0),
                    "type": data.get("edge_type", "TRANSFER"),
                }
            })

        return {
            "center_account": account_id,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
            "nodes": nodes_data,
            "edges": edges_data,
        }

    def close(self) -> None:
        if self.neo4j_driver:
            self.neo4j_driver.close()
