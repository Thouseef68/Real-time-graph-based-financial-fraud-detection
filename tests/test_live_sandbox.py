"""Phase 12: Live Sandbox Bank Integration & Multi-Client Tests.

Verifies:
1. Multi-client fan-in and pass-through detection with small cohort (5 simulated clients).
2. Clean participant making legitimate transfers is NEVER blocked.
3. Idempotency prevents duplicate ledger deductions.
4. Rate limiting intercepts rapid bursts.
5. Compressed time abstraction preserves point-in-time step calculations.
6. Zero residue left after room wipe.
7. p95 transfer latency recorded.
"""

import asyncio
import time
import uuid
import pytest
import numpy as np

from fraudengine.graph.engine import GraphEngine
from fraudengine.live.clock import CompressedClock
from fraudengine.live.manager import LiveSandboxManager
from fraudengine.scoring.core import Scorer


@pytest.fixture(scope="module")
def live_stack():
    graph_engine = GraphEngine(neo4j_uri=None)
    scorer = Scorer(
        model_path="models_v2/v2.0.0",
        graph_engine=graph_engine,
        model_version="2.0.0",
    )
    manager = LiveSandboxManager(scorer=scorer, graph_engine=graph_engine)
    return manager


def test_compressed_clock_point_in_time():
    """Verify time compression scale factor maps real time to simulated steps accurately."""
    mock_wall_time = 1000.0
    clock = CompressedClock(
        scale_factor=60.0,
        base_sim_step=700,
        start_wall_time=1000.0,
        time_provider=lambda: mock_wall_time,
    )

    # At 0 wall seconds
    assert clock.base_sim_step == 700
    assert clock.current_step == 700

    # Advance 60 real seconds (= 3600 simulated seconds = 1 simulated hour = 1 step)
    mock_wall_time = 1060.0
    assert clock.simulated_seconds_elapsed == 3600.0
    assert clock.current_step == 701


def test_multi_client_fan_in_and_layering_detection(live_stack):
    """Test 5 clients: 3 victims pay Mule A (fan-in), Mule A hops to Mule B (pass-through).

    Confirms:
    - Normal user sending payments is NEVER blocked.
    - Mule ring triggers REVIEW/BLOCK.
    - Graph containment isolates peers.
    """
    manager = live_stack
    room_code = f"TEST_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code, scale_factor=60.0)

    # 1. Register 5 audience clients + 1 normal neighbor
    vic1 = room.add_participant("Victim One", "DEV_VIC_1", "Mobile Safari", "192.168.1.101", "Campus-WiFi")
    vic2 = room.add_participant("Victim Two", "DEV_VIC_2", "Chrome Android", "192.168.1.102", "Campus-WiFi")
    vic3 = room.add_participant("Victim Three", "DEV_VIC_3", "Mobile Safari", "192.168.1.103", "Campus-WiFi")
    mule_a = room.add_participant("Mule A", "DEV_MULE_A", "Firefox Android", "192.168.1.104", "Cellular-Jio")
    mule_b = room.add_participant("Mule B", "DEV_MULE_B", "Chrome Desktop", "192.168.1.105", "Cellular-Jio")
    normal = room.add_participant("Normal Dave", "DEV_NORM", "Samsung Browser", "192.168.1.106", "Campus-WiFi")

    # 2. Normal customer buys coffee from Campus Mart
    norm_res = manager.execute_transfer(
        room_code=room_code,
        sender_id=normal.account_id,
        receiver_id="BOT_MERCHANT_CAMPUS_MART",
        amount=250.0,
        note="Coffee & sandwich",
    )
    assert norm_res["status"] == "PROCESSED", f"Normal transfer should be processed, got {norm_res}"
    assert norm_res["tier"] == "ALLOW"
    assert normal.balance == 9750.0

    # 3. Victims 1, 2, 3 each transfer ₹2,000 to Mule A (Fan-In accumulation)
    for vic, amt in [(vic1, 2000.0), (vic2, 2000.0), (vic3, 2000.0)]:
        v_res = manager.execute_transfer(
            room_code=room_code,
            sender_id=vic.account_id,
            receiver_id=mule_a.account_id,
            amount=amt,
            note="Urgent invoice deposit",
        )
        assert v_res["status"] in ("PROCESSED", "HELD"), f"Victim transfer failed: {v_res}"

    # Verify Mule A accumulated virtual funds (starting 10k + 4k processed, with 3rd txn held in review)
    assert mule_a.balance >= 14000.0

    # 4. Mule A forwards ₹5,500 immediately to Mule B (Pass-Through layering)
    hop_res = manager.execute_transfer(
        room_code=room_code,
        sender_id=mule_a.account_id,
        receiver_id=mule_b.account_id,
        amount=5500.0,
        note="Forwarding funds",
    )

    # Under demo sensitivity profile, pass-through >= 70% triggers BLOCK
    assert hop_res["tier"] == "BLOCK", f"Expected BLOCK on pass-through hop, got {hop_res['tier']}"
    assert hop_res["status"] == "DECLINED"

    # 5. Verify containment was executed
    assert manager.redis_store.is_account_blocked(mule_a.account_id)
    # Linked peer Mule B sharing Cellular network or payee edge should be held
    assert manager.redis_store.is_account_held(mule_b.account_id) or manager.redis_store.is_account_held(mule_a.account_id)

    # 6. Verify Normal Customer was NEVER blocked
    assert not manager.redis_store.is_account_blocked(normal.account_id)
    assert not manager.redis_store.is_account_held(normal.account_id)

    # 7. Post-block transfer from Mule A declined in < 1ms by pre-score filter
    start = time.perf_counter()
    post_block = manager.execute_transfer(
        room_code=room_code,
        sender_id=mule_a.account_id,
        receiver_id="BOT_MERCHANT_CAMPUS_MART",
        amount=100.0,
    )
    pre_check_latency_ms = (time.perf_counter() - start) * 1000.0
    assert post_block["status"] == "DECLINED"
    assert post_block["tier"] == "BLOCK"
    assert "Pre-Score" in post_block["reason"]
    assert pre_check_latency_ms < 5.0  # Well under 5ms (usually < 0.1ms)

    # Wipe room
    manager.wipe_room(room_code)


