import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  ShieldAlert, 
  CheckCircle2, 
  Clock, 
  Search, 
  Filter, 
  Key, 
  Hash, 
  FileCheck,
  RefreshCw
} from 'lucide-react';
import { fetchAuditLog, verifyAuditChain } from '../lib/api';
import { RiskBadge } from '../components/common/RiskBadge';

export const AuditLogPage: React.FC = () => {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [filterAction, setFilterAction] = useState<string>('ALL');
  
  // Chain verification state
  const [verifying, setVerifying] = useState<boolean>(false);
  const [verificationResult, setVerificationResult] = useState<{
    valid: boolean;
    records?: number;
    total_entries?: number;
    error?: string | null;
    timestamp?: string;
  } | null>(null);

  useEffect(() => {
    fetchLogs();
  }, []);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const data = await fetchAuditLog(50, 0);
      setLogs(data?.items || []);
    } catch (err) {
      console.error('Failed to fetch audit entries:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyChain = async () => {
    setVerifying(true);
    try {
      const result = await verifyAuditChain();
      setVerificationResult({
        valid: result.valid,
        total_entries: result.records || result.total_entries || 0,
        error: result.error,
        timestamp: new Date().toLocaleTimeString(),
      });
    } catch (err: any) {
      setVerificationResult({
        valid: false,
        total_entries: 0,
        error: err.message || 'Verification endpoint unreachable',
        timestamp: new Date().toLocaleTimeString(),
      });
    } finally {
      setVerifying(false);
    }
  };

  const filteredLogs = logs.filter(log => {
    const id = log.txn_id || log.event_id || '';
    const hash = log.record_hash || log.hash || '';
    const matchesSearch = 
      id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      hash.toLowerCase().includes(searchTerm.toLowerCase());
    
    const action = log.tier || log.action || 'REVIEW';
    const matchesAction = filterAction === 'ALL' || action === filterAction;
    return matchesSearch && matchesAction;
  });

  return (
    <div className="space-y-6">
      {/* Header & Verification Section */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
            <FileCheck className="w-7 h-7 text-indigo-500" />
            Immutable Audit Trail
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            SHA-256 cryptographically chained append-only decision ledger conforming to banking compliance standards.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="px-3.5 py-2 text-sm font-medium rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          
          <button
            onClick={handleVerifyChain}
            disabled={verifying}
            className="px-4 py-2 text-sm font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <ShieldCheck className={`w-4 h-4 ${verifying ? 'animate-spin' : ''}`} />
            {verifying ? 'Verifying Hashes...' : 'Verify Cryptographic Chain'}
          </button>
        </div>
      </div>

      {/* Verification Result Banner */}
      {verificationResult && (
        <div className={`p-4 rounded-xl border flex items-start gap-4 transition-all duration-300 ${
          verificationResult.valid 
            ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200'
            : 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200'
        }`}>
          {verificationResult.valid ? (
            <CheckCircle2 className="w-6 h-6 text-emerald-500 shrink-0 mt-0.5" />
          ) : (
            <ShieldAlert className="w-6 h-6 text-rose-500 shrink-0 mt-0.5" />
          )}
          <div className="flex-1 text-sm">
            <div className="font-semibold text-base flex items-center gap-2">
              {verificationResult.valid ? 'Cryptographic Chain Integrity Verified' : 'Integrity Violation Detected'}
              <span className="text-xs px-2 py-0.5 rounded-full font-mono font-normal bg-black/10 dark:bg-white/10">
                Verified at {verificationResult.timestamp}
              </span>
            </div>
            <p className="mt-1">
              {verificationResult.valid
                ? `All ${verificationResult.total_entries} consecutive SHA-256 block hashes linked without tampering or missing headers.`
                : `Audit chain verification failure: ${verificationResult.error || 'Hash mismatch between chained records.'}`}
            </p>
          </div>
        </div>
      )}

      {/* Filters and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <div className="relative w-full sm:w-80">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search Event ID or Hash..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-slate-900 dark:text-slate-100"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <Filter className="w-4 h-4 text-slate-400" />
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Action:</span>
          {(['ALL', 'BLOCK', 'REVIEW', 'APPROVE'] as const).map(action => (
            <button
              key={action}
              onClick={() => setFilterAction(action)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                filterAction === action
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              {action}
            </button>
          ))}
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/50 text-xs font-semibold text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="px-5 py-3.5">Block / Time</th>
                <th className="px-4 py-3.5">Event ID</th>
                <th className="px-4 py-3.5">Action & Risk</th>
                <th className="px-4 py-3.5">Reason / Summary</th>
                <th className="px-4 py-3.5">Current Hash (SHA-256)</th>
                <th className="px-4 py-3.5">Previous Hash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-slate-400 text-sm">
                    <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-500" />
                    Loading audit trail ledger...
                  </td>
                </tr>
              ) : filteredLogs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-slate-400 text-sm">
                    No audit records found matching your filters.
                  </td>
                </tr>
              ) : (
                filteredLogs.map((entry, idx) => {
                  const action = entry.tier || entry.action || 'REVIEW';
                  const eventId = entry.txn_id || entry.event_id || 'UNKNOWN';
                  const hash = entry.record_hash || entry.hash || '';
                  const prevHash = entry.prev_hash || '';
                  const score = entry.score ?? entry.model_score ?? 0.5;

                  return (
                    <tr key={eventId || idx} className="hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors font-mono">
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-slate-800 dark:text-slate-200 text-xs flex items-center gap-1 font-sans">
                          <Clock className="w-3.5 h-3.5 text-slate-400" />
                          {entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : 'N/A'}
                        </div>
                        <div className="text-[10px] text-slate-400 font-sans mt-0.5">
                          {entry.timestamp ? new Date(entry.timestamp).toLocaleDateString() : ''}
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-xs text-indigo-600 dark:text-indigo-400 font-semibold font-sans">
                        {eventId}
                      </td>

                      <td className="px-4 py-3.5 font-sans">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                            action === 'BLOCK' ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300' :
                            action === 'REVIEW' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' :
                            'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                          }`}>
                            {action}
                          </span>
                          <RiskBadge level={action} score={score} showScore />
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-xs font-sans text-slate-600 dark:text-slate-300 max-w-xs truncate">
                        {entry.summary || (entry.rule_hits && entry.rule_hits.join(', ')) || 'Standard transaction review'}
                      </td>

                      <td className="px-4 py-3.5 text-[11px] text-slate-600 dark:text-slate-300">
                        <div className="flex items-center gap-1.5" title={hash}>
                          <Key className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                          <span>{hash ? `${hash.slice(0, 10)}...${hash.slice(-8)}` : 'GENESIS'}</span>
                        </div>
                      </td>

                      <td className="px-4 py-3.5 text-[11px] text-slate-400">
                        <div className="flex items-center gap-1.5" title={prevHash}>
                          <Hash className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                          <span>{prevHash ? `${prevHash.slice(0, 8)}...${prevHash.slice(-6)}` : '00000000'}</span>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
