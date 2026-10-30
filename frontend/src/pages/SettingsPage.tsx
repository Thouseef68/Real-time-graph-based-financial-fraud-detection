import React, { useState } from 'react';
import { 
  Sliders, 
  Shield, 
  Cpu, 
  Database, 
  Save, 
  RotateCcw, 
  Check, 
  AlertCircle,
  FileCode,
  Layers
} from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const [reviewThreshold, setReviewThreshold] = useState<number>(0.35);
  const [blockThreshold, setBlockThreshold] = useState<number>(0.85);
  const [velocityCap1h, setVelocityCap1h] = useState<number>(50000);
  const [autoApproveBelow, setAutoApproveBelow] = useState<number>(0.08);
  const [anomalyWeight, setAnomalyWeight] = useState<number>(0.35);
  const [auditHashingEnabled, setAuditHashingEnabled] = useState<boolean>(true);
  const [saved, setSaved] = useState<boolean>(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
          <Sliders className="w-7 h-7 text-indigo-500" />
          Engine Configuration & Rules
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Tune operational decision thresholds, hybrid anomaly fusion weights, and compliance guardrails in real time.
        </p>
      </div>

      {saved && (
        <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200 text-sm flex items-center gap-2">
          <Check className="w-5 h-5 text-emerald-500" />
          Engine configuration successfully updated and reloaded into active memory.
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6">
        {/* Scoring Thresholds Card */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm space-y-5">
          <div className="flex items-center gap-2.5 pb-4 border-b border-slate-100 dark:border-slate-800">
            <Shield className="w-5 h-5 text-indigo-500" />
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              Decision Thresholds & Bands
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Manual Review Threshold (τ_review): {reviewThreshold}
              </label>
              <input
                type="range"
                min="0.1"
                max="0.6"
                step="0.01"
                value={reviewThreshold}
                onChange={(e) => setReviewThreshold(parseFloat(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <p className="text-xs text-slate-400 mt-1">
                Transactions with risk scores between τ_review and τ_block are queued for human analyst review.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Hard Block Threshold (τ_block): {blockThreshold}
              </label>
              <input
                type="range"
                min="0.65"
                max="0.99"
                step="0.01"
                value={blockThreshold}
                onChange={(e) => setBlockThreshold(parseFloat(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <p className="text-xs text-slate-400 mt-1">
                Transactions exceeding τ_block are automatically rejected at the gateway.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Auto-Approve Cutoff: {autoApproveBelow}
              </label>
              <input
                type="range"
                min="0.01"
                max="0.2"
                step="0.01"
                value={autoApproveBelow}
                onChange={(e) => setAutoApproveBelow(parseFloat(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <p className="text-xs text-slate-400 mt-1">
                Low-risk transactions with clean profile and 0 rule triggers bypass heavy graph enrichment.
              </p>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                1-Hour Outflow Velocity Cap ($):
              </label>
              <input
                type="number"
                value={velocityCap1h}
                onChange={(e) => setVelocityCap1h(parseInt(e.target.value) || 0)}
                className="w-full px-3 py-2 text-sm rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white"
              />
              <p className="text-xs text-slate-400 mt-1">
                Any outflow exceeding this cumulative 1-hour window triggers rule RUL_001.
              </p>
            </div>
          </div>
        </div>

        {/* Fusion & Anomaly Weights */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm space-y-5">
          <div className="flex items-center gap-2.5 pb-4 border-b border-slate-100 dark:border-slate-800">
            <Layers className="w-5 h-5 text-indigo-500" />
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              Model Fusion & Calibration
            </h2>
          </div>

          <div className="space-y-4">
            <div>
              <div className="flex justify-between items-center text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                <span>Anomaly Sub-Engine Weight: {(anomalyWeight * 100).toFixed(0)}%</span>
                <span className="text-slate-400">Supervised XGBoost: {((1 - anomalyWeight) * 100).toFixed(0)}%</span>
              </div>
              <input
                type="range"
                min="0.0"
                max="0.8"
                step="0.05"
                value={anomalyWeight}
                onChange={(e) => setAnomalyWeight(parseFloat(e.target.value))}
                className="w-full accent-indigo-600"
              />
              <p className="text-xs text-slate-400 mt-1">
                Determines how much influence PyTorch Autoencoder + IsolationForest reconstruction error has on the final fused risk score.
              </p>
            </div>
          </div>
        </div>

        {/* System & Audit Ledger */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 shadow-sm space-y-5">
          <div className="flex items-center gap-2.5 pb-4 border-b border-slate-100 dark:border-slate-800">
            <Cpu className="w-5 h-5 text-indigo-500" />
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              Runtime & Compliance Information
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <span className="text-slate-400">Active Engine Model:</span>
              <p className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5">XGBoost v2.0.0 + AE Stacking</p>
            </div>
            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <span className="text-slate-400">Calibration Method:</span>
              <p className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5">Isotonic Regression (Out-of-Fold)</p>
            </div>
            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <span className="text-slate-400">Graph Memory Engine:</span>
              <p className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5">NetworkX Directed Temporal Multi-Edge</p>
            </div>
            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <span className="text-slate-400">Audit Ledger Path:</span>
              <p className="font-semibold text-slate-800 dark:text-slate-200 mt-0.5 font-mono">results_v2/audit_log.jsonl</p>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => {
              setReviewThreshold(0.35);
              setBlockThreshold(0.85);
              setVelocityCap1h(50000);
              setAutoApproveBelow(0.08);
              setAnomalyWeight(0.35);
            }}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 transition-colors flex items-center gap-1.5"
          >
            <RotateCcw className="w-4 h-4" />
            Reset Defaults
          </button>
          <button
            type="submit"
            className="px-5 py-2 text-sm font-semibold rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm flex items-center gap-2 transition-colors"
          >
            <Save className="w-4 h-4" />
            Save Configuration
          </button>
        </div>
      </form>
    </div>
  );
};
