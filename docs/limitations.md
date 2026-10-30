# Engineering & Algorithmic Limitations

This document details known limitations, architectural trade-offs, and operational boundaries of the **Real-Time Financial Fraud Detection Engine (v2.0)**.

---

## 1. Graph State Eviction & Long-Range Memory Trade-offs

### 1.1. Bounded Memory (LRU Eviction)
- **Constraint**: To operate reliably within memory budgets (<1 GB RAM) under high event volumes (6.3+ million transactions), the `InMemoryFeatureStore` and `GraphEngine` utilize an LRU cache bounded to 35,000–40,000 active accounts with synchronous 24-hour temporal edge pruning.
- **Consequence**: Fraud rings that intentionally space their layering hops beyond 24 to 48 hours ("ultra-slow and low" laundering) will have their early edges evicted from the active graph. 
- **Mitigation**: Long-term behavioural aggregates (`dormancy_days`, account creation timestamp, historical lifetime transaction counts) persist in persistent key-value storage or feature stores independently of the transient 24-hour graph topology.

### 1.2. In-Memory Graph vs Distributed Graph Databases
- **Constraint**: The current engine defaults to an in-memory `networkx.DiGraph` engine optimized for sub-millisecond local 2-hop subgraphs and cycle detection.
- **Consequence**: Scalability beyond a single process requires externalising the graph to Neo4j or Memgraph. The code includes a drop-in Neo4j connector interface, but network serialization introduces 5–15ms round-trip latency compared to 0.05ms in-memory.

---

## 2. Cold-Start Problem (New Accounts & Devices)

- **Constraint**: Newly registered accounts (age < 24 hours) lack historical baselines for behavioural z-scores (`amount_zscore`, `hour_deviation`).
- **Consequence**: The statistical anomaly detector may under-predict or over-predict risk until baseline velocity is established.
- **Mitigation**:
  - Heuristic safety rules: Rule `R08_NEW_ACCOUNT_HIGH_VALUE` and Rule `R05_DEVICE_HOPPING_BURST` trigger deterministic `STEP_UP` (2FA/OTP) or `REVIEW` thresholds regardless of classifier output.
  - Device/IP clustering features (`accounts_per_device`, `is_new_device`) identify synthetic fraud farms immediately even on brand-new account numbers.

---

## 3. Label Delay & Operational Retraining Windows

- **Constraint**: Ground truth fraud confirmation relies on card network chargebacks or victim disputes, which typically arrive 24 to 72+ hours post-transaction.
- **Consequence**: Models cannot be retrained in true zero-lag real-time; attempting to retrain on the immediate trailing 24 hours induces label noise (false negatives where undetected fraud is misclassified as legitimate).
- **Mitigation**:
  - Champion-Challenger retraining jobs enforce a strict 72-hour exclusion quarantine on training data windows.
  - Drift monitoring (PSI on features and score distributions) alerts operators to concept drift before model retraining is triggered.

---

## 4. Explainability vs Latency Budget

- **Constraint**: Tree SHAP (`shap.TreeExplainer`) calculation across all 41 features takes 15–35ms per transaction on CPU, exceeding the 10ms p95 real-time scoring budget.
- **Consequence**: SHAP values cannot be computed synchronously in the critical path for every single ALLOW transaction.
- **Mitigation**:
  - Real-time scoring path uses deterministic Rule Reason Codes and decision logic (<2ms).
  - High-risk transactions (REVIEW and BLOCK decisions) generate full Case Bundles asynchronously, computing complete SHAP attribution and 2-hop subgraphs for analyst investigation without blocking transaction throughput.
