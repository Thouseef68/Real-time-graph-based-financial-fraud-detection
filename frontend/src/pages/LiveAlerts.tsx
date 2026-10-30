import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowUpDown,
  CheckCircle,
  Filter,
  Search,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { fetchAlerts, takeCaseAction } from "../lib/api";
import { formatCurrency } from "../lib/utils";
import { RiskBadge } from "../components/common/RiskBadge";

export const LiveAlerts: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTier = searchParams.get("tier") || "ALL";
  const currentStatus = searchParams.get("status") || "ALL";

  const [alerts, setAlerts] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(true);

  const loadAlerts = () => {
    setLoading(true);
    const tierParam = currentTier === "ALL" ? undefined : currentTier;
    const statusParam = currentStatus === "ALL" ? undefined : currentStatus;
    fetchAlerts({ tier: tierParam, status: statusParam, size: 100 })
      .then((data: any) => {
        setAlerts(data.items);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadAlerts();

    // Connect to Server-Sent Events stream for live alerts
    const eventSource = new EventSource("/api/v1/stream");
    eventSource.addEventListener("new_alert", (event) => {
      try {
        const newAlert = JSON.parse(event.data);
        setAlerts((prev) => [newAlert, ...prev]);
      } catch (e) {
        console.error("SSE parse error", e);
      }
    });

    return () => {
      eventSource.close();
    };
  }, [currentTier, currentStatus]);

  const handleAction = async (caseId: string, action: string) => {
    await takeCaseAction(caseId, action, `Quick action: ${action}`);
    loadAlerts();
  };

  const filteredAlerts = alerts.filter((a) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      a.txn_id?.toLowerCase().includes(q) ||
      a.account_id?.toLowerCase().includes(q) ||
      a.summary?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">
              Live Alert Investigation Queue
            </h2>
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Real-time queue of transactions requiring analyst attention or confirmation.
          </p>
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-2">
          {["ALL", "BLOCK", "REVIEW", "STEP_UP"].map((tier) => (
            <button
              key={tier}
              onClick={() => {
                const params = new URLSearchParams(searchParams);
                if (tier === "ALL") params.delete("tier");
                else params.set("tier", tier);
                setSearchParams(params);
              }}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                currentTier === tier
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800"
              }`}
            >
              {tier === "ALL" ? "All Tiers" : tier.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Search & Status Controls */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Filter by account or txn..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div className="flex items-center gap-2 self-end sm:self-auto text-xs text-slate-500">
          <span>Showing {filteredAlerts.length} alerts</span>
        </div>
      </div>

      {/* Alerts Table */}
      <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-950/40 text-slate-400 font-medium">
                <th className="py-3 px-4">Transaction / Account</th>
                <th className="py-3 px-4">Risk Level</th>
                <th className="py-3 px-4">Amount</th>
                <th className="py-3 px-4">Plain-English Investigation Summary</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4 text-right">Quick Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    Loading live alerts queue...
                  </td>
                </tr>
              ) : filteredAlerts.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    No alerts match the selected criteria.
                  </td>
                </tr>
              ) : (
                filteredAlerts.map((alert) => (
                  <tr
                    key={alert.case_id}
                    className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="py-3.5 px-4">
                      <Link
                        to={`/alerts/${alert.case_id}`}
                        className="font-semibold text-indigo-600 dark:text-indigo-400 hover:underline"
                      >
                        {alert.txn_id}
                      </Link>
                      <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                        {alert.account_id}
                      </p>
                    </td>
                    <td className="py-3.5 px-4">
                      <RiskBadge level={alert.tier} score={alert.score} showScore />
                    </td>
                    <td className="py-3.5 px-4 font-semibold text-slate-900 dark:text-slate-100 tabular-nums">
                      {formatCurrency(alert.amount)}
                    </td>
                    <td className="py-3.5 px-4 max-w-lg">
                      <p className="text-slate-700 dark:text-slate-300 line-clamp-2">
                        {alert.summary}
                      </p>
                      {alert.scenario && (
                        <span className="inline-block mt-1 text-[10px] font-mono font-medium px-2 py-0.2 rounded bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">
                          {alert.scenario}
                        </span>
                      )}
                    </td>
                    <td className="py-3.5 px-4">
                      <span className="capitalize px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                        {alert.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => handleAction(alert.case_id, "approve")}
                          title="Approve / Dismiss alert"
                          className="p-1 rounded text-slate-400 hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors"
                        >
                          <CheckCircle className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleAction(alert.case_id, "block")}
                          title="Confirm Fraud / Block"
                          className="p-1 rounded text-slate-400 hover:text-rose-500 hover:bg-rose-500/10 transition-colors"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                        <Link
                          to={`/alerts/${alert.case_id}`}
                          className="px-2.5 py-1 rounded bg-indigo-600 text-white text-[11px] font-medium hover:bg-indigo-700 transition-colors ml-1"
                        >
                          Details
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
