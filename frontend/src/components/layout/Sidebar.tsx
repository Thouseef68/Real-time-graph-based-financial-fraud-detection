import React from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  FileCheck,
  Network,
  PlayCircle,
  Settings,
  Shield,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { cn } from "../../lib/utils";

const NAV_ITEMS = [
  { label: "Live Demo Studio", path: "/", icon: Sparkles, badge: "Story" },
  { label: "Overview", path: "/overview", icon: Activity },
  { label: "Live Alerts", path: "/alerts", icon: AlertTriangle, badge: "Live" },
  { label: "Network Explorer", path: "/graph", icon: Network },
  { label: "Model Performance", path: "/models", icon: BarChart3 },
  { label: "Drift Monitoring", path: "/monitoring", icon: TrendingUp },
  { label: "Demo Simulator", path: "/simulator", icon: PlayCircle },
  { label: "Audit Chain", path: "/audit", icon: FileCheck },
  { label: "Settings", path: "/settings", icon: Settings },
];

export const Sidebar: React.FC = () => {
  const location = useLocation();

  return (
    <aside className="w-64 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between shrink-0 h-screen sticky top-0 z-30">
      <div>
        {/* Brand Header */}
        <div className="h-16 px-6 flex items-center gap-3 border-b border-slate-200 dark:border-slate-800">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white shadow-md shadow-indigo-600/30">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-bold text-sm tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
              FraudEngine <span className="text-[10px] bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 font-semibold px-1.5 py-0.2 rounded border border-indigo-500/20">v2.0</span>
            </h1>
            <p className="text-[10px] text-slate-500">Real-Time Risk & Graph</p>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="p-3 space-y-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path || (item.path !== "/" && location.pathname.startsWith(item.path));
            return (
              <Link
                key={item.path}
                to={item.path}
                className={cn(
                  "flex items-center justify-between px-3.5 py-2.5 rounded-lg text-xs font-medium transition-all",
                  isActive
                    ? "bg-indigo-600 text-white shadow-sm shadow-indigo-600/20 font-semibold"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800/60"
                )}
              >
                <div className="flex items-center gap-3">
                  <Icon className={cn("w-4 h-4", isActive ? "text-white" : "text-slate-400")} />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span
                    className={cn(
                      "text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider",
                      isActive
                        ? "bg-white/20 text-white"
                        : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    )}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Footer Info */}
      <div className="p-4 border-t border-slate-200 dark:border-slate-800 text-[11px] text-slate-500 space-y-1 bg-slate-50/50 dark:bg-slate-950/30">
        <div className="flex items-center justify-between">
          <span>Engine Model</span>
          <span className="font-mono font-medium text-slate-700 dark:text-slate-300">XGBoost v2</span>
        </div>
        <div className="flex items-center justify-between">
          <span>Latency p95</span>
          <span className="font-mono font-medium text-emerald-600">0.08 ms</span>
        </div>
      </div>
    </aside>
  );
};
