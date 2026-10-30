import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  DollarSign,
  HelpCircle,
  Network,
  ShieldAlert,
  User,
  XCircle,
} from "lucide-react";
import { fetchAlertDetail, takeCaseAction } from "../lib/api";
import { formatCurrency } from "../lib/utils";
import { CytoscapeGraph } from "../components/common/CytoscapeGraph";
import { ReasonCard } from "../components/common/ReasonCard";
import { RiskBadge } from "../components/common/RiskBadge";

export const CaseDetail: React.FC = () => {
  const { caseId } = useParams<{ caseId: string }>();
  const navigate = useNavigate();

  const [caseData, setCaseData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [actionNote, setActionNote] = useState("");
  const [actionDialog, setActionDialog] = useState<string | null>(null);
  const [showRawJson, setShowRawJson] = useState(false);

  useEffect(() => {
    if (caseId) {
      fetchAlertDetail(caseId).then((data) => {
        setCaseData(data);
        setLoading(false);
      });
    }
  }, [caseId]);

  const handleConfirmAction = async (action: string) => {
    if (!caseId) return;
    await takeCaseAction(caseId, action, actionNote);
    setActionDialog(null);
    setActionNote("");
    // Reload
    fetchAlertDetail(caseId).then(setCaseData);
  };

  if (loading) {
    return (
      <div className="py-24 text-center text-slate-400 text-sm">
        Loading case investigation bundle...
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="py-24 text-center space-y-3">
        <p className="text-slate-400">Case not found.</p>
        <Link to="/alerts" className="text-xs text-indigo-600 hover:underline">
          Return to Live Alerts
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-12">
      {/* Navigation Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link to="/alerts" className="hover:text-slate-900 dark:hover:text-slate-100 flex items-center gap-1">
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Alerts Queue</span>
        </Link>
        <ChevronRight className="w-3 h-3 text-slate-400" />
        <span className="font-mono text-slate-900 dark:text-slate-100">{caseData.txn_id}</span>
      </div>

      {/* Case Header */}
      <div className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 tracking-tight font-mono">
              {caseData.txn_id}
            </h2>
            <RiskBadge level={caseData.tier} score={caseData.score} showScore />
            <span className="capitalize px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
              Status: {caseData.status}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 mt-2">
            <span>
              Account: <span className="font-mono text-slate-700 dark:text-slate-300 font-semibold">{caseData.account_id}</span>
            </span>
            <span>•</span>
            <span>
              Amount: <span className="font-semibold text-slate-900 dark:text-slate-100 tabular-nums">{formatCurrency(caseData.amount)}</span>
            </span>
            <span>•</span>
            <span>
              Time: <span className="text-slate-700 dark:text-slate-300">{caseData.created_at}</span>
            </span>
            {caseData.scenario && (
              <>
                <span>•</span>
                <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-500 font-mono text-[11px] font-semibold">
                  Scenario: {caseData.scenario}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActionDialog("approve")}
            className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-emerald-600 hover:text-white transition-colors flex items-center gap-1.5"
          >
            <CheckCircle2 className="w-4 h-4" />
            <span>Approve</span>
          </button>
          <button
            onClick={() => setActionDialog("escalate")}
            className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-amber-600 hover:text-white transition-colors flex items-center gap-1.5"
          >
            <AlertTriangle className="w-4 h-4" />
            <span>Escalate</span>
          </button>
          <button
            onClick={() => setActionDialog("block")}
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-rose-600 text-white hover:bg-rose-700 transition-colors flex items-center gap-1.5 shadow-sm shadow-rose-600/30"
          >
            <ShieldAlert className="w-4 h-4" />
            <span>Confirm & Block</span>
          </button>
        </div>
      </div>

      {/* Confirmation Dialog Modal */}
      {actionDialog && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 max-w-md w-full shadow-xl space-y-4">
            <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 capitalize">
              Confirm {actionDialog} Action
            </h3>
            <p className="text-xs text-slate-600 dark:text-slate-400">
              Please enter an investigation note for the tamper-evident audit log before submitting.
            </p>
            <textarea
              placeholder="Reason for analyst action (e.g. Verified customer out-of-band via registered telephone)..."
              value={actionNote}
              onChange={(e) => setActionNote(e.target.value)}
              className="w-full p-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 text-xs text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 h-24"
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={() => setActionDialog(null)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                Cancel
              </button>
              <button
                onClick={() => handleConfirmAction(actionDialog)}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm"
              >
                Submit Decision
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Investigation Summary & Action Recommendation Banner */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 p-5 rounded-xl border border-indigo-500/20 bg-indigo-50/40 dark:bg-indigo-950/20 space-y-2">
          <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400">
            <ShieldAlert className="w-4 h-4" />
            <h3 className="text-xs font-bold uppercase tracking-wider">Executive Investigation Summary</h3>
          </div>
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100 leading-relaxed">
            {caseData.summary}
          </p>
        </div>

        <div className="p-5 rounded-xl border border-amber-500/20 bg-amber-50/40 dark:bg-amber-950/20 space-y-2">
          <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
            <HelpCircle className="w-4 h-4" />
            <h3 className="text-xs font-bold uppercase tracking-wider">Recommended Action</h3>
          </div>
          <p className="text-xs font-medium text-slate-800 dark:text-slate-200 leading-relaxed">
            {caseData.recommended_action}
          </p>
        </div>
      </div>

      {/* Why was this flagged? - Top 3 Reason Cards */}
      <div className="space-y-3">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight">
          Why was this flagged? (Top Key Risk Indicators)
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {caseData.reasons.map((r: any, idx: number) => (
            <ReasonCard
              key={idx}
              title={r.title}
              explanation={r.explanation}
              severity={r.severity}
              evidence={r.evidence}
            />
          ))}
        </div>
      </div>

      {/* Cytoscape 2-Hop Network Graph */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
              <Network className="w-4 h-4 text-indigo-500" />
              <span>2-Hop Entity Linkage Subgraph</span>
            </h3>
            <p className="text-xs text-slate-500">
              Interactive ego network showing co-located devices, fan-in senders, and downstream collectors.
            </p>
          </div>
          <span className="text-xs text-slate-500 font-mono">
            {caseData.subgraph?.node_count ?? 0} nodes • {caseData.subgraph?.edge_count ?? 0} edges
          </span>
        </div>
        <CytoscapeGraph
          elements={caseData.subgraph}
          centerId={caseData.account_id}
          height="400px"
        />
      </div>

      {/* Account History Timeline */}
      {caseData.timeline && caseData.timeline.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
            <Clock className="w-4 h-4 text-indigo-500" />
            <span>Recent Activity Timeline</span>
          </h3>
          <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
            <ol className="relative border-l border-slate-200 dark:border-slate-800 ml-3 space-y-4 py-2">
              {caseData.timeline.map((item: any, idx: number) => (
                <li key={idx} className="ml-6">
                  <span className="absolute -left-1.5 mt-1.5 w-3 h-3 rounded-full border-2 border-white dark:border-slate-900 bg-indigo-600" />
                  <div className="flex items-center justify-between text-xs">
                    <p className="font-semibold text-slate-800 dark:text-slate-200">{item.event}</p>
                    <time className="text-[11px] text-slate-400 font-mono">{item.time}</time>
                  </div>
                  {item.amount && (
                    <p className="text-xs font-semibold text-slate-600 dark:text-slate-400 mt-0.5 tabular-nums">
                      {formatCurrency(item.amount)}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {/* Audit Trail & Action History */}
      <div className="space-y-3">
        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight">
          Case Audit Log History
        </h3>
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm overflow-hidden text-xs">
          <table className="w-full text-left">
            <thead className="bg-slate-50 dark:bg-slate-950/40 text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="py-2.5 px-4 font-medium">Timestamp</th>
                <th className="py-2.5 px-4 font-medium">Actor</th>
                <th className="py-2.5 px-4 font-medium">Action</th>
                <th className="py-2.5 px-4 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono">
              {caseData.audit_events?.map((ev: any, idx: number) => (
                <tr key={idx}>
                  <td className="py-2.5 px-4 text-slate-500">{ev.created_at}</td>
                  <td className="py-2.5 px-4 font-semibold text-slate-800 dark:text-slate-200">{ev.actor}</td>
                  <td className="py-2.5 px-4 text-indigo-600 dark:text-indigo-400 uppercase font-semibold">{ev.action}</td>
                  <td className="py-2.5 px-4 text-slate-600 dark:text-slate-400 font-sans">{ev.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Advanced Expandable JSON Inspector */}
      <div className="pt-4 border-t border-slate-200 dark:border-slate-800">
        <button
          onClick={() => setShowRawJson((prev) => !prev)}
          className="text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-100 flex items-center gap-1.5 font-medium"
        >
          {showRawJson ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <span>{showRawJson ? "Hide Technical Features Snapshot (JSON)" : "Show Technical Features Snapshot (JSON)"}</span>
        </button>
        {showRawJson && (
          <pre className="mt-3 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-950 text-slate-200 text-xs font-mono overflow-x-auto max-h-96">
            {JSON.stringify(caseData.features, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
};
