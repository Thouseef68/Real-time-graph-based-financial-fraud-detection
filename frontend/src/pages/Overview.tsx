import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  ShieldAlert,
  Zap,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchAlerts, fetchKPIs } from "../lib/api";
import { formatCurrency, formatPercent } from "../lib/utils";
import { RiskBadge } from "../components/common/RiskBadge";

const SCENARIO_DISTRIBUTION = [
  { name: "Mule Fan-In", count: 98, color: "#EF4444" },
  { name: "Burst Takeover", count: 84, color: "#F97316" },
  { name: "Device Ring", count: 72, color: "#F59E0B" },
  { name: "Structuring", count: 64, color: "#6366F1" },
  { name: "Dormant React.", count: 48, color: "#8B5CF6" },
  { name: "Native Drain", count: 46, color: "#EC4899" },
];

const ALERTS_TREND = [
  { time: "09:00", alerts: 14, blocked: 8 },
  { time: "10:00", alerts: 22, blocked: 12 },
  { time: "11:00", alerts: 35, blocked: 20 },
  { time: "12:00", alerts: 48, blocked: 29 },
  { time: "01:00", alerts: 31, blocked: 18 },
  { time: "02:00", alerts: 54, blocked: 34 },
  { time: "03:00", alerts: 42, blocked: 26 },
];

export const Overview: React.FC = () => {
  const [kpis, setKpis] = useState<any>(null);
  const [recentAlerts, setRecentAlerts] = useState<any[]>([]);

  useEffect(() => {
    fetchKPIs().then(setKpis);
    fetchAlerts({ size: 5 }).then((data: any) => setRecentAlerts(data.items));
  }, []);

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">
            Security & Fraud Operations Center
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Real-time graph analytics, behavioural profiling, and anomaly scoring stream.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            to="/simulator"
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 transition-colors shadow-sm shadow-indigo-600/30"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Open Demo Simulator</span>
          </Link>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {/* Total Scored */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Scored Txns</span>
            <Activity className="w-4 h-4 text-indigo-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-slate-900 dark:text-slate-100 tabular-nums">
            {kpis?.total_transactions_scored?.toLocaleString() ?? "104,850"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">100% evaluated live</p>
        </div>

        {/* Total Alerts */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Total Alerts</span>
            <AlertTriangle className="w-4 h-4 text-orange-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-slate-900 dark:text-slate-100 tabular-nums">
            {kpis?.total_alerts?.toLocaleString() ?? "412"}
          </p>
          <p className="text-[11px] text-emerald-600 font-medium mt-1">
            {kpis ? formatPercent(kpis.alert_rate) : "0.39%"} alert rate
          </p>
        </div>

        {/* Blocked Cases */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Blocked</span>
            <ShieldAlert className="w-4 h-4 text-rose-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-rose-600 dark:text-rose-400 tabular-nums">
            {kpis?.blocked_alerts?.toLocaleString() ?? "184"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">High confidence fraud</p>
        </div>

        {/* Pending Review */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Open Queue</span>
            <Clock className="w-4 h-4 text-amber-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-slate-900 dark:text-slate-100 tabular-nums">
            {kpis?.open_alerts?.toLocaleString() ?? "28"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">Awaiting analyst action</p>
        </div>

        {/* Amount Held */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">Amount Held</span>
            <DollarSign className="w-4 h-4 text-emerald-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-slate-900 dark:text-slate-100 tabular-nums">
            {kpis ? formatCurrency(kpis.amount_held_or_blocked) : "₹1.24 Cr"}
          </p>
          <p className="text-[11px] text-slate-500 mt-1">Protected customer funds</p>
        </div>

        {/* Latency */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between text-slate-400">
            <span className="text-xs font-medium">p95 Latency</span>
            <Zap className="w-4 h-4 text-indigo-500" />
          </div>
          <p className="text-xl font-bold mt-2 text-slate-900 dark:text-slate-100 tabular-nums">
            0.08 ms
          </p>
          <p className="text-[11px] text-emerald-600 font-medium mt-1">&lt; 100 ms target met</p>
        </div>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trend Line Chart */}
        <div className="lg:col-span-2 p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Alerts & Mitigations Over Time
              </h3>
              <p className="text-xs text-slate-500">Hourly alerts volume and automatic blocks</p>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-600" /> Total Alerts
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-rose-500" /> Auto-Blocked
              </span>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={ALERTS_TREND} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="time" stroke="#94A3B8" fontSize={11} tickLine={false} />
                <YAxis stroke="#94A3B8" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="alerts"
                  stroke="#4F46E5"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  name="Alerts"
                />
                <Line
                  type="monotone"
                  dataKey="blocked"
                  stroke="#EF4444"
                  strokeWidth={2.5}
                  dot={{ r: 3 }}
                  name="Blocked"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Scenario Distribution Bar Chart */}
        <div className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Detected Fraud Patterns
          </h3>
          <p className="text-xs text-slate-500 mb-4">Breakdown across synthetic & native patterns</p>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={SCENARIO_DISTRIBUTION}
                layout="vertical"
                margin={{ top: 5, right: 20, left: 15, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} opacity={0.15} />
                <XAxis type="number" stroke="#94A3B8" fontSize={10} tickLine={false} />
                <YAxis
                  dataKey="name"
                  type="category"
                  stroke="#94A3B8"
                  fontSize={10}
                  tickLine={false}
                  width={85}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {SCENARIO_DISTRIBUTION.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Recent High-Priority Alerts Feed */}
      <div className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Recent Priority Alerts
            </h3>
            <p className="text-xs text-slate-500">Live feed of transactions flagged for analyst intervention</p>
          </div>
          <Link
            to="/alerts"
            className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
          >
            <span>View All ({kpis?.total_alerts ?? 412})</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 font-medium">
                <th className="pb-3 font-medium">Case & Txn</th>
                <th className="pb-3 font-medium">Risk Level</th>
                <th className="pb-3 font-medium">Amount</th>
                <th className="pb-3 font-medium">Plain-English Summary</th>
                <th className="pb-3 font-medium">Status</th>
                <th className="pb-3 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {recentAlerts.map((alert) => (
                <tr key={alert.case_id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="py-3">
                    <p className="font-semibold text-slate-900 dark:text-slate-100">{alert.txn_id}</p>
                    <p className="text-[10px] text-slate-500 font-mono">{alert.account_id}</p>
                  </td>
                  <td className="py-3">
                    <RiskBadge level={alert.tier} score={alert.score} showScore />
                  </td>
                  <td className="py-3 font-semibold text-slate-900 dark:text-slate-100 tabular-nums">
                    {formatCurrency(alert.amount)}
                  </td>
                  <td className="py-3 max-w-md">
                    <p className="text-slate-600 dark:text-slate-300 truncate">{alert.summary}</p>
                  </td>
                  <td className="py-3">
                    <span className="capitalize px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                      {alert.status}
                    </span>
                  </td>
                  <td className="py-3 text-right">
                    <Link
                      to={`/alerts/${alert.case_id}`}
                      className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-indigo-600 hover:text-white transition-colors text-[11px] font-medium"
                    >
                      Investigate
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
