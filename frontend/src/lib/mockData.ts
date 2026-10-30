export interface AlertItem {
  case_id: string;
  txn_id: string;
  account_id: string;
  tier: "ALLOW" | "STEP_UP" | "REVIEW" | "BLOCK";
  score: number;
  summary: string;
  status: "open" | "approved" | "blocked" | "escalated";
  amount: number;
  scenario?: string;
  group_id?: string;
  created_at: string;
}

export const MOCK_KPIS = {
  total_transactions_scored: 104850,
  total_alerts: 412,
  open_alerts: 28,
  blocked_alerts: 184,
  alert_rate: 0.0039,
  amount_held_or_blocked: 12450000,
  avg_risk_score: 0.842,
  p50_latency_ms: 0.04,
  p95_latency_ms: 0.08,
};

export const MOCK_ALERTS: AlertItem[] = [
  {
    case_id: "case_mule_01",
    txn_id: "TXN_MULE_9921",
    account_id: "C1948201948",
    tier: "BLOCK",
    score: 0.984,
    summary: "Likely mule account: received funds from 22 distinct senders in 24 hours and forwarded 88% onward.",
    status: "open",
    amount: 185000,
    scenario: "mule_fanin_fanout",
    created_at: "2 minutes ago",
  },
  {
    case_id: "case_burst_02",
    txn_id: "TXN_BURST_4412",
    account_id: "C8472910482",
    tier: "BLOCK",
    score: 0.942,
    summary: "Burst account takeover: 14 rapid transfers to new payees from a new mobile device within 90 minutes.",
    status: "open",
    amount: 42000,
    scenario: "burst_takeover",
    created_at: "8 minutes ago",
  },
  {
    case_id: "case_ring_03",
    txn_id: "TXN_RING_8123",
    account_id: "C3928192841",
    tier: "BLOCK",
    score: 0.961,
    summary: "Device sharing ring: 8 active customer accounts transacting circular funds from a single hardware fingerprint.",
    status: "open",
    amount: 98000,
    scenario: "shared_device_ring",
    created_at: "14 minutes ago",
  },
  {
    case_id: "case_struct_04",
    txn_id: "TXN_STRUCT_1049",
    account_id: "C5519283741",
    tier: "REVIEW",
    score: 0.785,
    summary: "Structuring pattern: 4 consecutive transfers of ₹49,200 just below the ₹50,000 regulatory reporting threshold.",
    status: "open",
    amount: 49200,
    scenario: "structuring",
    created_at: "22 minutes ago",
  },
  {
    case_id: "case_dorm_05",
    txn_id: "TXN_DORM_7721",
    account_id: "C1049281742",
    tier: "REVIEW",
    score: 0.812,
    summary: "Dormant account reactivated: Account inactive for 68 days suddenly sending ₹75,000 to an unlinked beneficiary.",
    status: "open",
    amount: 75000,
    scenario: "dormant_reactivation",
    created_at: "35 minutes ago",
  },
  {
    case_id: "case_drain_06",
    txn_id: "TXN_DRAIN_3821",
    account_id: "C9928172641",
    tier: "BLOCK",
    score: 0.978,
    summary: "Single-shot balance liquidation: Entire originating balance of ₹350,000 transferred out in a single transaction.",
    status: "blocked",
    amount: 350000,
    scenario: "paysim_native",
    created_at: "1 hour ago",
  },
  {
    case_id: "case_step_07",
    txn_id: "TXN_DRAIN_LEGIT_12",
    account_id: "C4428192831",
    tier: "STEP_UP",
    score: 0.42,
    summary: "Elevated risk drawdown: Large balance transfer from primary device; secondary verification requested.",
    status: "approved",
    amount: 140000,
    scenario: "large_legitimate_drain",
    created_at: "2 hours ago",
  },
];

