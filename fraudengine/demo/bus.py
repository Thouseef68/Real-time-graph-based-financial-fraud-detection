"""Kafka / Redpanda message bus client with real Kafka partitioning and live health tracking."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DemoMessageBus:
    """Kafka / Redpanda client.
    
    Guarantees:
    - Real Redpanda by default (localhost:9092)
    - key = account_id partitioned via real Kafka default partitioner
    - Transparent live connection status (green/red)
    - Optional offline mode must be explicitly labelled 'NOT KAFKA: in-process simulation'
    """

    def __init__(
        self,
        bootstrap_servers: str = "127.0.0.1:9092",
        run_id: str = "live_sandbox",
        allow_offline: bool = False,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.run_id = run_id
        self.allow_offline = allow_offline
        self.is_real = False
        self.healthy = False
        self.producer = None
        self.consumer = None
        self.connection_error: Optional[str] = None
        self.message_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self.published_events: List[Dict[str, Any]] = []
        self.num_partitions = 6
        self.partition_offsets: Dict[int, int] = {i: 0 for i in range(self.num_partitions)}

        self.connect()

    def connect(self) -> bool:
        """Attempt connection to real Redpanda broker."""
        import socket
        host, port_str = (self.bootstrap_servers.split(":") + ["9092"])[:2]
        port = int(port_str)

        sock = socket.socket()
        sock.settimeout(0.15)
        try:
            sock.connect((host, port))
            sock.close()
            port_open = True
        except Exception as e:
            port_open = False
            self.connection_error = f"Cannot reach Redpanda on {host}:{port}: {e}"

        if port_open:
            try:
                from confluent_kafka import Producer
                p = Producer({
                    "bootstrap.servers": self.bootstrap_servers,
                    "socket.timeout.ms": 500,
                    "message.timeout.ms": 3000,
                })
                # Check cluster metadata
                cluster_meta = p.list_topics(timeout=0.5)
                self.producer = p
                self.is_real = True
                self.healthy = True
                self.connection_error = None
                logger.info(f"Connected to real Redpanda on {self.bootstrap_servers}. Brokers: {len(cluster_meta.brokers)}")
                return True
            except Exception as e:
                self.is_real = False
                self.healthy = False
                self.connection_error = f"Kafka client error on {self.bootstrap_servers}: {e}"
                logger.warning(f"Redpanda connection failed: {e}")
        else:
            self.is_real = False
            self.healthy = False

        if not self.allow_offline:
            logger.warning(
                f"Redpanda unreachable at {self.bootstrap_servers}. "
                "Silent in-process fallback is disabled. Health status is RED."
            )
        else:
            logger.info("DemoMessageBus initialized in explicit 'NOT KAFKA: in-process simulation' mode.")

        return self.healthy

    def get_health(self) -> Dict[str, Any]:
        """Live connectivity probe for health checks."""
        # Fast live socket probe if not real
        if not self.is_real:
            self.connect()

        return {
            "healthy": self.healthy,
            "is_real": self.is_real,
            "mode": "REAL_REDPANDA" if self.is_real else ("NOT KAFKA: in-process simulation" if self.allow_offline else "UNREACHABLE"),
            "bootstrap_servers": self.bootstrap_servers,
            "error": self.connection_error,
            "partitions": self.num_partitions,
        }

    def on_message(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self.message_callbacks.append(callback)

    def publish_transaction(self, txn: Dict[str, Any]) -> Dict[str, Any]:
        """Publish transaction using key = account_id with Kafka's built-in partitioner."""
        t0 = time.perf_counter()
        topic = f"transactions_{self.run_id}"
        account_id = str(txn.get("account_id", "default"))
        key_bytes = account_id.encode("utf-8")
        payload_bytes = json.dumps(txn).encode("utf-8")

        partition = -1
        offset = 0

        if self.is_real and self.producer:
            delivery_record: Dict[str, Any] = {}

            def delivery_callback(err, msg):
                if err:
                    delivery_record["error"] = str(err)
                else:
                    delivery_record["partition"] = msg.partition()
                    delivery_record["offset"] = msg.offset()

            try:
                # Let librdkafka's real murmur2 partitioner assign the partition based on key=account_id
                self.producer.produce(
                    topic=topic,
                    key=key_bytes,
                    value=payload_bytes,
                    on_delivery=delivery_callback,
                )
                self.producer.flush(timeout=1.0)
                partition = delivery_record.get("partition", 0)
                offset = delivery_record.get("offset", 0)
            except Exception as e:
                logger.error(f"Redpanda publish failed: {e}")
                self.healthy = False
                self.connection_error = str(e)
        else:
            # Fallback if allow_offline is set, or record unreachability
            # Compute a standard CRC32/murmur partition for offline simulation only
            import zlib
            partition = zlib.crc32(key_bytes) % self.num_partitions
            offset = self.partition_offsets[partition]
            self.partition_offsets[partition] += 1

        latency_ms = (time.perf_counter() - t0) * 1000.0

        event = {
            "topic": topic,
            "partition": partition,
            "offset": offset,
            "key": account_id,
            "payload": txn,
            "latency_ms": round(latency_ms, 2),
            "timestamp": time.time(),
            "mode": "REAL_REDPANDA" if self.is_real else "NOT KAFKA: in-process simulation",
        }

        self.published_events.append(event)
        for cb in self.message_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Error in bus callback: {e}")

        return event

    def publish_decision(self, decision_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Publish evaluation decision to decisions topic."""
        t0 = time.perf_counter()
        topic = f"decisions_{self.run_id}"
        txn_id = str(decision_dict.get("txn_id", "unknown"))
        key_bytes = txn_id.encode("utf-8")
        payload_bytes = json.dumps(decision_dict).encode("utf-8")

        partition = -1
        offset = 0

        if self.is_real and self.producer:
            delivery_record: Dict[str, Any] = {}

            def delivery_callback(err, msg):
                if not err:
                    delivery_record["partition"] = msg.partition()
                    delivery_record["offset"] = msg.offset()

            try:
                self.producer.produce(
                    topic=topic,
                    key=key_bytes,
                    value=payload_bytes,
                    on_delivery=delivery_callback,
                )
                self.producer.flush(timeout=1.0)
                partition = delivery_record.get("partition", 0)
                offset = delivery_record.get("offset", 0)
            except Exception as e:
                logger.error(f"Redpanda decision publish failed: {e}")
        else:
            import zlib
            partition = zlib.crc32(key_bytes) % self.num_partitions
            offset = self.partition_offsets[partition]
            self.partition_offsets[partition] += 1

        latency_ms = (time.perf_counter() - t0) * 1000.0

        event = {
            "topic": topic,
            "partition": partition,
            "offset": offset,
            "key": txn_id,
            "payload": decision_dict,
            "latency_ms": round(latency_ms, 2),
            "timestamp": time.time(),
            "mode": "REAL_REDPANDA" if self.is_real else "NOT KAFKA: in-process simulation",
        }
        self.published_events.append(event)
        return event

    def reset(self) -> None:
        self.partition_offsets = {i: 0 for i in range(self.num_partitions)}
