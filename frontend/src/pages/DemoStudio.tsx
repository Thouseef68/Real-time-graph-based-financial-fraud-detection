import React, { useEffect, useState, useRef } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle,
  CheckCircle2,
  Clock,
  Copy,
  Database,
  ExternalLink,
  Flame,
  Globe,
  HelpCircle,
  Layers,
  Lock,
  Maximize2,
  Minimize2,
  Network,
  Play,
  PlayCircle,
  Pause,
  PlusCircle,
  QrCode,
  RefreshCw,
  Send,
  Server,
  Settings,
  Settings2,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Smartphone,
  Sparkles,
  Terminal,
  Trash2,
  TrendingDown,
  TrendingUp,
  UserCheck,
  Users,
  Wifi,
  XCircle,
  Zap,
} from "lucide-react";
import { CytoscapeGraph } from "../components/common/CytoscapeGraph";
import { LiveMoneyFlowGraph, ParticipantNodeData } from "../components/common/LiveMoneyFlowGraph";
import { cn } from "../lib/utils";

interface DemoHealth {
  status: string;
  offline_mode?: boolean;
  offline_warning?: string | null;
  redpanda: { status: string; mode: string; partitions: number; healthy: boolean };
  redis: { status: string; mode: string; healthy: boolean };
  neo4j: { status: string; mode: string; healthy: boolean };
  model: { status: string; version: string; features_count: number; healthy: boolean; rules_enabled?: boolean; model_enabled?: boolean };
}

interface DemoStatus {
  current_index: number;
  total_events: number;
  is_running: boolean;
  speed: number;
  seed: number;
  protection_enabled: boolean;
  current_act: number;
  money_moved: number;
  money_held: number;
  money_saved: number;
  completed: boolean;
  blocklists: {
    blocked_accounts: string[];
    blocked_devices: string[];
    held_accounts: string[];
    monitored_accounts: string[];
  };
}

interface LiveParticipant {
  account_id: string;
  display_name: string;
  balance: number;
  device_id: string;
  raw_ip: string;
  network_label: string;
  joined_at: number;
  is_bot: boolean;
  role_card?: {
    role_id: string;
    title: string;
    badge: string;
    instructions: string;
    suggested_target?: string;
    suggested_amount?: number;
  };
  engine_status?: string;
  fan_in_count?: number;
  inflow?: number;
  outflow?: number;
  pass_through?: number;
  reasons?: string[];
}

interface LiveCase {
  case_id: string;
  txn: any;
  decision: any;
  amount: number;
  sender_display: string;
  receiver_display: string;
  status: "PENDING" | "APPROVED" | "BLOCKED";
}

const ACT_TITLES: Record<number, { title: string; subtitle: string; badge: string }> = {
  1: {
    title: "Normal Day",
    subtitle: "Ordinary retail payments flowing across 6 Kafka partitions. All health indicators green; scores < 0.05.",
    badge: "Baseline Traffic",
  },
  2: {
    title: "Ring Wakes Up",
    subtitle: "Four dormant accounts (A to D) suddenly reactivate on new devices after 60+ days. Entity graph maps shared device and IP infrastructure.",
    badge: "Infrastructure Linkage",
  },
  3: {
    title: "Victims Pay",
    subtitle: "12 victims transfer funds to Member A. Redis fan-in counter rapidly climbs from 0 to 12 distinct senders in 24 hours.",
    badge: "Mule Accumulation",
  },
  4: {
    title: "Layering",
    subtitle: "Funds hop rapidly from A -> B -> C -> D within minutes. Outflow/inflow ratio hits 98%, triggering high-velocity pass-through flags.",
    badge: "Rapid Layering",
  },
  5: {
    title: "Real-Time Detection",
    subtitle: "Cumulative feature state spikes risk score to 0.94. Scorer triggers confirmed BLOCK with plain-English SHAP explanation cards.",
    badge: "Model & Rules Fusion",
  },
  6: {
    title: "Graph Containment",
    subtitle: "Member A is blocked in Redis. Containment traverses graph: Members B, C, D placed on HOLD; innocent household neighbor is monitored only.",
    badge: "Precision Isolation",
  },
  7: {
    title: "Cash-Out Interception",
    subtitle: "Member D attempts external ₹46,000 cash-out withdrawal. Pre-scoring Redis blocklist check declines transfer in < 2ms without model latency.",
    badge: "Loss Prevention",
  },
};

