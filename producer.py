import json
import random
import time
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer

TOPIC = "transactions"
producer = Producer({"bootstrap.servers": "localhost:9092"})


def delivery_report(err, msg):
    if err is not None:
        print(f"Delivery failed: {err}")


def make_transaction():
    return {
        "txn_id": str(uuid.uuid4()),
        "account_id": f"ACC{random.randint(1, 500):05d}",
        "payee_id": f"PAY{random.randint(1, 200):04d}",
        "amount": round(random.lognormvariate(4, 1), 2),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    try:
        while True:
            txn = make_transaction()
            producer.produce(
                TOPIC,
                key=txn["account_id"],
                value=json.dumps(txn),
                callback=delivery_report,
            )
            producer.poll(0)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        producer.flush()
        print("Producer stopped.")