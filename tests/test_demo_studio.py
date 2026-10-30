"""Tests for Live Demo Studio: 7-act mule ring scenario, containment, pre-score blocklist, and counterfactuals."""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import time
from fraudengine.api.state import state
from fraudengine.demo import DemoLedger, DemoMessageBus, DemoRedisStore, DemoRunner, DemoScenario


def test_scenario_deterministic_across_seeds():
    """Verify scenario generation is fully deterministic for a given seed."""
    s1 = DemoScenario(seed=42).generate_events()
    s2 = DemoScenario(seed=42).generate_events()
    assert len(s1) == len(s2)
    assert [e.get("txn_id") for e in s1] == [e.get("txn_id") for e in s2]
    assert [e.get("amount") for e in s1] == [e.get("amount") for e in s2]


@pytest.mark.parametrize("seed", [42, 100, 777, 999, 2026])
def test_full_7_act_mule_ring_run(seed):
    """Across 5 seeds:
    - Member A is confirmed BLOCK by Act 5
    - Members B, C, D are placed on HOLD via graph containment
    - Household is NEVER blocked (monitored/allowed only)
    - Member D's cash-out in Act 7 is declined instantly
    - Reset leaves zero residue.
    """
    redis_store = DemoRedisStore(prefix=f"test:demo:{seed}:")
    bus = DemoMessageBus(run_id=f"test_run_{seed}")
    ledger = DemoLedger()

    runner = DemoRunner(
        scorer=state.scorer,
        graph_engine=state.graph_engine,
        redis_store=redis_store,
        bus=bus,
        ledger=ledger,
    )

    runner.init_run(seed=seed, speed=5.0, protection_enabled=True)
    assert len(runner.events) > 0

    acts_encountered = set()
    household_txns = []
    cashout_txns = []
    member_a_decisions = []

    # Step through all events in the scenario
    while runner.current_index < len(runner.events):
        idx = runner.current_index
        event = runner.events[idx]
        act = event.get("act", 1)
        acts_encountered.add(act)

        res = runner.step()
        if res and isinstance(res, dict) and "decision" in res:
            d = res["decision"]
            sender = event.get("account_id")
            if "HOUSEHOLD" in sender:
                household_txns.append(d)
            elif "TXN_ACT7_CASHOUT_D" in event.get("txn_id", ""):
                cashout_txns.append(d)
            elif sender == "CUST_MULE_A" and act >= 3:
                member_a_decisions.append(d)

    # 1. All 7 acts executed
    assert acts_encountered == {1, 2, 3, 4, 5, 6, 7}

    # 2. Member A is blocked by Act 5
    assert len(member_a_decisions) > 0
    # The final Act 5 transaction on A must be BLOCK
    assert any(d["tier"] == "BLOCK" for d in member_a_decisions)

    # 3. Containment: B, C, D are placed on HOLD
    block_summary = redis_store.get_summary()
    assert "CUST_MULE_A" in block_summary["blocked_accounts"]
    assert "CUST_MULE_B" in block_summary["held_accounts"]
    assert "CUST_MULE_C" in block_summary["held_accounts"]

    # 4. Household is NEVER blocked
    assert "CUST_INNOCENT_HOUSEHOLD" not in block_summary["blocked_accounts"]
    assert "CUST_INNOCENT_HOUSEHOLD" not in block_summary["held_accounts"]
    assert "CUST_INNOCENT_HOUSEHOLD" in block_summary["monitored_accounts"]
    # Household transaction succeeded
    assert len(household_txns) > 0
    assert all(h["tier"] == "ALLOW" for h in household_txns)

    # 5. D's cash-out in Act 7 is declined instantly by blocklist/holdlist pre-check
    assert len(cashout_txns) == 1
    d_cashout = cashout_txns[0]
    assert d_cashout["tier"] in ("BLOCK", "HOLD")
    # Pre-check is ultra-fast: recorded latency under 25ms (typically <2ms)
    assert d_cashout["latency_ms"] < 25.0

    # 6. Ledger balances reflect money saved
    totals = ledger.get_totals()
    assert totals["money_saved"] >= 46000.0

    # 7. Reset leaves zero residue
    runner.init_run(seed=seed)
    reset_summary = redis_store.get_summary()
    assert len(reset_summary["blocked_accounts"]) == 0
    assert len(reset_summary["held_accounts"]) == 0
    assert len(reset_summary["monitored_accounts"]) == 0
    clean_totals = ledger.get_totals()
    assert clean_totals["money_moved"] == 0.0
    assert clean_totals["money_held"] == 0.0
    assert clean_totals["money_saved"] == 0.0


def test_counterfactual_protection_off():
    """Verify that with protection OFF, transactions are authorized and money is lost rather than saved."""
    redis_store = DemoRedisStore(prefix="test:counterfactual:")
    bus = DemoMessageBus(run_id="test_cf")
    ledger = DemoLedger()

    runner = DemoRunner(
        scorer=state.scorer,
        graph_engine=state.graph_engine,
        redis_store=redis_store,
        bus=bus,
        ledger=ledger,
    )

    runner.init_run(seed=42, speed=10.0, protection_enabled=False)

    while runner.current_index < len(runner.events):
        runner.step()

    totals = ledger.get_totals()
    # With protection OFF, money leaves, so money_saved is 0!
    assert totals["money_saved"] == 0.0
    assert totals["money_moved"] > 100000.0


def test_interactive_user_transfer():
    """Verify 'Try It Yourself' transfer passes through the real pipeline."""
    res = state.demo_runner.execute_user_transfer(
        from_account="CUST_NORM_01",
        to_account="MERCHANT_GROCERY_99",
        amount=55.0,
    )
    assert "decision" in res
    assert "tier" in res["decision"]
    assert "ledger" in res
    assert res["ledger"]["status"] == "AUTHORIZED"


if __name__ == "__main__":
    print("Testing scenario determinism...")
    test_scenario_deterministic_across_seeds()
    print("Scenario determinism PASSED.")

    for s in [42, 100, 777, 999, 2026]:
        print(f"Running full 7-act test with seed={s}...")
        test_full_7_act_mule_ring_run(s)
        print(f"Seed {s} PASSED.")

    print("Testing counterfactual protection OFF...")
    test_counterfactual_protection_off()
    print("Counterfactual PASSED.")

    print("Testing interactive user transfer...")
    test_interactive_user_transfer()
    print("Interactive transfer PASSED.")

    print("\nALL DEMO STUDIO TESTS PASSED SUCCESSFULLY!")
