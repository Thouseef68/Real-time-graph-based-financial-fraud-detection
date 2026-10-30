"""Pydantic schemas for the FastAPI backend (Pydantic v2)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "2.0.0"
    engine_mode: str = "inproc"
    timestamp: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserResponse(BaseModel):
    username: str
    role: str
    email: Optional[str] = None


class MetricsSummaryResponse(BaseModel):
    total_transactions_scored: int = 0
    total_alerts: int = 0
    open_alerts: int = 0
    blocked_alerts: int = 0
    alert_rate: float = 0.0
    amount_held_or_blocked: float = 0.0
    avg_risk_score: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


class ReasonSchema(BaseModel):
    title: str
    explanation: str
    severity: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RuleHitSchema(BaseModel):
    rule_id: str
    rule_name: str
    title: str
    explanation: str
    severity: str
    evidence: Dict[str, Any] = Field(default_factory=dict)


class TransactionScoreRequest(BaseModel):
    txn_id: str
    step: int = 0
    account_id: str
    payee_id: str
    amount: float
    txn_type: str = "TRANSFER"
    old_balance_orig: float = 0.0
    new_balance_orig: float = 0.0
    device_id: Optional[str] = "dev_default"
    ip_prefix: Optional[str] = "192.168.1"
    hour_of_day: Optional[int] = 12


class DecisionResponse(BaseModel):
    txn_id: str
    account_id: str
    score: float
    tier: str
    summary: str
    recommended_action: str
    reasons: List[ReasonSchema]
    rule_hits: List[RuleHitSchema] = Field(default_factory=list)
    latency_ms: float
    model_version: str
    config_hash: str
    feature_snapshot: Optional[Dict[str, float]] = None


class AlertSummary(BaseModel):
    case_id: str
    txn_id: str
    account_id: str
    tier: str
    score: float
    summary: str
    status: str
    amount: float
    scenario: Optional[str] = None  # Hidden unless demo_reveal
    group_id: Optional[str] = None
    created_at: str


class AlertListResponse(BaseModel):
    items: List[AlertSummary]
    total: int
    page: int
    size: int


class ActionRequest(BaseModel):
    action: str  # approve, block, escalate, dismiss
    note: str = ""


class ActionResponse(BaseModel):
    case_id: str
    status: str
    message: str


class SubgraphNode(BaseModel):
    data: Dict[str, Any]


class SubgraphEdge(BaseModel):
    data: Dict[str, Any]


class SubgraphResponse(BaseModel):
    center_account: str
    node_count: int
    edge_count: int
    nodes: List[SubgraphNode]
    edges: List[SubgraphEdge]


class AlertDetailResponse(BaseModel):
    case_id: str
    txn_id: str
    account_id: str
    payee_id: Optional[str] = "unknown"
    amount: float
    step: int
    score: float
    tier: str
    status: str
    summary: str
    recommended_action: str
    reasons: List[ReasonSchema]
    rule_hits: List[RuleHitSchema]
    features: Dict[str, float]
    timeline: List[Dict[str, Any]]
    subgraph: SubgraphResponse
    audit_events: List[Dict[str, Any]]
    scenario: Optional[str] = None
    created_at: str


class AccountDetailResponse(BaseModel):
    account_id: str
    first_seen_step: Optional[int] = None
    last_seen_step: Optional[int] = None
    total_txns: int = 0
    total_amount: float = 0.0
    known_devices: List[str] = Field(default_factory=list)
    known_payees: List[str] = Field(default_factory=list)
    recent_transactions: List[Dict[str, Any]] = Field(default_factory=list)


class SimulatorStatusResponse(BaseModel):
    is_running: bool
    speed: float = 1.0  # events per second multiplier
    events_replayed: int = 0
    alerts_generated: int = 0
    current_step: int = 601
    injected_count: int = 0


class SimulatorSpeedRequest(BaseModel):
    speed: float = Field(gt=0, le=100.0)


class InjectScenarioRequest(BaseModel):
    scenario_type: str  # burst_takeover, mule_fanin_fanout, shared_device_ring, structuring, dormant_reactivation


class ModelMetricsSchema(BaseModel):
    val_pr_auc: Optional[float] = None
    val_roc_auc: Optional[float] = None
    val_recall_at_1pct: Optional[float] = None
    test_pr_auc: Optional[float] = None


class ModelVersionResponse(BaseModel):
    version: str
    champion: bool
    created_at: str
    features_count: int
    metrics: Dict[str, Any]
    per_scenario: Dict[str, Any] = Field(default_factory=dict)


class ModelsListResponse(BaseModel):
    champion_version: str
    models: List[ModelVersionResponse]


class DriftFeatureMetric(BaseModel):
    feature: str
    psi: float
    status: str  # "green", "amber", "red"


class DriftResponse(BaseModel):
    baseline_window: str = "val (steps 501-600)"
    current_window: str = "test (steps 601-743)"
    score_psi: float = 0.04
    features_drift: List[DriftFeatureMetric] = Field(default_factory=list)
    alert_rate_trend: List[Dict[str, Any]] = Field(default_factory=list)


class VerifyChainResponse(BaseModel):
    valid: bool
    records: int
    message: str
    first_hash: Optional[str] = None
    last_hash: Optional[str] = None


class AuditRecordsResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int


class SettingsResponse(BaseModel):
    threshold_allow_max: float
    threshold_step_up_max: float
    threshold_review_max: float
    threshold_block_min: float
    cost_fp: float
    cost_fn: float
    cost_review: float
    confirmation_delay_hours: int
    demo_reveal: bool = False


class SettingsUpdateRequest(BaseModel):
    threshold_allow_max: Optional[float] = None
    threshold_step_up_max: Optional[float] = None
    threshold_review_max: Optional[float] = None
    threshold_block_min: Optional[float] = None
    cost_fp: Optional[float] = None
    cost_fn: Optional[float] = None
    cost_review: Optional[float] = None
    demo_reveal: Optional[bool] = None


class DemoRunCreateRequest(BaseModel):
    scenario: Optional[str] = "demo_mule_ring"
    seed: Optional[int] = 42
    speed: Optional[float] = 1.0
    protection_enabled: Optional[bool] = True


class DemoControlRequest(BaseModel):
    action: str  # "play", "pause", "step", "reset"
    speed: Optional[float] = None


class DemoTransferRequest(BaseModel):
    from_account: str
    to_account: str
    amount: float


# Phase 12: Live Sandbox Bank Schemas
class LiveRoomCreateRequest(BaseModel):
    room_code: Optional[str] = None
    scale_factor: Optional[float] = 60.0


class LiveParticipantJoinRequest(BaseModel):
    display_name: str
    device_id: Optional[str] = None
    network_label: Optional[str] = "Campus-WiFi"
    coarse_fingerprint: Optional[str] = None
    consent_accepted: bool = False
    join_token: Optional[str] = None


class LiveTransferRequest(BaseModel):
    room_code: str
    sender_id: str
    receiver_id: str
    amount: float
    session_token: Optional[str] = None
    note: Optional[str] = ""
    idempotency_key: Optional[str] = None
    device_id: Optional[str] = None


class LiveNetworkLabelUpdateRequest(BaseModel):
    network_label: str


class DemoToggleRequest(BaseModel):
    rules_enabled: Optional[bool] = None
    model_enabled: Optional[bool] = None



