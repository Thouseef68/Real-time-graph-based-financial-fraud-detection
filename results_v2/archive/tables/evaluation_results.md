# Evaluation Results

## Overall Model Comparison

| Model | PR-AUC | 95% CI | ROC-AUC | Recall@1% | Recall@0.5% | P@R=0.8 | P@R=0.9 | HN-FPR |
|-------|--------|--------|---------|-----------|-------------|---------|---------|--------|
| rule_drain_only | 0.4852 | [0.204, 0.5007] | 0.7812 | 0.7978 | 0.7978 | 0.2513 | 0.2513 | 0.0000 |
| logistic_regression | 0.7228 | [0.6692, 0.8906] | 0.9056 | 0.0373 | 0.0295 | 0.6757 | 0.5315 | 0.7839 |
| xgb_drain_only | 0.9976 | [0.7369, 0.9994] | 0.9986 | 0.0767 | 0.0767 | 1.0000 | 0.9854 | 0.4556 |
| xgb_all_no_anomaly | 1.0000 | [0.9992, 1.0] | 1.0000 | 0.0394 | 0.0394 | 1.0000 | 1.0000 | 0.1189 |
| v2_xgboost_tuned | 0.9996 | [0.9971, 0.9996] | 0.9997 | 0.9891 | 0.9891 | 1.0000 | 1.0000 | 0.0335 |


## Per-Scenario Results (v2_xgboost_tuned)

| Scenario | N | N_Fraud | PR-AUC | Recall@1% | P@R=0.8 |
|----------|---|---------|--------|-----------|---------|
| bill_payment_burst | 25 | 0 | N/A | N/A | N/A |
| burst_takeover | 162 | 162 | N/A | N/A | N/A |
| dormant_reactivation | 4 | 4 | N/A | N/A | N/A |
| household_shared_device | 68 | 0 | N/A | N/A | N/A |
| large_legitimate_drain | 4 | 0 | N/A | N/A | N/A |
| merchant_high_fanin | 300 | 0 | N/A | N/A | N/A |
| mule_fanin_fanout | 77 | 7 | 0.8500 | 0.4286 | 0.7000 |
| payroll | 200 | 0 | N/A | N/A | N/A |
| paysim_native | 6680 | 1600 | 0.9995 | 0.9988 | 1.0000 |
| shared_device_ring | 132 | 132 | N/A | N/A | N/A |
| structuring | 24 | 24 | N/A | N/A | N/A |