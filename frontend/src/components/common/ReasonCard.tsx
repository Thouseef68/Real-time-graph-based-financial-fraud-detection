import React from "react";
import { AlertCircle, AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { cn } from "../../lib/utils";

interface ReasonCardProps {
  title: string;
  explanation: string;
  severity: "low" | "medium" | "high" | "critical" | string;
  evidence?: Record<string, any>;
  className?: string;
}

export const ReasonCard: React.FC<ReasonCardProps> = ({
  title,
  explanation,
  severity,
  evidence,
  className,
}) => {
  const getIcon = () => {
    switch (severity.toLowerCase()) {
      case "critical":
        return <ShieldAlert className="w-5 h-5 text-rose-500 shrink-0" />;
      case "high":
        return <AlertCircle className="w-5 h-5 text-orange-500 shrink-0" />;
      case "medium":
        return <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />;
      default:
        return <Info className="w-5 h-5 text-indigo-500 shrink-0" />;
    }
  };

  return (
    <div
      className={cn(
        "p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 shadow-sm flex flex-col justify-between transition-all hover:border-slate-300 dark:hover:border-slate-700",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 p-1.5 rounded-lg bg-slate-100 dark:bg-slate-800">
          {getIcon()}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h4>
            <span
              className={cn(
                "text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full border",
                severity.toLowerCase() === "critical"
                  ? "bg-rose-500/10 text-rose-500 border-rose-500/20"
                  : severity.toLowerCase() === "high"
                  ? "bg-orange-500/10 text-orange-500 border-orange-500/20"
                  : severity.toLowerCase() === "medium"
                  ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
                  : "bg-slate-500/10 text-slate-500 border-slate-500/20"
              )}
            >
              {severity}
            </span>
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 leading-relaxed">
            {explanation}
          </p>
        </div>
      </div>

      {evidence && Object.keys(evidence).length > 0 && (
        <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800/80 flex flex-wrap gap-2">
          {Object.entries(evidence).map(([k, v]) => (
            <span
              key={k}
              className="inline-flex items-center gap-1 text-[11px] font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              <span className="text-slate-400">{k}:</span>
              <span className="font-semibold">{typeof v === "number" ? v.toLocaleString() : String(v)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
