import React from "react";
import { cn } from "../../lib/utils";

export type RiskLevel = "ALLOW" | "STEP_UP" | "REVIEW" | "BLOCK" | "Low" | "Medium" | "High" | "Critical";

interface RiskBadgeProps {
  level: RiskLevel | string;
  score?: number;
  className?: string;
  showScore?: boolean;
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  level,
  score,
  className,
  showScore = false,
}) => {
  // Normalize
  const normalized = level.toUpperCase();

  let label = "Low";
  let bgClasses = "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20";

  if (normalized === "BLOCK" || normalized === "CRITICAL") {
    label = "Critical";
    bgClasses = "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20";
  } else if (normalized === "REVIEW" || normalized === "HIGH") {
    label = "High";
    bgClasses = "bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20";
  } else if (normalized === "STEP_UP" || normalized === "MEDIUM") {
    label = "Medium";
    bgClasses = "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20";
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border",
        bgClasses,
        className
      )}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-80" />
      <span>{label} Risk</span>
      {showScore && score !== undefined && (
        <span className="opacity-75 font-normal ml-0.5 tabular-nums">({score.toFixed(2)})</span>
      )}
    </span>
  );
};
