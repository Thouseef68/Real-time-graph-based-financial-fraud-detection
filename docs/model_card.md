# Model Card: Financial Fraud Detection Engine (v2.0.0)

## 1. Model Details

- **Model Name**: Champion Fraud Classifier v2.0.0 (`models_v2/v2.0.0/`)
- **Model Architecture**:
  - **Supervised Classifier**: XGBoost (`XGBClassifier`) with histogram-based split finding (`tree_method='hist'`) and scale-pos-weight imbalance compensation.
  - **Anomaly Stack**: Two-stream unsupervised pipeline:
    - Isolation Forest (40 estimators, contamination=0.01)
    - PyTorch Deep Autoencoder (Linear 12 -> 6 -> 3 -> 6 -> 12, ReLU, Adam, MSE loss)
  - **Calibration Layer**: Non-parametric Isotonic Regression (`sklearn.isotonic.IsotonicRegression(out_of_bounds='clip')`).
- **Feature Set**: 41 engineered point-in-time features spanning:
  - Base transaction attributes (amount, type code, balance delta ratios)
  - Multi-window rolling velocity (1h, 6h, 24h sums, counts, distinct payees)
  - Behavioural deviations (amount z-score, hour deviation, dormancy days)
  - Device/IP network graphs (accounts per device, IP prefix sharing)
  - Bipartite graph metrics (payee fan-in, flow ratio, 2-hop fraud exposure, PageRank)
  - Unsupervised anomaly percentiles (`isolation_forest_score`, `autoencoder_reconstruction_error`)
- **Release Version**: `2.0.0`
- **Trained By**: Automated Pipeline (`fraudengine.models.train_v2`)
- **License**: MIT / Academic Use Only

---

## 2. Intended Use

### 2.1. In-Scope Uses
- Real-time scoring and classification of mobile money and banking transactions.
- Automated multi-tiered decision dispatch:
  - **ALLOW**: Low-risk probability (< step_up threshold).
  - **STEP_UP**: Moderate risk (prompts 2FA, OTP, or biometric challenge).
  - **REVIEW**: Elevated risk routed to human fraud analyst queue with complete Case Bundle and 2-hop subgraph.
  - **BLOCK**: High risk or deterministic safety rule trip (immediate transaction termination).
- Investigator decision-support with SHAP feature attribution and graph cycle analysis.

### 2.2. Out-of-Scope & Misuse
- Scoring non-financial behavioral actions.
- Autonomous account freezing without human-in-the-loop audit logs and appeal channels.
- Deployment in production banking environments without regulatory model risk governance (SR 11-7) validation.

---

## 3. Training & Validation Data

- **Provenance**: Synthetic financial scenario transactions generated from `data/scenarios.parquet` (6,367,603 total events).
- **Split Methodology**: Strict chronological time-based split:
  - **Train**: Steps 1–496 (Days 1–20), 143,217 sampled transactions with 10 fraud scenario typologies.
  - **Validation**: Steps 497–620 (Days 21–25), 8,478 held-out transactions used exclusively for Optuna hyperparameter optimization and probability calibration.
  - **Test**: Steps 621–744 (Days 26–31), 7,676 transactions used for final Phase 5 evaluation benchmarks.
- **Data Leakage Mitigation**: Out-of-fold cross-validation used during anomaly score generation to prevent optimistic stacking bias.

---

## 4. Evaluation Metrics & Performance Benchmarks

*(Metrics cited directly from validated execution artifacts in `models_v2/v2.0.0/metrics.json` and `results_v2/`)*:
- **Optimization Objective**: Held-out Validation PR-AUC (Precision-Recall Area Under Curve).
- **Secondary Metrics**:
  - ROC-AUC
  - Recall at 1.0% operational alert budget
  - Recall at 0.5% operational alert budget
  - Cost curve optimization under business utility parameters ($C_{FP} = \$1.00, C_{FN} = \$10.00$).

---

## 5. Ethical Considerations & Fairness

- **Protected Attributes**: The feature pipeline contains **no demographic, gender, racial, or geographic personal identifiers**. Features are strictly mathematical representations of velocity, account balance deltas, and graph connection topologies.
- **False Positive Friction**: Over-aggressive blocking disproportionately harms low-income or unbanked users with erratic transaction habits. The engine prioritizes `STEP_UP` (friction challenge) over hard `BLOCK` for ambiguous transactions.
- **Auditability**: Every prediction, rule firing, and analyst adjudication is preserved in an immutable, cryptographically chained SHA-256 audit ledger.
