import React, { useEffect, useState } from "react";
import {
  AlertTriangle,
  Flame,
  Layers,
  Pause,
  Play,
  PlayCircle,
  Repeat,
  ShieldAlert,
  Smartphone,
  Sparkles,
  Zap,
} from "lucide-react";
import { fetchSimulatorStatus, injectScenario, triggerSimulatorControl } from "../lib/api";

const INJECTION_OPTIONS = [
  {
    type: "burst_takeover",
    title: "Burst Account Takeover",
    description: "Account compromised via credential stuffing; sends 15 rapid transfers to mules within 90 minutes.",
    icon: Flame,
    color: "text-rose-500",
    bg: "bg-rose-500/10 border-rose-500/20",
  },
  {
    type: "mule_fanin_fanout",
    title: "Mule Ring (Fan-In / Fan-Out)",
    description: "22 victims deposit funds into a single mule account; 88% is forwarded to a collector within 4 hours.",
    icon: Repeat,
    color: "text-orange-500",
    bg: "bg-orange-500/10 border-orange-500/20",
  },
  {
    type: "shared_device_ring",
    title: "Shared Device Identity Ring",
    description: "8 separate synthetic customer identities transacting layered funds through 1 physical mobile hardware device.",
    icon: Smartphone,
    color: "text-purple-500",
    bg: "bg-purple-500/10 border-purple-500/20",
  },
  {
    type: "structuring",
    title: "Smurfing / Structuring",
    description: "Multiple transactions between ₹48,000–₹49,500 intentionally structured just under the ₹50,000 reporting limit.",
    icon: Layers,
    color: "text-indigo-500",
    bg: "bg-indigo-500/10 border-indigo-500/20",
  },
  {
    type: "dormant_reactivation",
    title: "Dormant Reactivation",
    description: "Account inactive for 68 days suddenly transfers ₹75,000 to an unknown beneficiary from a new IP prefix.",
    icon: Zap,
    color: "text-amber-500",
    bg: "bg-amber-500/10 border-amber-500/20",
  },
];

export const Simulator: React.FC = () => {
  const [status, setStatus] = useState<any>(null);
  const [speed, setSpeed] = useState(1);
  const [injecting, setInjecting] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const loadStatus = () => {
    fetchSimulatorStatus().then(setStatus);
  };

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 2500);
    return () => clearInterval(interval);
  }, []);

  const handleToggle = async () => {
    const action = status?.is_running ? "stop" : "start";
    const res = await triggerSimulatorControl(action);
    setStatus(res);
  };

  const handleInject = async (type: string) => {
    setInjecting(type);
    const res = await injectScenario(type);
    setToastMessage(res.message);
    setTimeout(() => setToastMessage(null), 4000);
    setInjecting(null);
    loadStatus();
  };

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="pb-2 border-b border-slate-200 dark:border-slate-800">
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
          <PlayCircle className="w-5 h-5 text-indigo-500" />
          <span>Interactive Replay & Scenario Injection Control</span>
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Control live transaction replay across the test split and inject realistic fraud attack scenarios on demand.
        </p>
      </div>

      {toastMessage && (
        <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 text-xs font-semibold flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Simulator Control Dashboard */}
      <div className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={handleToggle}
              className={`px-5 py-2.5 rounded-lg text-xs font-bold text-white transition-all flex items-center gap-2 shadow-sm ${
                status?.is_running
                  ? "bg-amber-600 hover:bg-amber-700 shadow-amber-600/30"
                  : "bg-indigo-600 hover:bg-indigo-700 shadow-indigo-600/30"
              }`}
            >
              {status?.is_running ? (
                <>
                  <Pause className="w-4 h-4" />
                  <span>Pause Stream Replay</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  <span>Start Stream Replay</span>
                </>
              )}
            </button>
            <span className="text-xs text-slate-500">
              Status:{" "}
              <strong className={status?.is_running ? "text-emerald-500" : "text-slate-400"}>
                {status?.is_running ? "Active (Streaming Events)" : "Paused"}
              </strong>
            </span>
          </div>

          {/* Speed Multiplier */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-500">Speed:</span>
            {[1, 5, 20, 50].map((s) => (
              <button
                key={s}
                onClick={() => setSpeed(s)}
                className={`px-2.5 py-1 rounded text-xs font-semibold ${
                  speed === s
                    ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>

        {/* Live Replay Counters */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-slate-100 dark:border-slate-800">
          <div>
            <p className="text-xs text-slate-400">Events Replayed</p>
            <p className="text-xl font-bold font-mono text-slate-900 dark:text-slate-100 mt-0.5">
              {status?.events_replayed?.toLocaleString() ?? "12,450"}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Alerts Triggered</p>
            <p className="text-xl font-bold font-mono text-orange-500 mt-0.5">
              {status?.alerts_generated?.toLocaleString() ?? "412"}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Injected Attacks</p>
            <p className="text-xl font-bold font-mono text-rose-500 mt-0.5">
              {status?.injected_count ?? 5}
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-400">Sim Step</p>
            <p className="text-xl font-bold font-mono text-indigo-500 mt-0.5">
              {status?.current_step ?? 642}h
            </p>
          </div>
        </div>
      </div>

      {/* 1-Click Scenario Injectors */}
      <div className="space-y-3">
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight">
            One-Click Synthetic Scenario Injectors
          </h3>
          <p className="text-xs text-slate-500">
            Click any attack scenario below to immediately inject it into the live scoring engine and observe alert trigger.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {INJECTION_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            return (
              <div
                key={opt.type}
                className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm flex flex-col justify-between space-y-4"
              >
                <div className="flex items-start gap-3.5">
                  <div className={`p-2.5 rounded-xl border shrink-0 ${opt.bg}`}>
                    <Icon className={`w-5 h-5 ${opt.color}`} />
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-900 dark:text-slate-100">
                      {opt.title}
                    </h4>
                    <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 leading-relaxed">
                      {opt.description}
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => handleInject(opt.type)}
                  disabled={injecting === opt.type}
                  className="w-full py-2 rounded-lg text-xs font-semibold bg-slate-100 dark:bg-slate-800 hover:bg-indigo-600 hover:text-white transition-colors text-slate-700 dark:text-slate-200 disabled:opacity-50 flex items-center justify-center gap-1.5"
                >
                  <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
                  <span>{injecting === opt.type ? "Injecting Attack..." : `Inject ${opt.title}`}</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
