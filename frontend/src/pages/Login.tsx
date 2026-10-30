import React, { useState } from 'react';
import { Shield, Lock, User, ArrowRight, ShieldAlert, Sparkles } from 'lucide-react';
import { useAuth, type Role } from '../context/AuthContext';

export const Login: React.FC = () => {
  const { login } = useAuth();
  const [username, setUsername] = useState('analyst');
  const [password, setPassword] = useState('analyst123');
  const [role, setRole] = useState<Role>('analyst');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (!username.trim() || !password.trim()) {
        setError('Please enter both username and password.');
        return;
      }
      login(username, role, 'mock-jwt-token-xyz');
    } catch (err: any) {
      setError(err.message || 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickSelect = (u: string, p: string, r: Role) => {
    setUsername(u);
    setPassword(p);
    setRole(r);
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-12 sm:px-6 lg:px-8 relative overflow-hidden">
      {/* Background ambient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[400px] bg-indigo-500/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-[400px] h-[300px] bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none" />

      <div className="sm:mx-auto sm:w-full sm:max-w-md z-10">
        <div className="flex justify-center">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/25">
            <Shield className="w-8 h-8 text-white" />
          </div>
        </div>
        <h2 className="mt-5 text-center text-2xl font-bold tracking-tight text-white">
          FraudSentinel AI
        </h2>
        <p className="mt-1.5 text-center text-xs text-slate-400">
          Real-Time Graph & Anomaly Fraud Detection Engine v2.0
        </p>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md z-10 px-4">
        <div className="bg-slate-900/80 backdrop-blur-xl py-8 px-6 shadow-2xl rounded-2xl border border-slate-800/80 sm:px-10 space-y-6">
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Username
              </label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-slate-800/50 border border-slate-700/80 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-white placeholder-slate-500"
                  placeholder="analyst"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Password
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-slate-800/50 border border-slate-700/80 focus:outline-none focus:ring-2 focus:ring-indigo-500 text-white placeholder-slate-500"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-all shadow-md shadow-indigo-600/30 disabled:opacity-50"
            >
              {loading ? 'Authenticating...' : 'Sign In to Console'}
              <ArrowRight className="w-4 h-4" />
            </button>
          </form>

          {/* Quick Demo Switcher */}
          <div className="pt-4 border-t border-slate-800/60">
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              Demo Roles (One-Click Select):
            </p>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleQuickSelect('analyst', 'analyst123', 'analyst')}
                className={`px-3 py-2 text-xs rounded-lg border transition-all text-center ${
                  role === 'analyst'
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-300 font-semibold'
                    : 'border-slate-800 bg-slate-800/40 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Risk Analyst
              </button>
              <button
                type="button"
                onClick={() => handleQuickSelect('admin', 'admin123', 'admin')}
                className={`px-3 py-2 text-xs rounded-lg border transition-all text-center ${
                  role === 'admin'
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-300 font-semibold'
                    : 'border-slate-800 bg-slate-800/40 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Lead Admin
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
