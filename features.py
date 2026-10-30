# features.py
# Shared by train.py and scorer.py so the model sees identical features in both.
import pandas as pd

WINDOW_HOURS = 24  # PaySim step = 1 hour, so this is a 24-hour window

TYPE_CODES = {"CASH_IN": 0, "CASH_OUT": 1, "DEBIT": 2, "PAYMENT": 3, "TRANSFER": 4}

FEATURES = [
    "amount",
    "type_code",
    "amount_to_balance",
    "orig_drained",
    "amount_vs_sum_24h",
    "count_24h",
    "sum_24h",
    "distinct_payees_24h",
]


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Expects amount, txn_type, old_balance_orig, new_balance_orig,
    count_24h, sum_24h, distinct_payees_24h. Returns a copy with FEATURES."""
    df = df.copy()
    # Convert categorical to string first, then map
    type_str = df["txn_type"].astype(str)
    df["type_code"] = type_str.map(TYPE_CODES).fillna(-1).astype(int)
    df["amount_to_balance"] = df["amount"] / (df["old_balance_orig"] + 1.0)
    df["orig_drained"] = (
        (df["old_balance_orig"] > 0) & (df["new_balance_orig"] == 0)
    ).astype(int)
    df["amount_vs_sum_24h"] = df["amount"] / (df["sum_24h"] + 1.0)
    return df