import json

from confluent_kafka import Consumer

consumer = Consumer({
    "bootstrap.servers": "localhost:9092",
    "group.id": "scorer",
    "auto.offset.reset": "earliest",
})
consumer.subscribe(["transactions"])

try:
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"Consumer error: {msg.error()}")
            continue

        txn = json.loads(msg.value())
        print(
            f"partition={msg.partition()} offset={msg.offset()} "
            f"account={msg.key().decode()} amount={txn['amount']}"
        )
except KeyboardInterrupt:
    pass
finally:
    consumer.close()