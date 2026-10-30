# inject_burst.py
# Injects synthetic burst-fraud into the held-out test split:
# - Pick N mule payee accounts
# - For each, select K victim originator accounts
# - Each victim makes M small transfers to the mule within a short window
# This creates velocity signals (high count_24h, high distinct_payees_24h)
# that the drain features won't catch (amounts are small, balance not drained).
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

DATA = "data/PS_20174392719_1491204439457_log.csv"
OUT = "data/PS_20174392719_1491204439457_log_with_bursts.csv"
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Burst parameters
N_MULES = 50          # number of mule payee accounts
K_VICTIMS_PER_MULE = 20   # victims per mule
M_TXNS_PER_VICTIM = 5     # transfers per victim
BURST_WINDOW_HOURS = 6    # all transfers within this window
BURST_START_STEP = 610    # step to start bursts (within held-out period)
TXN_TYPE = "TRANSFER"
AMOUNT_RANGE = (10.0, 100.0)  # small amounts, won't drain balance


def load_original() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    return df


def inject_bursts(df: pd.DataFrame) -> pd.DataFrame:
    # Get accounts that exist in the held-out period (step > 600)
    held_out = df[df.step > 600].copy()
    if len(held_out) == 0:
        raise ValueError("No held-out data")

    # Pick mule payees from existing payees in held-out
    mule_candidates = held_out.nameDest.unique()
    if len(mule_candidates) < N_MULES:
        raise ValueError("Not enough mule candidates")
    mules = pd.Series(mule_candidates).sample(N_MULES, random_state=42).values

    # Pick victim originators from existing originators in held-out
    victim_candidates = held_out.nameOrig.unique()
    total_victims_needed = N_MULES * K_VICTIMS_PER_MULE
    if len(victim_candidates) < total_victims_needed:
        raise ValueError("Not enough victim candidates")
    victims = pd.Series(victim_candidates).sample(total_victims_needed, random_state=43).values

    new_rows = []
    base_step = BURST_START_STEP

    for mi, mule in enumerate(mules):
        mule_victims = victims[mi * K_VICTIMS_PER_MULE:(mi + 1) * K_VICTIMS_PER_MULE]
        for vi, victim in enumerate(mule_victims):
            # Get victim's balance info from their last transaction
            victim_tx = held_out[held_out.nameOrig == victim].sort_values('step').iloc[-1]
            old_bal = victim_tx.oldbalanceOrg
            new_bal = victim_tx.newbalanceOrig

            for tx_i in range(M_TXNS_PER_VICTIM):
                step = base_step + (tx_i * BURST_WINDOW_HOURS // M_TXNS_PER_VICTIM)
                amount = round(
                    AMOUNT_RANGE[0] + (AMOUNT_RANGE[1] - AMOUNT_RANGE[0]) * (tx_i / M_TXNS_PER_VICTIM), 2
                )
                new_row = {
                    "step": step,
                    "type": TXN_TYPE,
                    "amount": amount,
                    "nameOrig": victim,
                    "oldbalanceOrg": old_bal,
                    "newbalanceOrig": max(0, old_bal - amount),
                    "nameDest": mule,
                    "oldbalanceDest": 0.0,
                    "newbalanceDest": 0.0,
                    "isFraud": 1,
                    "isFlaggedFraud": 0,
                }
                new_rows.append(new_row)
                old_bal = new_row["newbalanceOrig"]

    burst_df = pd.DataFrame(new_rows)
    print(f"Injected {len(burst_df):,} burst transactions ({N_MULES} mules × {K_VICTIMS_PER_MULE} victims × {M_TXNS_PER_VICTIM} txns)")

    # Combine and sort
    combined = pd.concat([df, burst_df], ignore_index=True)
    combined = combined.sort_values(["step", "type"]).reset_index(drop=True)
    return combined


def main():
    print("Loading original data...")
    df = load_original()
    print(f"Original: {len(df):,} rows")

    print("Injecting bursts...")
    df = inject_bursts(df)
    print(f"With bursts: {len(df):,} rows")

    print(f"Saving to {OUT}...")
    df.to_csv(OUT, index=False)
    print("Done.")

    # Quick stats
    fraud_rate = df.isFraud.mean()
    burst_fraud = df[df.step >= BURST_START_STEP].isFraud.sum()
    print(f"Overall fraud rate: {fraud_rate:.4%}")
    print(f"Burst fraud count: {burst_fraud:,}")


if __name__ == "__main__":
    main()