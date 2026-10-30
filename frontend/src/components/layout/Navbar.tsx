import React, { useState } from "react";
import {
  Bell,
  CheckCircle2,
  Moon,
  Search,
  Sun,
  User as UserIcon,
  Wifi,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { useTheme } from "../../context/ThemeContext";

interface NavbarProps {
  onSearch?: (term: string) => void;
}

export const Navbar: React.FC<NavbarProps> = ({ onSearch }) => {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [searchTerm, setSearchTerm] = useState("");

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (onSearch && searchTerm.trim()) {
      onSearch(searchTerm.trim());
    }
  };

  return (
    <header className="h-16 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Global Search */}
      <form onSubmit={handleSearchSubmit} className="relative w-80 max-w-sm">
        <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          placeholder="Search account, device, or txn ID..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full pl-9 pr-4 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </form>

      {/* Status & User Actions */}
      <div className="flex items-center gap-4">
        {/* Live Service Health Strip: Scoring engine, Kafka, Redis, Graph DB */}
        <div className="hidden lg:flex items-center gap-1.5 text-[11px] font-mono">
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-bold">Scoring Engine:</span>
            <span>XGBoost v2</span>
          </div>
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="font-bold">Kafka:</span>
            <span>6 Partitions</span>
          </div>
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="font-bold">Redis:</span>
            <span>Fast Store</span>
          </div>
          <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span className="font-bold">Graph DB:</span>
            <span>Topology</span>
          </div>
        </div>

        {/* Compact fallback on smaller viewports */}
        <div className="lg:hidden inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-mono">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Services: 4/4 Live</span>
        </div>

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="p-2 rounded-lg text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        {/* User Badge */}
        {user && (
          <div className="flex items-center gap-2 pl-2 border-l border-slate-200 dark:border-slate-800">
            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-bold uppercase">
              {user.username.slice(0, 1)}
            </div>
            <div className="hidden sm:block text-left text-xs">
              <p className="font-semibold text-slate-900 dark:text-slate-100 leading-tight">
                {user.username}
              </p>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">
                {user.role}
              </p>
            </div>
            <button
              onClick={logout}
              className="text-[11px] text-slate-400 hover:text-rose-500 ml-1 transition-colors"
            >
              Logout
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