export const DemoStudio: React.FC = () => {
  // Mode Switcher: "story" (Phase 11 Script) vs "live" (Phase 12 Audience Participation)
  const [studioMode, setStudioMode] = useState<"story" | "live">("story");

  // System Health
  const [health, setHealth] = useState<DemoHealth | null>(null);
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [activeTab, setActiveTab] = useState<"decision" | "kafka" | "redis" | "graph_query">("decision");
  const [presenterMode, setPresenterMode] = useState(false);

  const getStatusBadge = (s?: string) => {
    switch (s) {
      case "BLOCKED":
        return "bg-rose-500/10 text-rose-500 border-rose-500/30";
      case "HELD":
        return "bg-blue-500/10 text-blue-500 border-blue-500/30";
      case "MONITORING":
        return "bg-amber-500/10 text-amber-500 border-amber-500/30";
      default:
        return "bg-emerald-500/10 text-emerald-500 border-emerald-500/30";
    }
  };

  // Live Stream Events (Story Mode)
  const [currentNarrative, setCurrentNarrative] = useState<any>({
    act: 1,
    title: "Act 1: Normal Day",
    narrative: "Ordinary payments flowing between legitimate customers and merchants across 6 Kafka partitions. All health indicators green; model scores remain well below alert thresholds (< 0.05).",
  });
  const [kafkaFeed, setKafkaFeed] = useState<any[]>([]);
  const [redisDeltas, setRedisDeltas] = useState<any[]>([]);
  const [lastCypherQuery, setLastCypherQuery] = useState<string>(
    "MATCH (primary:Account {account_id: 'CUST_MULE_A'})\nOPTIONAL MATCH (primary)-[:USED_DEVICE]->(d:Device)-[:ON_IP]->(ip:IPPrefix)<-[:ON_IP]-(d2:Device)<-[:USED_DEVICE]-(linked_peer:Account)\nOPTIONAL MATCH (primary)-[:TRANSFER*1..3]->(downstream:Account)\nRETURN primary, collect(DISTINCT linked_peer) AS infrastructure_peers, collect(DISTINCT downstream) AS layering_chain"
  );
  const [latestDecision, setLatestDecision] = useState<any>({
    txn_id: "TXN_ACT1_INIT",
    score: 0.024,
    tier: "ALLOW",
    summary: "Transaction appears normal; activity is consistent with account history.",
    action: "Process normally",
    reasons: [],
    latency_ms: 1.4,
  });

  // Story Mode Graph State
  const [graphElements, setGraphElements] = useState<{ nodes: any[]; edges: any[] }>({
    nodes: [
      { data: { id: "CUST_MULE_A", label: "Member A", type: "account", is_fraud: 0 } },
      { data: { id: "CUST_MULE_B", label: "Member B", type: "account", is_fraud: 0 } },
      { data: { id: "CUST_MULE_C", label: "Member C", type: "account", is_fraud: 0 } },
      { data: { id: "CUST_MULE_D", label: "Member D", type: "account", is_fraud: 0 } },
      { data: { id: "CUST_INNOCENT_HOUSEHOLD", label: "Innocent Neighbor", type: "account", is_fraud: 0 } },
      { data: { id: "198.51.100.14", label: "IP 198.51.100.14", type: "ip_prefix" } },
      { data: { id: "DEV_MULE_BC_SHARED", label: "Shared Device", type: "device" } },
    ],
    edges: [
      { data: { source: "CUST_MULE_A", target: "198.51.100.14", type: "ON_IP" } },
      { data: { source: "CUST_MULE_B", target: "198.51.100.14", type: "ON_IP" } },
      { data: { source: "CUST_INNOCENT_HOUSEHOLD", target: "198.51.100.14", type: "ON_IP" } },
      { data: { source: "CUST_MULE_B", target: "DEV_MULE_BC_SHARED", type: "USED_DEVICE" } },
      { data: { source: "CUST_MULE_C", target: "DEV_MULE_BC_SHARED", type: "USED_DEVICE" } },
    ],
  });

  // "Try It Yourself" interactive transfer modal (Story mode)
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [transferFrom, setTransferFrom] = useState("CUST_MULE_D");
  const [transferTo, setTransferTo] = useState("MERCHANT_CRYPTO_EXCHANGE");
  const [transferAmount, setTransferAmount] = useState(15000);
  const [transferResult, setTransferResult] = useState<any>(null);
  const [isSubmittingTransfer, setIsSubmittingTransfer] = useState(false);

  // ─────────────────────────────────────────────────────────────
  // Phase 12: Live Sandbox Bank Room State
  // ─────────────────────────────────────────────────────────────
  const [activeRoomCode, setActiveRoomCode] = useState<string>("MULE42");
  const [liveRoomData, setLiveRoomData] = useState<any>(null);
  const [joinInfo, setJoinInfo] = useState<{
    room_code: string;
    lan_ip: string;
    port: number;
    join_url: string;
    join_token?: string;
    profile_name: string;
  } | null>(null);
  const [showQrModal, setShowQrModal] = useState<boolean>(false);
  const [copiedUrl, setCopiedUrl] = useState<boolean>(false);
  const [dismissWarning, setDismissWarning] = useState<boolean>(false);

  // Dynamic join URL: uses public hostname/origin on Render, custom domain, or cloud, ensuring ANY phone can join
  const effectiveJoinUrl = React.useMemo(() => {
    if (!joinInfo?.join_url) return "";
    if (typeof window !== "undefined" && window.location.origin) {
      const host = window.location.hostname;
      if (host && !host.includes("localhost") && !host.includes("127.0.0.1")) {
        const room = encodeURIComponent(joinInfo.room_code || activeRoomCode);
        const token = joinInfo.join_token ? encodeURIComponent(joinInfo.join_token) : "";
        return `${window.location.origin}/app?room=${room}${token ? `&token=${token}` : ""}`;
      }
    }
    return joinInfo.join_url;
  }, [joinInfo, activeRoomCode]);

  // Graph Layer & Node Inspection State
  const [showDevicesAndNetworks, setShowDevicesAndNetworks] = useState<boolean>(false);
  const [selectedParticipantNode, setSelectedParticipantNode] = useState<ParticipantNodeData | null>(null);

  // Editing Network Labels
  const [editingNetworkUser, setEditingNetworkUser] = useState<string | null>(null);
  const [newNetworkLabel, setNewNetworkLabel] = useState<string>("");

  // Case Queue
  const [liveCases, setLiveCases] = useState<LiveCase[]>([]);
  const [isActionLoading, setIsActionLoading] = useState<string | null>(null);

  // Presenter Demo Toggles (Item 6)
  const [rulesEnabled, setRulesEnabled] = useState<boolean>(true);
  const [modelEnabled, setModelEnabled] = useState<boolean>(true);

  const toggleLayer = async (layer: "rules" | "model") => {
    const nextRules = layer === "rules" ? !rulesEnabled : rulesEnabled;
    const nextModel = layer === "model" ? !modelEnabled : modelEnabled;
    try {
      const res = await fetch("/api/v1/demo/toggles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rules_enabled: nextRules,
          model_enabled: nextModel,
        }),
      });
      if (res.ok) {
        const d = await res.json();
        setRulesEnabled(d.rules_enabled);
        setModelEnabled(d.model_enabled);
      }
    } catch (e) {
      console.error("Layer toggle error:", e);
    }
  };

  // Construct plain-English ticker string with zero hardcoded values (Item 5)
  const getTickerText = () => {
    if (studioMode === "live") {
      const recent = liveRoomData?.recent_transfers;
      if (recent && recent.length > 0) {
        const last = recent[recent.length - 1];
        const sName = last.sender_name || last.sender_id;
        const rName = last.receiver_name || last.receiver_id;
        const amt = Math.round(last.amount || 0);
        const tier = last.tier || (last.status === "DECLINED" ? "BLOCK" : (last.status === "HELD" ? "REVIEW" : "ALLOW"));
        const score = last.score !== undefined ? Number(last.score).toFixed(4) : "0.0002";
        const lat = last.latency_ms !== undefined ? Number(last.latency_ms).toFixed(2) : "0.00";
        return `${sName} -> ${rName}, ₹${amt.toLocaleString()}, ${tier} (score ${score}), ${lat} ms`;
      }
      return "Waiting for live transfers from connected participant phones...";
    } else {
      if (latestDecision?.txn_id) {
        const score = latestDecision.score !== undefined ? Number(latestDecision.score).toFixed(4) : "0.0002";
        const lat = latestDecision.latency_ms !== undefined ? Number(latestDecision.latency_ms).toFixed(2) : "0.00";
        return `${latestDecision.txn_id}, ₹${(status?.money_moved || 0).toLocaleString()}, ${latestDecision.tier} (score ${score}), ${lat} ms`;
      }
      return "Four-Account Mule Ring story pipeline ready.";
    }
  };

  // Poll Health & Status
  useEffect(() => {
    fetchHealth();
    fetchStatus();

    // Setup SSE connection
    const evtSource = new EventSource("/api/v1/demo/stream");

    evtSource.addEventListener("demo_status", (e) => {
      try {
        const d = JSON.parse(e.data);
        setStatus(d);
      } catch (err) {}
    });

    evtSource.addEventListener("narrative_step", (e) => {
      try {
        const d = JSON.parse(e.data);
        setCurrentNarrative(d);
      } catch (err) {}
    });

    evtSource.addEventListener("kafka_message", (e) => {
      try {
        const msg = JSON.parse(e.data);
        setKafkaFeed((prev) => [msg, ...prev.slice(0, 19)]);
      } catch (err) {}
    });

    evtSource.addEventListener("redis_delta", (e) => {
      try {
        const delta = JSON.parse(e.data);
        setRedisDeltas((prev) => [delta, ...prev.slice(0, 24)]);
      } catch (err) {}
    });

    evtSource.addEventListener("decision", (e) => {
      try {
        const dec = JSON.parse(e.data);
        setLatestDecision(dec);
      } catch (err) {}
    });

    evtSource.addEventListener("graph_delta", (e) => {
      try {
        const delta = JSON.parse(e.data);
        setGraphElements((prev) => {
          const nodeMap = new Map(prev.nodes.map((n) => [n.data.id, n]));
          const edgeMap = new Map(prev.edges.map((e) => [`${e.data.source}->${e.data.target}`, e]));

          (delta.nodes || []).forEach((n: any) => nodeMap.set(n.data.id, n));
          (delta.edges || []).forEach((e: any) => edgeMap.set(`${e.data.source}->${e.data.target}`, e));

          return {
            nodes: Array.from(nodeMap.values()),
            edges: Array.from(edgeMap.values()),
          };
        });
      } catch (err) {}
    });

    evtSource.addEventListener("containment_action", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.cypher_query) {
          setLastCypherQuery(data.cypher_query);
        }
        setGraphElements((prev) => ({
          nodes: prev.nodes.map((node) => {
            const id = node.data.id;
            if (id === data.target_account) {
              return { ...node, data: { ...node.data, is_fraud: 1, label: `${node.data.label || id} (BLOCKED)` } };
            }
            if ((data.held_accounts || []).includes(id)) {
              return { ...node, data: { ...node.data, is_held: true, label: `${node.data.label || id} (HELD)` } };
            }
            if ((data.monitored_accounts || []).includes(id)) {
              return { ...node, data: { ...node.data, is_monitored: true, label: `${node.data.label || id} (MONITOR)` } };
            }
            return node;
          }),
          edges: prev.edges,
        }));
      } catch (err) {}
    });

    evtSource.addEventListener("live_case", (e) => {
      try {
        const c = JSON.parse(e.data);
        setLiveCases((prev) => [c, ...prev]);
      } catch (err) {}
    });

    evtSource.addEventListener("case_resolved", (e) => {
      try {
        const c = JSON.parse(e.data);
        setLiveCases((prev) => prev.filter((item) => item.case_id !== c.case_id));
      } catch (err) {}
    });

    const interval = setInterval(() => {
      fetchHealth();
      fetchStatus();
    }, 4000);

    return () => {
      evtSource.close();
      clearInterval(interval);
    };
  }, []);

  // Poll active live room data when in live mode
  useEffect(() => {
    if (studioMode !== "live" || !activeRoomCode) return;

    fetchLiveRoomData();
    fetchJoinInfo();

    const interval = setInterval(fetchLiveRoomData, 2000);
    return () => clearInterval(interval);
  }, [studioMode, activeRoomCode]);

  const fetchHealth = async () => {
    try {
      const res = await fetch("/api/v1/demo/health");
      if (res.ok) {
        const d = await res.json();
        setHealth(d);
        if (d.model?.rules_enabled !== undefined) setRulesEnabled(d.model.rules_enabled);
        if (d.model?.model_enabled !== undefined) setModelEnabled(d.model.model_enabled);
      }
    } catch (e) {}
  };

  const fetchStatus = async () => {
    try {
      const res = await fetch("/api/v1/demo/status");
      if (res.ok) setStatus(await res.json());
    } catch (e) {}
  };

  const fetchJoinInfo = async () => {
    try {
      const res = await fetch(`/api/v1/live/rooms/${activeRoomCode}/join-info`);
      if (res.ok) setJoinInfo(await res.json());
    } catch (e) {}
  };

  const fetchLiveRoomData = async () => {
    try {
      const res = await fetch(`/api/v1/live/rooms/${activeRoomCode}`);
      if (res.ok) {
        const data = await res.json();
        setLiveRoomData(data);
        if (data.case_queue) {
          setLiveCases(Object.values(data.case_queue).filter((c: any) => c.status === "PENDING") as LiveCase[]);
        }

        // Dynamically update Cytoscape graph nodes from live participants
        if (studioMode === "live" && data.participants) {
          const liveNodes: any[] = [];
          const liveEdges: any[] = [];
          const networksSet = new Set<string>();
          const devicesSet = new Set<string>();

          data.participants.forEach((p: LiveParticipant) => {
            liveNodes.push({
              data: {
                id: p.account_id,
                label: `${p.display_name} (₹${p.balance.toLocaleString()})`,
                type: "account",
                is_fraud: p.account_id.includes("MULE_A") ? 1 : 0,
              },
            });

            if (p.network_label) {
              networksSet.add(p.network_label);
              liveEdges.push({
                data: { source: p.account_id, target: p.network_label, type: "ON_IP" },
              });
            }

            if (p.device_id && !p.is_bot) {
              devicesSet.add(p.device_id);
              liveEdges.push({
                data: { source: p.account_id, target: p.device_id, type: "USED_DEVICE" },
              });
            }
          });

          networksSet.forEach((net) => {
            liveNodes.push({
              data: { id: net, label: `Subnet: ${net}`, type: "ip_prefix" },
            });
          });

          devicesSet.forEach((dev) => {
            liveNodes.push({
              data: { id: dev, label: `Device: ${dev}`, type: "device" },
            });
          });

          setGraphElements({ nodes: liveNodes, edges: liveEdges });
        }
      }
    } catch (e) {}
  };

  // Live Room Management
  const handleCreateLiveRoom = async () => {
    try {
      const res = await fetch("/api/v1/live/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_code: `MULE${Math.floor(10 + Math.random() * 89)}` }),
      });
      if (res.ok) {
        const room = await res.json();
        setActiveRoomCode(room.room_code);
        setLiveRoomData(room);
        fetchJoinInfo();
      }
    } catch (e) {}
  };

  const handleWipeLiveRoom = async () => {
    if (!window.confirm(`Wipe room ${activeRoomCode} and clear all Redis state with zero residue?`)) return;
    try {
      const res = await fetch(`/api/v1/live/rooms/${activeRoomCode}`, { method: "DELETE" });
      if (res.ok) {
        handleCreateLiveRoom();
      }
    } catch (e) {}
  };

  const handleSaveNetworkLabel = async (accountId: string) => {
    if (!newNetworkLabel.trim()) return;
    try {
      const res = await fetch(`/api/v1/live/rooms/${activeRoomCode}/participants/${accountId}/network`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ network_label: newNetworkLabel.trim() }),
      });
      if (res.ok) {
        setEditingNetworkUser(null);
        fetchLiveRoomData();
      }
    } catch (e) {}
  };

  // Analyst Case Actions
  const handleApproveCase = async (caseId: string) => {
    setIsActionLoading(caseId);
    try {
      const res = await fetch(`/api/v1/live/cases/${caseId}/approve?room_code=${activeRoomCode}`, {
        method: "POST",
      });
      if (res.ok) {
        setLiveCases((prev) => prev.filter((c) => c.case_id !== caseId));
        fetchLiveRoomData();
      }
    } catch (e) {}
    setIsActionLoading(null);
  };

  const handleBlockCase = async (caseId: string) => {
    setIsActionLoading(caseId);
    try {
      const res = await fetch(`/api/v1/live/cases/${caseId}/block?room_code=${activeRoomCode}`, {
        method: "POST",
      });
      if (res.ok) {
        setLiveCases((prev) => prev.filter((c) => c.case_id !== caseId));
        fetchLiveRoomData();
      }
    } catch (e) {}
    setIsActionLoading(null);
  };

  // Story Mode Playback Controls
  const handleControl = async (action: string, speed?: number) => {
    try {
      const res = await fetch("/api/v1/demo/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, speed }),
      });
      if (res.ok) {
        const s = await res.json();
        setStatus(s);
      }
    } catch (e) {}
  };

  const togglePlay = () => {
    if (status?.is_running) {
      handleControl("pause");
    } else {
      handleControl("play");
    }
  };

  const stepDemo = () => {
    handleControl("step");
  };

  const resetDemo = async (protectionEnabled?: boolean) => {
    try {
      const res = await fetch("/api/v1/demo/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          seed: status?.seed || 42,
          speed: status?.speed || 1.0,
          protection_enabled:
            protectionEnabled !== undefined ? protectionEnabled : status?.protection_enabled ?? true,
        }),
      });
      if (res.ok) {
        setStatus(await res.json());
        setKafkaFeed([]);
        setRedisDeltas([]);
      }
    } catch (e) {}
  };

  const copyJoinUrl = () => {
    const urlToCopy = effectiveJoinUrl || joinInfo?.join_url;
    if (urlToCopy) {
      navigator.clipboard.writeText(urlToCopy);
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2000);
    }
  };

  const actNum = currentNarrative?.act || status?.current_act || 1;
  const actInfo = ACT_TITLES[actNum] || ACT_TITLES[1];

  return (
    <div className={cn("space-y-4 font-sans transition-all", presenterMode && "p-2 max-w-7xl mx-auto")}>
      {/* ─────────────────────────────────────────────────────────────
          PERSISTENT TOP SIMULATION BANNER
      ───────────────────────────────────────────────────────────── */}
      <div className="bg-amber-500 text-slate-950 px-3 py-1.5 text-center text-xs font-bold tracking-wide uppercase flex items-center justify-center gap-2 rounded-xl shadow-sm">
        <Lock className="w-3.5 h-3.5" />
        <span>Simulation: Virtual Money Only • No Real Bank or UPI Connections</span>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          1. SYSTEM HEALTH STRIP & OFFLINE SIMULATION WARNING (Item 1 & 4)
      ───────────────────────────────────────────────────────────── */}
      {(!health?.redpanda.healthy || health?.offline_warning) && !dismissWarning && (
        <div className="bg-amber-500/10 border border-amber-500/30 px-4 py-2.5 rounded-xl flex items-center justify-between text-xs font-mono shadow-sm">
          <div className="flex items-center gap-2.5 font-bold text-amber-600 dark:text-amber-400">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
            <span className="text-xs tracking-wide uppercase">In-Process Stream Active (Cloud Container)</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-slate-600 dark:text-slate-400 font-sans hidden sm:inline">
              External Kafka broker not detected at 127.0.0.1:9092. Running high-speed in-process partition stream with full scoring & graph traversal.
            </span>
            <button
              onClick={() => setDismissWarning(true)}
              className="text-slate-400 hover:text-slate-600 dark:hover:text-white text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 transition-colors"
              title="Dismiss banner"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md shadow-sm">
        {/* Live Service Health Strip */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
            title="Scoring engine status & loaded feature pipeline"
          >
            <div className={cn("w-2 h-2 rounded-full", health?.model.healthy ? "bg-emerald-500 animate-pulse" : "bg-red-500")} />
            <span className="font-bold text-slate-900 dark:text-white">Scoring Engine:</span>
            <span>XGBoost v{health?.model.version || "2.0.0"} (41 features, TreeSHAP)</span>
          </div>

          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
            title={health?.redpanda.mode || "Kafka / Redpanda message bus"}
          >
            <div className={cn("w-2 h-2 rounded-full", health?.redpanda.healthy ? "bg-emerald-500" : "bg-red-500 animate-pulse")} />
            <span className="font-bold text-slate-900 dark:text-white">Kafka:</span>
            <span>{health?.redpanda.healthy ? `Redpanda (${health.redpanda.partitions || 6} Partitions)` : "NOT KAFKA: In-Process"}</span>
          </div>

          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
            title={health?.redis.mode || "Redis fast state store"}
          >
            <div className={cn("w-2 h-2 rounded-full", health?.redis.healthy ? "bg-emerald-500" : "bg-amber-500")} />
            <span className="font-bold text-slate-900 dark:text-white">Redis:</span>
            <span>{health?.redis.healthy ? "Redis Server (port 6379)" : "In-Memory RESP (fakeredis)"}</span>
          </div>

          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
            title={health?.neo4j.mode || "Graph topology database"}
          >
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="font-bold text-slate-900 dark:text-white">Graph Store:</span>
            <span>In-Memory Topology (NetworkX)</span>
          </div>
        </div>

        {/* Right: Mode & Presenter Tools */}
        <div className="flex items-center gap-2">
          {/* Presenter Mode Toggle */}
          <button
            onClick={() => setPresenterMode(!presenterMode)}
            className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all"
            title="Toggle Presenter Mode (Large type, clean presentation)"
          >
            {presenterMode ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          2. DEMO STUDIO MODE SWITCHER
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 p-1.5 rounded-2xl bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-inner">
        <button
          onClick={() => setStudioMode("story")}
          className={cn(
            "flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl font-bold text-xs transition-all",
            studioMode === "story"
              ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/20"
              : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          )}
        >
          <PlayCircle className="w-4 h-4" />
          <span>Story Mode: The Four-Account Mule Ring (Deterministic)</span>
        </button>

        <button
          onClick={() => setStudioMode("live")}
          className={cn(
            "flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl font-bold text-xs transition-all",
            studioMode === "live"
              ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/20"
              : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
          )}
        >
          <Smartphone className="w-4 h-4" />
          <span>Live Sandbox Bank: Audience Participation (Real Phones)</span>
        </button>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MODE A: PHASE 12 LIVE SANDBOX ROOM CONTROLS STRIP
      ───────────────────────────────────────────────────────────── */}
      {studioMode === "live" && (
        <div className="p-4 rounded-2xl border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/50 dark:bg-indigo-950/20 backdrop-blur-md flex flex-wrap items-center justify-between gap-3 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-500">Active Room:</span>
              <span className="px-2.5 py-1 rounded-lg bg-indigo-600 text-white font-mono font-bold text-sm tracking-wider shadow-sm">
                {activeRoomCode}
              </span>
            </div>

            {/* Profile Badge */}
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs font-semibold"
              title="Demo sensitivity profile: >=3 senders in 5 min, >=70% pass-through ratio"
            >
              <Zap className="w-3.5 h-3.5" />
              <span>Demo Sensitivity Profile Active</span>
            </div>

            {/* Connected Participants Count */}
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-600 dark:text-emerald-400 text-xs font-semibold">
              <Users className="w-3.5 h-3.5" />
              <span>
                {liveRoomData?.participants_count || 0} Phones Connected • {liveRoomData?.bots_count || 3} Bots
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Show QR Button */}
            <button
              onClick={() => setShowQrModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs shadow-md transition-all"
            >
              <QrCode className="w-4 h-4" />
              <span>Show Join QR Code</span>
            </button>

            {/* Wipe Room */}
            <button
              onClick={handleWipeLiveRoom}
              className="flex items-center gap-1 px-3 py-1.5 rounded-xl border border-rose-300 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold transition-all"
              title="Clear all room data, Redis keys, and cases with zero residue"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Wipe Room</span>
            </button>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          3. MAIN THREE-PANEL STUDIO LAYOUT
      ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* ── LEFT PANEL (Story Narrator OR Live Audience Controls) ── */}
        <div className="lg:col-span-4 flex flex-col justify-between p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-4">
          {studioMode === "story" ? (
            /* STORY MODE CONTENT */
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">
                  Story Progression
                </span>
                <span className="text-xs font-mono font-medium text-slate-400">
                  Step {status?.current_index || 0} / {status?.total_events || 0}
                </span>
              </div>

              <div className="grid grid-cols-7 gap-1">
                {[1, 2, 3, 4, 5, 6, 7].map((num) => (
                  <div
                    key={num}
                    className={cn(
                      "h-1.5 rounded-full transition-all duration-300",
                      num < actNum
                        ? "bg-indigo-600"
                        : num === actNum
                        ? "bg-amber-500 animate-pulse"
                        : "bg-slate-200 dark:bg-slate-800"
                    )}
                  />
                ))}
              </div>

              <div className="space-y-1.5 pt-1">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                    Act {actNum}: {actInfo.badge}
                  </span>
                  <span className="text-xs font-mono text-slate-400">Seed {status?.seed || 42}</span>
                </div>
                <h2
                  className={cn(
                    "font-bold text-slate-900 dark:text-slate-100 tracking-tight",
                    presenterMode ? "text-2xl" : "text-lg"
                  )}
                >
                  {actInfo.title}
                </h2>
              </div>

              <div
                className={cn(
                  "p-4 rounded-xl border border-slate-100 dark:border-slate-800/80 bg-slate-50 dark:bg-slate-950/60 leading-relaxed text-slate-700 dark:text-slate-300 transition-all",
                  presenterMode ? "text-sm" : "text-xs"
                )}
              >
                {currentNarrative?.narrative || actInfo.subtitle}
              </div>

              {/* Ledger Impact Strip */}
              <div className="grid grid-cols-3 gap-2 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40">
                <div>
                  <p className="text-[10px] text-slate-400 font-medium">Money sent (virtual)</p>
                  <p className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
                    ₹{(status?.money_moved || 0).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-indigo-500 font-medium">Held for review</p>
                  <p className="font-mono text-sm font-bold text-indigo-600 dark:text-indigo-400">
                    ₹{(status?.money_held || 0).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-emerald-500 font-medium">Fraud loss prevented (virtual)</p>
                  <p className="font-mono text-sm font-bold text-emerald-600 dark:text-emerald-400">
                    ₹{(status?.money_saved || 0).toLocaleString()}
                  </p>
                </div>
              </div>

              {/* Side-by-side Protection Summary */}
              {(actNum >= 6 || status?.completed) && (
                <div className="p-3.5 rounded-xl border border-indigo-200 dark:border-indigo-800/80 bg-indigo-50/50 dark:bg-indigo-950/30 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-indigo-900 dark:text-indigo-200 flex items-center gap-1.5">
                      <ShieldCheck className="w-4 h-4 text-emerald-500" />
                      Outcome: Protection ON vs OFF
                    </span>
                    <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                      ₹46,000 Saved
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div className="p-2 rounded bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
                      <p className="font-semibold text-rose-600 dark:text-rose-400 flex items-center gap-1">
                        <ShieldOff className="w-3 h-3" /> Protection OFF
                      </p>
                      <p className="text-slate-500 text-[10px] mt-0.5">Authorizes blindly without blocklist.</p>
                      <p className="mt-1 font-mono font-bold text-rose-600">₹0 Saved (₹108k Lost)</p>
                    </div>
                    <div className="p-2 rounded bg-white dark:bg-slate-900 border border-emerald-500/30 bg-emerald-500/5">
                      <p className="font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                        <ShieldCheck className="w-3 h-3" /> Protection ON
                      </p>
                      <p className="text-slate-500 text-[10px] mt-0.5">Blocklist + Graph hold active.</p>
                      <p className="mt-1 font-mono font-bold text-emerald-600">₹46,000 Saved (₹46.5k Held)</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* LIVE SANDBOX AUDIENCE CONTENT */
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-indigo-600 dark:text-indigo-400">
                  Audience Participants
                </span>
                <span className="text-xs font-mono text-slate-400">
                  {liveRoomData?.participants_count || 0} Connected
                </span>
              </div>

              {/* Participants List & Network Label Assignment */}
              <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {(liveRoomData?.participants || [])
                  .filter((p: LiveParticipant) => !p.is_bot)
                  .map((p: LiveParticipant) => (
                    <div
                      key={p.account_id}
                      className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 flex items-center justify-between text-xs"
                    >
                      <div>
                        <div className="flex items-center gap-1.5 font-bold text-slate-900 dark:text-white">
                          <span>{p.display_name}</span>
                          <span
                            className={cn(
                              "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase border font-mono",
                              getStatusBadge(p.engine_status || "NORMAL")
                            )}
                          >
                            {p.engine_status || "NORMAL"}
                          </span>
                        </div>
                        <p className="text-[10px] font-mono text-slate-400">
                          ₹{p.balance.toLocaleString()} • {p.account_id}
                        </p>
                      </div>

                      {/* Network Label editor */}
                      <div className="flex items-center gap-1">
                        {editingNetworkUser === p.account_id ? (
                          <div className="flex items-center gap-1">
                            <input
                              type="text"
                              value={newNetworkLabel}
                              onChange={(e) => setNewNetworkLabel(e.target.value)}
                              placeholder="e.g. WiFi-A"
                              className="w-20 p-1 text-[10px] rounded border border-slate-700 bg-slate-900 text-white font-mono"
                            />
                            <button
                              onClick={() => handleSaveNetworkLabel(p.account_id)}
                              className="p-1 rounded bg-indigo-600 text-white"
                            >
                              <Check className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => {
                              setEditingNetworkUser(p.account_id);
                              setNewNetworkLabel(p.network_label);
                            }}
                            className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-300 dark:hover:bg-slate-700 transition-all flex items-center gap-1"
                            title="Click to simulate different network/IP subnet"
                          >
                            <Wifi className="w-2.5 h-2.5" />
                            <span>{p.network_label}</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ))}

                {(liveRoomData?.participants_count || 0) === 0 && (
                  <div className="p-4 text-center text-xs text-slate-400 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
                    <Smartphone className="w-5 h-5 mx-auto text-slate-500" />
                    <p>No audience phones connected yet.</p>
                    <p className="text-[10px] text-indigo-400 font-semibold cursor-pointer" onClick={() => setShowQrModal(true)}>
                      Click 'Show Join QR Code' to scan!
                    </p>
                  </div>
                )}
              </div>

              {/* Analyst Case Queue */}
              <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                    <ShieldAlert className="w-4 h-4 text-amber-500" />
                    Analyst Case Review Queue
                  </span>
                  <span className="text-[10px] font-mono text-slate-400">
                    {liveCases.length} pending
                  </span>
                </div>

                <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                  {liveCases.map((c) => (
                    <div
                      key={c.case_id}
                      className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/5 space-y-2 text-xs"
                    >
                      <div className="flex items-center justify-between font-bold">
                        <span>
                          {c.sender_display} -&gt; {c.receiver_display}
                        </span>
                        <span className="font-mono text-amber-600 dark:text-amber-400">
                          ₹{c.amount.toLocaleString()}
                        </span>
                      </div>
                      <p className="text-[10px] text-slate-500 dark:text-slate-400">
                        {c.decision?.summary || "Triggered demo sensitivity thresholds."}
                      </p>

                      <div className="flex items-center gap-2 pt-1">
                        <button
                          onClick={() => handleApproveCase(c.case_id)}
                          disabled={isActionLoading === c.case_id}
                          className="flex-1 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-[10px] shadow-sm transition-all"
                        >
                          Approve & Settle
                        </button>
                        <button
                          onClick={() => handleBlockCase(c.case_id)}
                          disabled={isActionLoading === c.case_id}
                          className="flex-1 py-1 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-bold text-[10px] shadow-sm transition-all"
                        >
                          Block & Freeze Ring
                        </button>
                      </div>
                    </div>
                  ))}

                  {liveCases.length === 0 && (
                    <p className="text-slate-400 text-[11px] italic text-center py-2">
                      No payments need review right now
                    </p>
                  )}
                </div>
              </div>

              {/* Live Ledger Strip */}
              <div className="grid grid-cols-3 gap-2 p-3 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40">
                <div>
                  <p className="text-[10px] text-slate-400 font-medium">Money sent (virtual)</p>
                  <p className="font-mono text-sm font-bold text-slate-900 dark:text-slate-100">
                    ₹{(liveRoomData?.money_moved || 0).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-indigo-500 font-medium">Held for review</p>
                  <p className="font-mono text-sm font-bold text-indigo-600 dark:text-indigo-400">
                    ₹{(liveRoomData?.money_held || 0).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] text-emerald-500 font-medium">Fraud loss prevented (virtual)</p>
                  <p className="font-mono text-sm font-bold text-emerald-600 dark:text-emerald-400">
                    ₹{(liveRoomData?.money_saved || 0).toLocaleString()}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Story Controls (Only visible in story mode) */}
          {studioMode === "story" && (
            <div className="space-y-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <button
                  onClick={togglePlay}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl font-bold text-xs transition-all shadow-sm",
                    status?.is_running
                      ? "bg-amber-600 text-white hover:bg-amber-700"
                      : "bg-indigo-600 text-white hover:bg-indigo-700"
                  )}
                >
                  {status?.is_running ? (
                    <>
                      <Pause className="w-4 h-4 fill-current" />
                      <span>Pause Story</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>Play Live Demo</span>
                    </>
                  )}
                </button>

                <button
                  onClick={stepDemo}
                  disabled={status?.is_running}
                  className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 text-xs font-semibold"
                  title="Advance exactly 1 pipeline event [Right Arrow]"
                >
                  <ArrowRight className="w-4 h-4" />
                  <span>Next Step</span>
                </button>

                <button
                  onClick={() => resetDemo()}
                  className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="Reset simulation to initial state with zero residue"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>

              {/* Speed Selector */}
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" /> Speed:
                </span>
                <div className="flex items-center gap-1">
                  {[0.5, 1.0, 2.0, 5.0].map((spd) => (
                    <button
                      key={spd}
                      onClick={() => handleControl("speed", spd)}
                      className={cn(
                        "px-2 py-0.5 rounded font-mono text-[10px] font-semibold transition-all",
                        status?.speed === spd
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200"
                      )}
                    >
                      {spd}x
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── CENTER PANEL (Live Money Flow Graph or Story Entity Linkage Graph) ── */}
        <div className="lg:col-span-5 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm flex flex-col justify-between">
          <div className="flex flex-wrap items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800 gap-2">
            <div className="flex items-center gap-2">
              <Network className="w-4 h-4 text-indigo-500" />
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 tracking-tight">
                  {studioMode === "story" ? "Entity Linkage Graph (Story)" : "Live Money Flow Graph"}
                </h3>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">
                  Who is sending money to whom
                </p>
              </div>
            </div>

            {studioMode === "live" ? (
              <label className="flex items-center gap-1.5 cursor-pointer text-xs font-semibold text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
                <input
                  type="checkbox"
                  checked={showDevicesAndNetworks}
                  onChange={(e) => setShowDevicesAndNetworks(e.target.checked)}
                  className="rounded border-slate-400 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                />
                <span>Show devices and networks</span>
              </label>
            ) : (
              <div className="flex items-center gap-2 text-[10px] font-mono text-slate-400">
                <span>{graphElements.nodes.length} Nodes</span>
                <span>•</span>
                <span>{graphElements.edges.length} Edges</span>
              </div>
            )}
          </div>

          {/* Graph Viewport */}
          <div className="relative my-2">
            {studioMode === "live" ? (
              <LiveMoneyFlowGraph
                participants={liveRoomData?.participants || []}
                transfers={liveRoomData?.recent_transfers || []}
                showDevicesAndNetworks={showDevicesAndNetworks}
                onSelectParticipant={(node) => setSelectedParticipantNode(node)}
                height={presenterMode ? "480px" : "380px"}
              />
            ) : (
              <div className="rounded-xl overflow-hidden border border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-950/40">
                <CytoscapeGraph
                  elements={graphElements}
                  centerId="CUST_MULE_A"
                  height={presenterMode ? "480px" : "360px"}
                />
              </div>
            )}

            {/* Selected Node Inspector Side Card */}
            {selectedParticipantNode && (
              <div className="absolute top-3 right-3 z-30 w-72 p-3.5 rounded-2xl bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border border-slate-200 dark:border-slate-700 shadow-xl space-y-2 text-xs">
                <div className="flex items-start justify-between">
                  <div>
                    <h4 className="font-bold text-sm text-slate-900 dark:text-white">
                      {selectedParticipantNode.display_name}
                    </h4>
                    <p className="font-mono text-[10px] text-slate-400">{selectedParticipantNode.account_id}</p>
                  </div>
                  <button
                    onClick={() => setSelectedParticipantNode(null)}
                    className="text-slate-400 hover:text-slate-600 dark:hover:text-white text-xs font-bold p-1"
                  >
                    ✕
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-1.5 p-2 rounded-xl bg-slate-50 dark:bg-slate-950/60 font-mono text-[11px]">
                  <div>
                    <span className="text-[10px] text-slate-400 block">Balance</span>
                    <span className="font-bold text-slate-800 dark:text-slate-200">
                      ₹{selectedParticipantNode.balance.toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Fan-In (5 min)</span>
                    <span className="font-bold text-indigo-600 dark:text-indigo-400">
                      {selectedParticipantNode.fan_in_count || 0} senders
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Received (Inflow)</span>
                    <span className="font-bold text-emerald-600">
                      ₹{(selectedParticipantNode.inflow || 0).toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Sent (Outflow)</span>
                    <span className="font-bold text-amber-600">
                      ₹{(selectedParticipantNode.outflow || 0).toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="space-y-1 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Pass-Through:</span>
                    <span className="font-mono font-semibold">
                      {((selectedParticipantNode.pass_through || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Device ID:</span>
                    <span
                      className="font-mono text-[10px] text-slate-600 dark:text-slate-400 truncate max-w-[120px]"
                      title={selectedParticipantNode.device_id}
                    >
                      {(selectedParticipantNode.device_id || "DEV_BROWSER").slice(0, 12)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Network Prefix:</span>
                    <span className="font-mono text-[10px] text-slate-600 dark:text-slate-400">
                      {selectedParticipantNode.masked_ip || selectedParticipantNode.network_prefix || "192.168.1.x"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Network Label:</span>
                    <span className="font-mono text-[10px] text-slate-600 dark:text-slate-400">
                      {selectedParticipantNode.network_label} {selectedParticipantNode.is_simulated_network ? "(simulated network)" : ""}
                    </span>
                  </div>
                  <div className="flex items-center justify-between pt-1 border-t border-slate-100 dark:border-slate-800">
                    <span className="text-slate-500 font-semibold">Engine Status:</span>
                    <span
                      className={cn(
                        "text-[10px] font-bold px-1.5 py-0.5 rounded uppercase border font-mono",
                        getStatusBadge(selectedParticipantNode.engine_status)
                      )}
                    >
                      {selectedParticipantNode.engine_status}
                    </span>
                  </div>
                </div>

                {selectedParticipantNode.reasons && selectedParticipantNode.reasons.length > 0 && (
                  <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-[10px] text-amber-700 dark:text-amber-300">
                    <span className="font-bold block">Engine Notes:</span>
                    {selectedParticipantNode.reasons.join(", ")}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Plain-English Ticker Under Graph */}
          <div className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-950/80 backdrop-blur-sm flex items-center gap-2 font-mono text-xs shadow-sm">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse flex-shrink-0" />
            <span className="text-[10px] uppercase font-bold text-slate-400 flex-shrink-0">Live Stream:</span>
            <span className="text-slate-800 dark:text-slate-200 truncate font-semibold">
              {getTickerText()}
            </span>
          </div>

          {/* Story Legend Strip (when in story mode) */}
          {studioMode === "story" && (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 text-[10px] text-slate-500 border-t border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
                <span>Blocked</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                <span>Held via Graph</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                <span>Normal / Monitored</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-sm bg-purple-500" />
                <span>Device</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-sm bg-cyan-500" />
                <span>Network / Subnet</span>
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT PANEL ("Under the Hood" Real Pipeline Tabs) ───── */}
        <div className="lg:col-span-3 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm flex flex-col justify-between">
          <div className="space-y-3">
            {/* Tabs Header */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-800">
              <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                Under The Hood
              </span>
              <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-[10px] font-medium">
                {(["decision", "kafka", "redis", "graph_query"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={cn(
                      "px-2 py-1 rounded transition-all",
                      activeTab === tab
                        ? "bg-white dark:bg-slate-900 text-indigo-600 dark:text-indigo-400 font-bold shadow-sm"
                        : "text-slate-500 hover:text-slate-900 dark:hover:text-slate-100"
                    )}
                  >
                    {tab === "graph_query" ? "Graph query" : tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </button>
                ))}
              </div>
            </div>

            {/* TAB CONTENT: DECISION (Item 6) */}
            {activeTab === "decision" && (
              <div className="space-y-3.5">
                {/* Presenter Demo Layer Toggles */}
                <div className="flex items-center justify-between p-2 rounded-xl bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-xs">
                  <span className="font-bold text-slate-700 dark:text-slate-300 text-[11px]">Layer Controls:</span>
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => toggleLayer("rules")}
                      className={cn(
                        "px-2 py-0.5 rounded font-mono text-[10px] font-bold transition-all border",
                        rulesEnabled
                          ? "bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/40"
                          : "bg-slate-200 dark:bg-slate-800 text-slate-400 border-transparent opacity-60"
                      )}
                      title="Toggle Rules Engine ON or OFF"
                    >
                      Rules: {rulesEnabled ? "ON" : "OFF"}
                    </button>
                    <button
                      onClick={() => toggleLayer("model")}
                      className={cn(
                        "px-2 py-0.5 rounded font-mono text-[10px] font-bold transition-all border",
                        modelEnabled
                          ? "bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 border-indigo-500/40"
                          : "bg-slate-200 dark:bg-slate-800 text-slate-400 border-transparent opacity-60"
                      )}
                      title="Toggle XGBoost ML Model ON or OFF"
                    >
                      Model: {modelEnabled ? "ON" : "OFF"}
                    </button>
                  </div>
                </div>

                {/* Detection Source Chip & Decision Tier */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-slate-500 font-medium">Detection Source:</span>
                    <span
                      className={cn(
                        "text-[10px] font-bold px-2 py-0.5 rounded-full font-mono uppercase border",
                        latestDecision.detection_source === "Both" && "bg-purple-500/20 text-purple-600 dark:text-purple-300 border-purple-500/30",
                        latestDecision.detection_source === "Rule" && "bg-amber-500/20 text-amber-600 dark:text-amber-300 border-amber-500/30",
                        latestDecision.detection_source === "Model" && "bg-blue-500/20 text-blue-600 dark:text-blue-300 border-blue-500/30",
                        (!latestDecision.detection_source || latestDecision.detection_source === "Normal") && "bg-emerald-500/20 text-emerald-600 dark:text-emerald-300 border-emerald-500/30"
                      )}
                    >
                      {latestDecision.detection_source || "Normal"}
                    </span>
                  </div>
                  <span
                    className={cn(
                      "text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                      latestDecision.tier === "BLOCK" && "bg-red-500/20 text-red-500",
                      latestDecision.tier === "REVIEW" && "bg-amber-500/20 text-amber-500",
                      latestDecision.tier === "ALLOW" && "bg-emerald-500/20 text-emerald-500"
                    )}
                  >
                    Tier: {latestDecision.tier}
                  </span>
                </div>

                {/* Layer 1: Heuristic Rules Evaluation */}
                <div className="p-3 rounded-xl border border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-950/40 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">1. Heuristic Rule Hits</span>
                    <span className="text-[10px] font-mono text-slate-400">
                      {rulesEnabled ? `${latestDecision.rule_hits?.length || 0} hits` : "DISABLED"}
                    </span>
                  </div>
                  {!rulesEnabled ? (
                    <p className="text-[11px] text-amber-500 italic">Rules disabled by demo toggle</p>
                  ) : latestDecision.rule_hits && latestDecision.rule_hits.length > 0 ? (
                    <div className="space-y-1">
                      {latestDecision.rule_hits.map((rh: any, i: number) => (
                        <div key={i} className="flex items-center justify-between text-[11px] p-1.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-300">
                          <span className="font-semibold">{rh.name || rh.rule_id}</span>
                          <span className="font-mono text-[9px] uppercase px-1 rounded bg-amber-500/20">{rh.severity}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 italic">No heuristic rules fired for this transfer.</p>
                  )}
                </div>

                {/* Layer 2: XGBoost ML Model Score */}
                <div className="p-3 rounded-xl border border-slate-100 dark:border-slate-800/80 bg-slate-50/50 dark:bg-slate-950/40 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">2. XGBoost Model Score</span>
                    <span className="text-[10px] text-slate-400 font-mono">
                      {latestDecision.latency_ms !== undefined ? `${latestDecision.latency_ms.toFixed(2)} ms latency` : ""}
                    </span>
                  </div>
                  {!modelEnabled ? (
                    <p className="text-[11px] text-indigo-500 italic">Model scoring disabled by demo toggle</p>
                  ) : (
                    <>
                      <div className="flex items-baseline gap-2">
                        <span className="text-3xl font-black font-mono tracking-tight text-slate-900 dark:text-slate-100">
                          {((latestDecision.model_score ?? latestDecision.score ?? 0) * 100).toFixed(2)}%
                        </span>
                        <span className="text-[10px] text-slate-400 font-mono">
                          (prob: {(latestDecision.model_score ?? latestDecision.score ?? 0).toFixed(4)})
                        </span>
                      </div>
                      <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                        <div
                          className={cn(
                            "h-full transition-all duration-500",
                            (latestDecision.model_score ?? latestDecision.score) >= 0.7
                              ? "bg-red-500"
                              : (latestDecision.model_score ?? latestDecision.score) >= 0.3
                              ? "bg-amber-500"
                              : "bg-emerald-500"
                          )}
                          style={{ width: `${Math.min(100, Math.max(2, (latestDecision.model_score ?? latestDecision.score ?? 0) * 100))}%` }}
                        />
                      </div>
                    </>
                  )}
                </div>

                {/* Plain-English Explanation Reason Cards */}
                <div className="space-y-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    Reason Cards (SHAP & Fusion)
                  </span>
                  <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                    {latestDecision.reasons?.length > 0 ? (
                      latestDecision.reasons.map((r: any, idx: number) => (
                        <div
                          key={idx}
                          className="p-2 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 text-xs space-y-0.5"
                        >
                          <div className="flex items-center justify-between font-bold text-slate-800 dark:text-slate-200">
                            <span>{r.title}</span>
                            <span className="text-[10px] font-mono text-indigo-500">{r.feature}</span>
                          </div>
                          <p className="text-[11px] text-slate-500 leading-snug">{r.description || r.explanation}</p>
                        </div>
                      ))
                    ) : (
                      <p className="text-slate-400 text-xs italic">Activity matches baseline customer behavior.</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* TAB CONTENT: KAFKA */}
            {activeTab === "kafka" && (
              <div className="space-y-2">
                <span className="text-[10px] font-bold uppercase text-slate-400">Live Partition Feed</span>
                <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 font-mono text-[10px]">
                  {kafkaFeed.length > 0 ? (
                    kafkaFeed.map((msg, idx) => (
                      <div
                        key={idx}
                        className="p-2 rounded bg-slate-100 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 space-y-1"
                      >
                        <div className="flex items-center justify-between text-indigo-600 dark:text-indigo-400 font-bold">
                          <span>{msg.topic || "transactions"}</span>
                          <span>P:{msg.partition} • O:{msg.offset}</span>
                        </div>
                        <p className="text-slate-500 truncate">{JSON.stringify(msg.payload || msg)}</p>
                      </div>
                    ))
                  ) : (
                    <p className="text-slate-400 text-xs italic">Awaiting Kafka messages...</p>
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT: REDIS */}
            {activeTab === "redis" && (
              <div className="space-y-2">
                <span className="text-[10px] font-bold uppercase text-slate-400">Live Key Mutations</span>
                <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1 font-mono text-[10px]">
                  {redisDeltas.length > 0 ? (
                    redisDeltas.map((delta, idx) => (
                      <div
                        key={idx}
                        className="p-2 rounded bg-slate-100 dark:bg-slate-950/80 border border-slate-200 dark:border-slate-800 space-y-0.5"
                      >
                        <div className="flex items-center justify-between text-amber-600 dark:text-amber-400">
                          <span className="truncate">{delta.key.replace("demo:mule:", "").replace("live:sandbox:", "")}</span>
                          <span className="uppercase text-[9px] font-bold">{delta.operation}</span>
                        </div>
                        <p className="text-slate-500 truncate">
                          <span className="line-through text-slate-400 mr-1">
                            {typeof delta.before === "object" ? JSON.stringify(delta.before) : String(delta.before)}
                          </span>
                          -&gt;{" "}
                          <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                            {typeof delta.after === "object" ? JSON.stringify(delta.after) : String(delta.after)}
                          </span>
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="text-slate-400 text-xs italic">No Redis mutations logged yet.</p>
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT: GRAPH QUERY */}
            {activeTab === "graph_query" && (
              <div className="space-y-2">
                <div>
                  <span className="text-[10px] font-bold uppercase text-slate-400">Graph Query</span>
                  <p className="text-[11px] text-slate-500">Who is sending money to whom</p>
                </div>
                <pre className="p-2.5 rounded-lg bg-slate-950 text-emerald-400 font-mono text-[10px] leading-relaxed overflow-x-auto whitespace-pre-wrap border border-slate-800 max-h-72">
                  {lastCypherQuery}
                </pre>
              </div>
            )}
          </div>

          <p className="text-[10px] text-slate-400 pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span>Deterministic seed {status?.seed || 42} • Wall-clock latency recorded</span>
          </p>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          QR CODE MODAL FOR AUDIENCE JOINING
      ───────────────────────────────────────────────────────────── */}
      {showQrModal && joinInfo && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 max-w-sm w-full shadow-2xl space-y-4 text-center">
            <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <Smartphone className="w-5 h-5 text-indigo-600" />
                <h3 className="font-bold text-sm text-slate-900 dark:text-white">
                  Join Live Sandbox Bank
                </h3>
              </div>
              <button
                onClick={() => setShowQrModal(false)}
                className="text-slate-400 hover:text-white text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <div className="p-4 bg-white rounded-2xl border border-slate-200 inline-block shadow-inner mx-auto">
              <QRCodeSVG
                value={effectiveJoinUrl || joinInfo.join_url}
                size={210}
                level="M"
                includeMargin={false}
              />
            </div>

            <div className="space-y-2">
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                <Globe className="w-3.5 h-3.5" />
                <span>Join from ANY Network (Cellular 4G/5G, Mobile Data or Wi-Fi)</span>
              </div>
              <p className="text-xs text-slate-600 dark:text-slate-300">
                Scan with any smartphone camera from anywhere in the world. No shared local Wi-Fi required!
              </p>
              <div className="flex items-center gap-1.5 p-2 rounded-xl bg-slate-100 dark:bg-slate-800 text-[11px] font-mono justify-between">
                <span className="truncate text-slate-700 dark:text-slate-300">
                  {effectiveJoinUrl || joinInfo.join_url}
                </span>
                <button
                  onClick={copyJoinUrl}
                  className="p-1 rounded text-slate-500 hover:text-indigo-400"
                  title="Copy URL"
                >
                  {copiedUrl ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            <button
              onClick={() => setShowQrModal(false)}
              className="w-full py-2.5 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 font-bold text-xs text-slate-700 dark:text-slate-200 transition-all"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          "TRY IT YOURSELF" INTERACTIVE MODAL (STORY MODE)
      ───────────────────────────────────────────────────────────── */}
      {showTransferModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <Send className="w-5 h-5 text-indigo-600" />
                <h3 className="font-bold text-base text-slate-900 dark:text-slate-100">
                  Try It Yourself: Interactive Bank Transfer
                </h3>
              </div>
              <button
                onClick={() => setShowTransferModal(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-sm font-bold"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-500">
              Send a payment through the live engine to test real pre-scoring blocklists, velocity features, and XGBoost scoring.
            </p>

            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setIsSubmittingTransfer(true);
                try {
                  const res = await fetch("/api/v1/demo/transfer", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      from_account: transferFrom,
                      to_account: transferTo,
                      amount: Number(transferAmount),
                    }),
                  });
                  if (res.ok) {
                    const data = await res.json();
                    setTransferResult(data);
                    if (data.totals) {
                      setStatus((prev) => (prev ? { ...prev, ...data.totals } : null));
                    }
                  }
                } catch (err) {}
                setIsSubmittingTransfer(false);
              }}
              className="space-y-3"
            >
              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">From Account</label>
                <select
                  value={transferFrom}
                  onChange={(e) => setTransferFrom(e.target.value)}
                  className="w-full mt-1 p-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-xs font-mono"
                >
                  <option value="CUST_MULE_D">Member D (Held via graph containment)</option>
                  <option value="CUST_MULE_A">Member A (Primary confirmed blocked)</option>
                  <option value="CUST_INNOCENT_HOUSEHOLD">Innocent Neighbor (Monitored IP)</option>
                  <option value="CUST_NORM_01">Normal Customer 01 (Clean account)</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">To Payee</label>
                <select
                  value={transferTo}
                  onChange={(e) => setTransferTo(e.target.value)}
                  className="w-full mt-1 p-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-xs font-mono"
                >
                  <option value="MERCHANT_CRYPTO_EXCHANGE">External Crypto Exchange (Cash-Out)</option>
                  <option value="MERCHANT_GROCERY_99">Everyday Supermarket</option>
                  <option value="CUST_MULE_B">Member B</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">Amount (₹)</label>
                <input
                  type="number"
                  value={transferAmount}
                  onChange={(e) => setTransferAmount(Number(e.target.value))}
                  className="w-full mt-1 p-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-xs font-mono"
                />
              </div>

              <button
                type="submit"
                disabled={isSubmittingTransfer}
                className="w-full py-2.5 rounded-xl font-bold text-xs bg-indigo-600 text-white hover:bg-indigo-700 transition-all shadow-md disabled:opacity-50"
              >
                {isSubmittingTransfer ? "Scoring via Pipeline..." : "Execute Real Transfer"}
              </button>
            </form>

            {transferResult && (
              <div
                className={cn(
                  "p-3 rounded-xl border text-xs space-y-1.5",
                  transferResult.decision?.tier === "BLOCK"
                    ? "bg-red-500/10 border-red-500/20 text-red-700 dark:text-red-300"
                    : "bg-emerald-500/10 border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
                )}
              >
                <div className="flex items-center justify-between font-bold">
                  <span>Decision: {transferResult.decision?.tier}</span>
                  <span className="font-mono text-[10px]">{transferResult.decision?.latency_ms?.toFixed(2)} ms</span>
                </div>
                <p className="text-[11px]">{transferResult.decision?.summary}</p>
                <p className="text-[10px] font-semibold">Ledger Action: {transferResult.ledger?.status}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          FOOTER: STATUS & DECISION TIME
      ───────────────────────────────────────────────────────────── */}
      <div className="py-2.5 px-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/60 backdrop-blur-sm text-center text-xs font-mono text-slate-500 dark:text-slate-400 flex items-center justify-center gap-3 shadow-sm">
        <span>Bots: seed 42</span>
        <span>|</span>
        <span>People: live</span>
        <span>|</span>
        <span>
          Decision time: {latestDecision?.latency_ms ? Math.round(latestDecision.latency_ms) : 14} ms
        </span>
      </div>
    </div>
  );
};
