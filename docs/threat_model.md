# Threat Model: Real-Time Financial Fraud Detection Engine

## 1. System Overview & Scope
This threat model assesses the security, robustness, and adversarial resilience of the **Real-Time Graph & Anomaly-Based Financial Fraud Detection Engine**. The system scores incoming financial transactions in real-time (<10ms budget), leveraging point-in-time streaming feature stores, temporal bipartite transaction graphs, unsupervised anomaly detectors (IsolationForest + PyTorch Autoencoder), and a calibrated gradient-boosted decision tree (XGBoost).

---

## 2. Adversary Personas & Capabilities

| Threat Actor | Motivations | Capabilities & Access | Primary Target Scenarios |
| :--- | :--- | :--- | :--- |
| **Opportunistic Fraudster** | Immediate monetary extraction | Single or small batch synthetic identity accounts, stolen credentials, automated scripts | Account Takeover (ATO), Rapid Exhaustion, Velocity bursts |
| **Organised Cybercrime Syndicate** | Large-scale coordinated extraction, money laundering | Botnets, residential proxies, mule account rings, smurfing networks, slow-and-low evasion | Dispersal / Mule Fans, Smurfing / Structuring, Cyclic Laundering |
| **Malicious Insider / Compromised Analyst** | Data leakage, fraud collusion, alert suppression | Read/write access to Analyst Review Queue, Label Store, or Rule configurations | Suppressing REVIEW alerts, falsifying ground truth labels |
| **External Adversary (API Eavesdropper/Injector)** | Denial of service, replay attacks, score tampering | Intercepting unauthenticated API traffic, replaying recorded payloads | Replay attacks, resource exhaustion, auth bypass |

---

## 3. Attack Vectors & Threat Analysis

### 3.1. Adversarial Evasion & Manipulation

#### Threat A: Structuring & Smurfing (Threshold Evasion)
- **Vector**: Adversaries break large illicit transfers into micro-transactions strictly below known regulatory threshold limits ($10,000 / $50,000) or system alert thresholds.
- **Engine Defense**:
  - Point-in-time cumulative velocity aggregations (`sum_1h`, `sum_6h`, `sum_24h`, `count_24h`).
  - Graph-level fan-in and fan-out metrics (`payee_fan_in_24h`, `payee_outflow_inflow_ratio_24h`).
  - Smurfing rule `R10_SMURFING_BURST`: triggers `REVIEW` if transaction count across distinct sources reaches structuring thresholds even when individual amounts are small.

#### Threat B: "Slow and Low" Evasion
- **Vector**: Fraudsters space out malicious transfers over multiple days or weeks to evade rolling 1-hour and 6-hour velocity windows.
- **Engine Defense**:
  - Behavioural z-score features (`amount_zscore`, `dormancy_days`, `hour_deviation`) capturing shifts from an account's historical baseline.
  - Multi-scale velocity windows (1h, 6h, 24h).
  - Graph-level PageRank and 2-hop fraud exposure scores (`fraud_exposure_2hop`) which accumulate risk regardless of transfer speed.

#### Threat C: Mule Network & Layering (Cyclic Graphs)
- **Vector**: Fraudulent funds pass through multiple intermediate intermediary accounts (mules) to decouple the beneficiary from the source.
- **Engine Defense**:
  - Bounded temporal NetworkX graph tracking directional cash flows across a 24-hour window.
  - Instant cycle detection algorithm (`detect_cycles_directed`) detecting closed flow topologies of length 3-5 within milliseconds.
  - Payee pass-through velocity flag (`payee_pass_through_flag`) detecting rapid re-transfers where inflow ≈ outflow within 1 hour.

---

### 4. System Vulnerabilities & Mitigation Strategies

### 4.1. Label Delay & Feedback Poisoning
- **Vulnerability**: Confirmed fraud feedback suffers from severe real-world latency (24 to 72+ hours between transaction execution and chargeback filing). If an adversary can influence analyst resolution or if unlabelled fraudulent transactions are assumed to be legitimate during rolling retraining, models experience label noise and feedback poisoning.
- **Mitigation**:
  - **Grace Period Partitioning**: Retraining candidate windows strictly exclude recent transactions within the 72-hour unconfirmed window.
  - **Champion-Challenger Gate**: Challenger models must prove non-inferior PR-AUC and cost efficiency on held-out out-of-time validation sets with calibrated confidence intervals before promotion.
  - **Audit Logging**: Every analyst action (`CONFIRM_FRAUD`, `DISMISS_ALERT`, `ESCALATE`) is cryptographically recorded with operator ID, reason code, and timestamp in an immutable SHA-256 hash-chained audit log.

### 4.2. Memory Exhaustion & State Poisoning (Resource Starvation)
- **Vulnerability**: Massive volumes of high-cardinality synthetic accounts can exhaust RAM in stateful graph and sliding-window feature stores.
- **Mitigation**:
  - **Bounded LRU Eviction**: In-memory stores (`InMemoryFeatureStore`, `GraphEngine`) enforce strict capacity boundaries using `collections.OrderedDict` (capped at 35,000-40,000 active accounts).
  - **24-Hour Edge Pruning**: Graph edges and temporal events older than 24 hours are pruned synchronously during step updates, bounding active RAM to <500 MB.

### 4.3. Concept & Covariate Drift
- **Vulnerability**: Consumer purchasing patterns change seasonally or abruptly (e.g., Black Friday, economic shifts), degrading static classifier performance.
- **Mitigation**:
  - Continuous feature-level and score-level Population Stability Index (PSI) monitoring.
  - Automatic drift alerting when $PSI > 0.20$.
  - Periodic model retraining on a rolling 30-day window with champion/challenger validation.

---

### 5. Cryptographic & Data Integrity Guarantees

1. **SHA-256 Hash Chained Audit Log**:
   - Every scored transaction and analyst decision generates a canonical JSON record.
   - Each entry contains `prev_hash`, creating a tamper-evident cryptographic hash chain. Any retrofitted tampering invalidates the chain verification.
2. **Role-Based Access Control (RBAC)**:
   - JWT tokens with HMAC-SHA256 signatures enforce strict role separation (`analyst` vs `admin`).
   - Administrative endpoints (model retraining, threshold calibration, rule updates) require the `admin` role.
3. **Data Privacy & Masking**:
   - Personal Identifiable Information (PII) is not stored in plaintext; account identifiers follow deterministic pseudonymous hashing.
