"""Kafka consumer/producer wrapper for the Scorer."""
from typing import Any, Dict, List, Optional, Callable
import json
import os
import signal
import sys

from confluent_kafka import Consumer, Producer, KafkaError

from fraudengine.scoring.core import Scorer, Decision
from fraudengine.config import config


class KafkaScorer:
    """Kafka wrapper around the Scorer."""

    def __init__(self, scorer: Scorer, run_id: str = None,
                 consumer_group: str = None, auto_commit: bool = False):
        self.scorer = scorer
        self.run_id = run_id or os.getenv("RUN_ID", "local")
        kafka_cfg = config.load("kafka_config")
        self.bootstrap_servers = kafka_cfg["kafka"]["bootstrap_servers"]
        self.in_topic = f"{kafka_cfg['kafka']['topics']['transactions']}_{self.run_id}"
        self.out_topic = f"{kafka_cfg['kafka']['topics']['decisions']}_{self.run_id}"
        self.consumer_group = consumer_group or f"{kafka_cfg['kafka']['consumer_group_prefix']}_{self.run_id}"

        self.consumer = Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.consumer_group,
            "auto.offset.reset": kafka_cfg["kafka"]["auto_offset_reset"],
            "enable.auto.commit": auto_commit,
        })
        self.consumer.subscribe([self.in_topic])

        self.producer = Producer({
            "bootstrap.servers": self.bootstrap_servers,
            "linger.ms": kafka_cfg["kafka"]["producer_linger_ms"],
        })

        self._running = False
        self._delivery_callback = self._default_delivery_callback

    def _default_delivery_callback(self, err, msg):
        if err is not None:
            print(f"Decision delivery failed: {err}")

    def set_delivery_callback(self, callback: Callable):
        """Set custom delivery callback."""
        self._delivery_callback = callback

    def run(self, max_messages: int = None, poll_timeout: float = 1.0) -> int:
        """Run the scoring loop."""
        self._running = True
        processed = 0

        def signal_handler(sig, frame):
            self._running = False
            print("Shutdown signal received...")

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print(f"KafkaScorer running: {self.in_topic} -> {self.out_topic}")
        print(f"Consumer group: {self.consumer_group}")

        try:
            while self._running and (max_messages is None or processed < max_messages):
                msg = self.consumer.poll(poll_timeout)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        print(f"Consumer error: {msg.error()}")
                    continue

                try:
                    txn = json.loads(msg.value())
                    # Schema validation
                    required = ["txn_id", "account_id", "payee_id", "amount", "ts", "step", "txn_type"]
                    for field in required:
                        if field not in txn:
                            raise ValueError(f"Missing field: {field}")
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"Skipping malformed message: {e}")
                    if not auto_commit:
                        self.consumer.commit(message=msg, asynchronous=False)
                    continue

                decision = self.scorer.score(txn)

                # Produce decision
                self.producer.produce(
                    self.out_topic,
                    key=txn["account_id"],
                    value=json.dumps(decision.to_dict()),
                    callback=self._delivery_callback
                )
                self.producer.poll(0)

                if not auto_commit:
                    self.consumer.commit(message=msg, asynchronous=False)

                if decision.tier != "ALLOW":
                    print(f"{decision.tier:8} {txn['account_id']} score={decision.score:.4f} "
                          f"summary={decision.summary}")

                processed += 1

        except KeyboardInterrupt:
            pass
        finally:
            self.producer.flush()
            self.consumer.close()
            print(f"Processed {processed} transactions.")

        return processed

    def close(self) -> None:
        """Close connections."""
        self.scorer.close()
        self.producer.flush()
        self.consumer.close()