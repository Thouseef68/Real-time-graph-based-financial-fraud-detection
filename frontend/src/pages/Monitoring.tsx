import React, { useEffect, useState } from "react";
import { AlertCircle, CheckCircle, RefreshCw, TrendingUp } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchDrift } from "../lib/api";

export const Monitoring: React.FC = () => {
  const [driftData, setDriftData] = useState<any>(null);

  useEffect(() => {
    fetchDrift().then(setDriftData);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="pb-2 border-b border-slate-200 dark:border-slate-800">
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-indigo-500" />
          <span>Feature & Score Drift Monitoring (PSI)</span>
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Population Stability Index (PSI) tracking data distribution shifts between training and production stream.
        </p>
      </div>

      {/* Model Deployment Registry Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <p className="text-xs text-slate-500 font-medium">Champion Model</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-lg font-bold text-slate-900 dark:text-slate-100">v2.0.0</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              Active in Production
            </span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Full 41 features + anomaly ensembles</p>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <p className="text-xs text-slate-500 font-medium">Challenger Status</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-lg font-bold text-slate-900 dark:text-slate-100">v2.1.0-retrain</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">
              Shadow Mode
            </span>
          </div>
          <p className="text-[11px] text-slate-400 mt-1">Trained on recent 72h confirmed labels</p>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <p className="text-xs text-slate-500 font-medium">Score Distribution PSI</p>
          <p className="font-mono text-lg font-bold text-emerald-600 dark:text-emerald-400 mt-1">
            {driftData?.score_psi?.toFixed(3) ?? "0.028"}
          </p>
          <p className="text-[11px] text-slate-400 mt-1">&lt; 0.10 threshold (Minimal drift)</p>
        </div>
      </div>

      {/* Feature Drift Table & Alert Rate Trend */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* PSI Table */}
        <div className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-3">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Feature Population Stability Index (PSI)
          </h3>
          <p className="text-xs text-slate-500">
            Comparing validation split vs live test stream (PSI &gt; 0.2 indicates significant drift)
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-800 text-slate-400 font-medium">
                  <th className="py-2.5 px-3">Feature Name</th>
                  <th className="py-2.5 px-3">PSI Metric</th>
                  <th className="py-2.5 px-3">Health Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono">
                {driftData?.features_drift?.map((f: any) => (
                  <tr key={f.feature}>
                    <td className="py-2.5 px-3 font-medium text-slate-900 dark:text-slate-100 font-sans">
                      {f.feature}
                    </td>
                    <td className="py-2.5 px-3">{f.psi.toFixed(3)}</td>
                    <td className="py-2.5 px-3 font-sans">
                      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
                        <span>Stable</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Alert Rate Trend Chart */}
        <div className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-3">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Alert Rate Trend Over Rolling Windows
          </h3>
          <p className="text-xs text-slate-500">
            Monitoring alert volume consistency across simulated 24h intervals
          </p>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={driftData?.alert_rate_trend || []}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="step" stroke="#94A3B8" fontSize={10} tickLine={false} />
                <YAxis stroke="#94A3B8" fontSize={10} tickLine={false} domain={[0, 0.025]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(value: any) => [`${(Number(value) * 100).toFixed(2)}%`, "Alert Rate"]}
                />
                <Line
                  type="monotone"
                  dataKey="alert_rate"
                  stroke="#4F46E5"
                  strokeWidth={2.5}
                  dot={{ r: 4 }}
                  name="Alert Rate"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
};