def test_idempotency_prevention(live_stack):
    """Verify duplicate transfers with the same idempotency key are not charged twice."""
    manager = live_stack
    room_code = f"IDEM_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code)
    u1 = room.add_participant("Sender", "DEV_S", "UA", "127.0.0.1")
    u2 = room.add_participant("Receiver", "DEV_R", "UA", "127.0.0.1")

    idemp_key = f"IDEMP_{uuid.uuid4().hex}"

    # First attempt
    res1 = manager.execute_transfer(
        room_code=room_code,
        sender_id=u1.account_id,
        receiver_id=u2.account_id,
        amount=1000.0,
        idempotency_key=idemp_key,
    )
    assert res1["status"] == "PROCESSED"
    bal_after_first = u1.balance
    assert bal_after_first == 9000.0

    # Second duplicate attempt with identical key
    res2 = manager.execute_transfer(
        room_code=room_code,
        sender_id=u1.account_id,
        receiver_id=u2.account_id,
        amount=1000.0,
        idempotency_key=idemp_key,
    )
    # Balance must remain unchanged
    assert u1.balance == bal_after_first
    assert res2["txn_id"] == res1["txn_id"]

    manager.wipe_room(room_code)


def test_rate_limiting(live_stack):
    """Verify rapid transfer spam is intercepted by rate limiter."""
    manager = live_stack
    room_code = f"RL_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code)
    u1 = room.add_participant("Spammer", "DEV_SPAM", "UA", "127.0.0.1")
    u2 = room.add_participant("Recipient", "DEV_REC", "UA", "127.0.0.1")

    # Send 5 allowed transfers
    for _ in range(5):
        manager.execute_transfer(
            room_code=room_code,
            sender_id=u1.account_id,
            receiver_id=u2.account_id,
            amount=50.0,
        )

    # 6th immediate transfer must be rate limited
    res6 = manager.execute_transfer(
        room_code=room_code,
        sender_id=u1.account_id,
        receiver_id=u2.account_id,
        amount=50.0,
    )
    assert res6["status"] == "DECLINED"
    assert res6["error_code"] == "RATE_LIMITED"

    manager.wipe_room(room_code)


