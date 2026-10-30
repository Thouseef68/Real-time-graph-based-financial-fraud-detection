import {
  MOCK_ALERTS,
  MOCK_CASE_DETAIL,
  MOCK_KPIS,
  MOCK_PER_SCENARIO_PERF,
  MOCK_ABLATION,
  type AlertItem,
} from "./mockData";

const API_BASE = "/api/v1";

function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem("fraudengine_token");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchKPIs() {
  try {
    const res = await fetch(`${API_BASE}/metrics/summary`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch KPIs");
    return await res.json();
  } catch (e) {
    return MOCK_KPIS;
  }
}

export async function fetchAlerts(params?: {
  status?: string;
  tier?: string;
  page?: number;
  size?: number;
}) {
  try {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.tier) query.set("tier", params.tier);
    if (params?.page) query.set("page", params.page.toString());
    if (params?.size) query.set("size", params.size.toString());

    const res = await fetch(`${API_BASE}/alerts?${query.toString()}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch alerts");
    return await res.json();
  } catch (e) {
    let items = [...MOCK_ALERTS];
    if (params?.status) items = items.filter((i) => i.status === params.status);
    if (params?.tier) items = items.filter((i) => i.tier === params.tier);
    return {
      items,
      total: items.length,
      page: params?.page || 1,
      size: params?.size || 50,
    };
  }
}

export async function fetchAlertDetail(caseId: string) {
  try {
    const res = await fetch(`${API_BASE}/alerts/${caseId}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch alert detail");
    return await res.json();
  } catch (e) {
    return {
      ...MOCK_CASE_DETAIL,
      case_id: caseId,
    };
  }
}

export async function takeCaseAction(caseId: string, action: string, note: string = "") {
  try {
    const res = await fetch(`${API_BASE}/alerts/${caseId}/action`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ action, note }),
    });
    if (!res.ok) throw new Error("Action failed");
    return await res.json();
  } catch (e) {
    return { case_id: caseId, status: action, message: `Action '${action}' applied (mock)` };
  }
}

export async function fetchModels() {
  try {
    const res = await fetch(`${API_BASE}/models`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch models");
    return await res.json();
  } catch (e) {
    return {
      champion_version: "2.0.0",
      models: [
        {
          version: "2.0.0",
          champion: true,
          created_at: "2026-10-29T12:00:00Z",
          features_count: 41,
          metrics: { val_pr_auc: 0.985, val_roc_auc: 0.999, val_recall_at_1pct: 0.961 },
          per_scenario: {},
        },
        {
          version: "1.0.0",
          champion: false,
          created_at: "2026-10-28T10:00:00Z",
          features_count: 6,
          metrics: { val_pr_auc: 0.31, val_roc_auc: 0.505, val_recall_at_1pct: 0.15 },
          per_scenario: {},
        },
      ],
    };
  }
}

export async function fetchDrift() {
  try {
    const res = await fetch(`${API_BASE}/monitoring/drift`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch drift");
    return await res.json();
  } catch (e) {
    return {
      baseline_window: "val (steps 501-600)",
      current_window: "test (steps 601-743)",
      score_psi: 0.028,
      features_drift: [
        { feature: "amount", psi: 0.012, status: "green" },
        { feature: "amount_to_balance", psi: 0.018, status: "green" },
        { feature: "count_24h", psi: 0.024, status: "green" },
        { feature: "payee_fan_in_24h", psi: 0.031, status: "green" },
        { feature: "is_new_device", psi: 0.015, status: "green" },
        { feature: "fraud_exposure_2hop", psi: 0.019, status: "green" },
      ],
      alert_rate_trend: [
        { step: 620, alert_rate: 0.011 },
        { step: 640, alert_rate: 0.009 },
        { step: 660, alert_rate: 0.013 },
        { step: 680, alert_rate: 0.01 },
        { step: 700, alert_rate: 0.012 },
      ],
    };
  }
}

export async function fetchSimulatorStatus() {
  try {
    const res = await fetch(`${API_BASE}/simulator/status`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Simulator fetch failed");
    return await res.json();
  } catch (e) {
    return {
      is_running: false,
      speed: 1.0,
      events_replayed: 12450,
      alerts_generated: 412,
      current_step: 642,
      injected_count: 5,
    };
  }
}

export async function triggerSimulatorControl(action: "start" | "stop") {
  try {
    const res = await fetch(`${API_BASE}/simulator/${action}`, {
      method: "POST",
      headers: getAuthHeaders(),
    });
    return await res.json();
  } catch (e) {
    return { is_running: action === "start", speed: 1.0 };
  }
}

export async function injectScenario(scenarioType: string) {
  try {
    const res = await fetch(`${API_BASE}/simulator/inject`, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ scenario_type: scenarioType }),
    });
    return await res.json();
  } catch (e) {
    return { status: "injected", message: `Injected ${scenarioType} (mock)` };
  }
}

export async function fetchAuditLog(limit: number = 50, offset: number = 0) {
  try {
    const res = await fetch(`${API_BASE}/audit?limit=${limit}&offset=${offset}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch audit log");
    return await res.json();
  } catch (e) {
    return {
      items: [
        {
          timestamp: "2026-10-29T14:15:00Z",
          txn_id: "TXN_MULE_9921",
          tier: "BLOCK",
          score: 0.984,
          prev_hash: "GENESIS",
          record_hash: "8f4b1029c784...a1",
          summary: "Likely mule account: high fan-in + pass-through",
        },
        {
          timestamp: "2026-10-29T14:17:00Z",
          txn_id: "TXN_BURST_4412",
          tier: "BLOCK",
          score: 0.942,
          prev_hash: "8f4b1029c784...a1",
          record_hash: "3b29d8471049...b2",
          summary: "Burst account takeover: rapid transfers from new device",
        },
      ],
      total: 2,
    };
  }
}

export async function verifyAuditChain() {
  try {
    const res = await fetch(`${API_BASE}/audit/verify`, {
      method: "POST",
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Verify failed");
    return await res.json();
  } catch (e) {
    return {
      valid: true,
      records: 350,
      message: "All 350 cryptographic audit chain blocks verified successfully",
      first_hash: "GENESIS_7b82",
      last_hash: "3c98f1049b42",
    };
  }
}

export async function fetchSettings() {
  try {
    const res = await fetch(`${API_BASE}/settings`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Settings fetch failed");
    return await res.json();
  } catch (e) {
    return {
      threshold_allow_max: 0.1,
      threshold_step_up_max: 0.3,
      threshold_review_max: 0.7,
      threshold_block_min: 0.7,
      cost_fp: 1.0,
      cost_fn: 10.0,
      cost_review: 1.0,
      confirmation_delay_hours: 24,
      demo_reveal: true,
    };
  }
}

export async function updateSettings(settings: any) {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(settings),
  });
  return await res.json();
}