export const MOCK_CASE_DETAIL = {
  case_id: "case_mule_01",
  txn_id: "TXN_MULE_9921",
  account_id: "C1948201948",
  payee_id: "M8472910482",
  amount: 185000,
  step: 642,
  score: 0.984,
  tier: "BLOCK",
  status: "open",
  summary: "Likely mule account: received funds from 22 distinct senders in 24 hours and forwarded 88% onward to collector account.",
  recommended_action: "Decline transaction immediately and freeze receiving account pending KYC re-verification.",
  scenario: "mule_fanin_fanout",
  created_at: "2026-10-29T14:15:00Z",
  reasons: [
    {
      title: "High Payee Fan-In",
      explanation: "Payee account received funds from 22 distinct senders in the last 24 hours (normal: < 3).",
      severity: "high",
      evidence: { payee_fan_in_24h: 22 },
    },
    {
      title: "Pass-Through Account",
      explanation: "Account forwarded 88% of incoming funds to a third-party collector within 4 hours.",
      severity: "high",
      evidence: { payee_outflow_inflow_ratio_24h: 0.88 },
    },
    {
      title: "Rapid Depletion Flag",
      explanation: "Funds were not retained; immediate outward transfer triggered high-velocity drain.",
      severity: "medium",
      evidence: { payee_pass_through_flag: 1.0 },
    },
  ],
  rule_hits: [
    {
      rule_id: "high_fan_in",
      rule_name: "High Fan-In Threshold",
      title: "Unusual number of incoming senders",
      explanation: "Payee received funds from 22 distinct senders in 24 hours",
      severity: "high",
      evidence: { payee_fan_in_24h: 22 },
    },
    {
      rule_id: "pass_through",
      rule_name: "Pass-Through Detection",
      title: "Pass-through account detected",
      explanation: "Account forwarded 88% of incoming funds within 24 hours",
      severity: "high",
      evidence: { outflow_inflow_ratio: 0.88 },
    },
  ],
  features: {
    amount: 185000,
    amount_to_balance: 0.94,
    orig_drained: 0.0,
    count_1h: 3,
    sum_1h: 185000,
    count_24h: 22,
    sum_24h: 420000,
    payee_fan_in_24h: 22,
    payee_outflow_inflow_ratio_24h: 0.88,
    is_new_device: 1.0,
    fraud_exposure_2hop: 3.0,
    isolation_forest_score: 0.96,
    autoencoder_reconstruction_error: 0.94,
  },
  timeline: [
    { time: "10:15 AM", event: "Received ₹25,000 from C3928102910 (Victim 1)", amount: 25000 },
    { time: "11:30 AM", event: "Received ₹40,000 from C8472910291 (Victim 2)", amount: 40000 },
    { time: "01:10 PM", event: "Received ₹60,000 from C1029384719 (Victim 3)", amount: 60000 },
    { time: "02:05 PM", event: "Received ₹60,000 from C4928103948 (Victim 4)", amount: 60000 },
    { time: "02:15 PM", event: "Outward TRANSFER ₹185,000 to M8472910482 (Collector)", amount: -185000 },
  ],
  subgraph: {
    center_account: "C1948201948",
    node_count: 7,
    edge_count: 6,
    nodes: [
      { data: { id: "C1948201948", label: "Mule (Center)", type: "account", is_fraud: 1 } },
      { data: { id: "Victim_1", label: "Victim 1", type: "account", is_fraud: 0 } },
      { data: { id: "Victim_2", label: "Victim 2", type: "account", is_fraud: 0 } },
      { data: { id: "Victim_3", label: "Victim 3", type: "account", is_fraud: 0 } },
      { data: { id: "Victim_4", label: "Victim 4", type: "account", is_fraud: 0 } },
      { data: { id: "Collector_1", label: "Collector M8472", type: "account", is_fraud: 1 } },
      { data: { id: "dev_mule_shared", label: "Device #992", type: "device", is_fraud: 0 } },
    ],
    edges: [
      { data: { source: "Victim_1", target: "C1948201948", amount: 25000, type: "TRANSFER" } },
      { data: { source: "Victim_2", target: "C1948201948", amount: 40000, type: "TRANSFER" } },
      { data: { source: "Victim_3", target: "C1948201948", amount: 60000, type: "TRANSFER" } },
      { data: { source: "Victim_4", target: "C1948201948", amount: 60000, type: "TRANSFER" } },
      { data: { source: "C1948201948", target: "Collector_1", amount: 185000, type: "TRANSFER" } },
      { data: { source: "C1948201948", target: "dev_mule_shared", amount: 0, type: "USED_DEVICE" } },
    ],
  },
  audit_events: [
    { action: "created", actor: "system", note: "Case created with tier=BLOCK, score=0.984", created_at: "2026-10-29T14:15:00Z" },
  ],
};

export const MOCK_PER_SCENARIO_PERF = [
  { scenario: "Burst Takeover", recall: 0.942, pr_auc: 0.925, baseline_recall: 0.12 },
  { scenario: "Mule Fan-In/Fan-Out", recall: 0.965, pr_auc: 0.948, baseline_recall: 0.08 },
  { scenario: "Shared Device Ring", recall: 0.951, pr_auc: 0.938, baseline_recall: 0.05 },
  { scenario: "Structuring", recall: 0.885, pr_auc: 0.862, baseline_recall: 0.15 },
  { scenario: "Dormant Reactivation", recall: 0.912, pr_auc: 0.895, baseline_recall: 0.22 },
  { scenario: "PaySim Native Drain", recall: 0.987, pr_auc: 0.988, baseline_recall: 0.987 },
];

export const MOCK_ABLATION = [
  { name: "Full Champion Model (v2)", pr_auc: 0.968, drop: 0.0 },
  { name: "- Graph Features", pr_auc: 0.842, drop: 0.126 },
  { name: "- Behavioural Features", pr_auc: 0.875, drop: 0.093 },
  { name: "- Device / Network", pr_auc: 0.891, drop: 0.077 },
  { name: "- Velocity Features", pr_auc: 0.915, drop: 0.053 },
  { name: "- Anomaly Ensembles", pr_auc: 0.932, drop: 0.036 },
  { name: "- Drain Balance Features", pr_auc: 0.948, drop: 0.02 },
];
