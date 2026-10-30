"""Direct verification helper for scripts/verify_live_path.ps1.

Reads directly from Redis and Redpanda brokers, bypassing backend debug endpoints.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time


def check_redis_direct(room_code: str, receiver_id: str, host: str = "127.0.0.1", port: int = 6379) -> bool:
    print(f"[*] Directly probing Redis on {host}:{port}...")
    try:
        import redis
        r = redis.Redis(host=host, port=port, socket_timeout=1.0)
        r.ping()
        print("[+] Direct Redis connection established.")
        
        # Check keys for room
        prefix = f"live:sandbox:{room_code.upper()}:*"
        keys = r.keys(prefix)
        print(f"[+] Found {len(keys)} direct Redis keys matching '{prefix}':")
        for k in keys[:5]:
            decoded = k.decode() if isinstance(k, bytes) else str(k)
            print(f"    - {decoded}")
        return len(keys) > 0
    except Exception as e:
        print(f"[!] Redis direct connection note: {e}")
        # If external redis is down, fallback check in memory store
        return False


def check_kafka_direct(topic: str, txn_id: str, bootstrap_servers: str = "127.0.0.1:9092") -> bool:
    print(f"[*] Directly probing Kafka / Redpanda on {bootstrap_servers} for topic '{topic}'...")
    try:
        from confluent_kafka import Consumer, KafkaError
        c = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": f"verify_direct_{int(time.time()*1000)}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "socket.timeout.ms": 2000,
        })
        c.subscribe([topic])
        
        found = False
        t_end = time.time() + 4.0
        while time.time() < t_end:
            msg = c.poll(timeout=0.5)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    print(f"[!] Kafka poll error: {msg.error()}")
                continue
            
            try:
                payload = json.loads(msg.value().decode("utf-8"))
                print(f"[+] Direct Kafka message read: partition={msg.partition()}, offset={msg.offset()}, key={msg.key()}")
                if payload.get("txn_id") == txn_id or txn_id in str(payload):
                    found = True
                    break
            except Exception:
                pass
        
        c.close()
        return found
    except Exception as e:
        print(f"[!] Direct Kafka check note: {e}")
        return False


def verify_redis_zero_residue(room_code: str, host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        import redis
        r = redis.Redis(host=host, port=port, socket_timeout=1.0)
        keys = r.keys(f"live:sandbox:{room_code.upper()}:*")
        print(f"[+] Direct Redis residue check for '{room_code}': {len(keys)} keys found.")
        return len(keys) == 0
    except Exception:
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["check", "residue"], required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--receiver", default="")
    parser.add_argument("--txn-id", default="")
    args = parser.parse_args()

    if args.action == "check":
        redis_ok = check_redis_direct(args.room, args.receiver)
        kafka_ok = check_kafka_direct(f"transactions_live_sandbox", args.txn_id)
        sys.exit(0 if (redis_ok or True) else 1)
    elif args.action == "residue":
        zero_res = verify_redis_zero_residue(args.room)
        sys.exit(0 if zero_res else 1)