def test_zero_residue_room_wipe(live_stack):
    """Verify room wipe leaves zero residue in Redis and internal state."""
    manager = live_stack
    room_code = f"WIPE_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code)
    u = room.add_participant("Temp User", "DEV_TEMP", "UA", "127.0.0.1")

    manager.execute_transfer(
        room_code=room_code,
        sender_id=u.account_id,
        receiver_id="BOT_MERCHANT_CAMPUS_MART",
        amount=500.0,
    )

    # Wipe room
    wipe_success = manager.wipe_room(room_code)
    assert wipe_success

    # Verify room is removed
    assert manager.get_room(room_code) is None

    # Verify redis store keys under live:sandbox: are completely empty
    remaining_keys = manager.redis_store.get_all_keys()
    assert len(remaining_keys) == 0, f"Expected 0 residue keys, found {remaining_keys}"


def test_transfer_latency_benchmark(live_stack):
    """Benchmark p95 latency of /live/transfer pipeline across 20 transfers."""
    manager = live_stack
    room_code = f"PERF_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code)
    u1 = room.add_participant("P1", "DEV_P1", "UA", "127.0.0.1")
    u2 = room.add_participant("P2", "DEV_P2", "UA", "127.0.0.1")

    latencies = []
    for i in range(20):
        t0 = time.perf_counter()
        res = manager.execute_transfer(
            room_code=room_code,
            sender_id=u1.account_id,
            receiver_id=u2.account_id,
            amount=10.0,
        )
        t_el = (time.perf_counter() - t0) * 1000.0
        latencies.append(t_el)

    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    print(f"\n[Live Sandbox Benchmark] p50: {p50:.2f} ms | p95: {p95:.2f} ms across 20 transfers")

    assert p95 < 50.0, f"p95 latency {p95:.2f} ms exceeded 50ms SLA"
    manager.wipe_room(room_code)


def test_role_labels_never_input_to_scoring(live_stack):
    """Confirm mathematically and architecturally that role labels are never inputs to scoring."""
    manager = live_stack

    # 1. Inspect model metadata: 41 features, zero mention of role
    feature_names = getattr(manager.scorer, "feature_names", [])
    assert len(feature_names) == 41, f"Expected 41 features, got {len(feature_names)}"
    for f in feature_names:
        assert "role" not in f.lower(), f"Feature '{f}' contains 'role' - violates separation!"

    # 2. Test identical transactions with different role cards
    room_code = f"ROLE_{uuid.uuid4().hex[:4].upper()}"
    room = manager.create_room(room_code=room_code)
    mule_acc = room.add_participant("MuleUser", "DEV_MULE", "UA", "127.0.0.1")
    # Explicitly set role card on mule
    mule_acc.role_card = {
        "role_id": "MULE_LEADER",
        "title": "Mule Ring Leader",
        "badge": "Ring Leader",
        "instructions": "Accumulate funds",
    }

    clean_acc = room.add_participant("CleanUser", "DEV_CLEAN", "UA", "127.0.0.1")
    # Clean user has no role card
    clean_acc.role_card = None

    # Execute transfer for both
    res_mule = manager.execute_transfer(
        room_code=room_code,
        sender_id=mule_acc.account_id,
        receiver_id="BOT_MERCHANT_CAMPUS_MART",
        amount=100.0,
    )
    res_clean = manager.execute_transfer(
        room_code=room_code,
        sender_id=clean_acc.account_id,
        receiver_id="BOT_MERCHANT_CAMPUS_MART",
        amount=100.0,
    )

    # Check scores recorded in internal engine decision ledger
    score_mule = room.transfers[-2]["score"]
    score_clean = room.transfers[-1]["score"]
    assert abs(score_mule - score_clean) < 1e-4, f"Role label leaked into score! {score_mule} vs {score_clean}"
    assert res_mule["tier"] == res_clean["tier"] == "ALLOW"
    manager.wipe_room(room_code)
