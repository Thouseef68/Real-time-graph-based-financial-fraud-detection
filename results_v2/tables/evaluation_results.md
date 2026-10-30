# Evaluation Results

## Overall Model Comparison

| Model | PR-AUC | 95% CI | ROC-AUC | Recall@1% | Recall@0.5% | P@R=0.8 | P@R=0.9 | HN-FPR |
|-------|--------|--------|---------|-----------|-------------|---------|---------|--------|
| rule_drain_only | 0.0484 | [0.0467, 0.4348] | 0.7621 | 0.0658 | 0.0530 | 0.0186 | 0.0186 | 0.0000 |
| logistic_regression | 0.1764 | [0.1444, 0.9445] | 0.9267 | 0.1825 | 0.0972 | 0.1340 | 0.0769 | 0.2156 |
| xgb_drain_only | 0.9947 | [0.7627, 0.9972] | 0.9998 | 0.5378 | 0.2689 | 1.0000 | 0.9793 | 0.4431 |
| xgb_all_no_anomaly | 0.9996 | [0.9949, 0.9998] | 1.0000 | 0.5378 | 0.2689 | 1.0000 | 1.0000 | 0.0917 |
| v2_xgboost_tuned | 0.9990 | [0.9892, 0.9998] | 1.0000 | 0.5378 | 0.2689 | 0.9995 | 0.9995 | 0.0153 |


## Per-Scenario Results (v2_xgboost_tuned)

| Scenario | N | N_Fraud | PR-AUC | Recall@1% | P@R=0.8 |
|----------|---|---------|--------|-----------|---------|
| bill_payment_burst | 25 | 0 | N/A | N/A | N/A |
| burst_takeover | 163 | 163 | N/A | N/A | N/A |
| dormant_reactivation | 4 | 4 | N/A | N/A | N/A |
| household_shared_device | 60 | 0 | N/A | N/A | N/A |
| large_legitimate_drain | 4 | 0 | N/A | N/A | N/A |
| merchant_high_fanin | 300 | 0 | N/A | N/A | N/A |
| mule_fanin_fanout | 144 | 28 | 0.9929 | 0.0357 | 1.0000 |
| payroll | 200 | 0 | N/A | N/A | N/A |
| paysim_native | 103573 | 1600 | 1.0000 | 0.6469 | 1.0000 |
| shared_device_ring | 126 | 126 | N/A | N/A | N/A |
| structuring | 24 | 24 | N/A | N/A | N/A |