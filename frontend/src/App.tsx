import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Lock } from 'lucide-react';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/layout/Navbar';
import { Sidebar } from './components/layout/Sidebar';
import { Login } from './pages/Login';

// Pages
import { CustomerApp } from './pages/CustomerApp';
import { DemoStudio } from './pages/DemoStudio';
import { Overview } from './pages/Overview';
import { LiveAlerts } from './pages/LiveAlerts';
import { CaseDetail } from './pages/CaseDetail';
import { NetworkExplorer } from './pages/NetworkExplorer';
import { ModelPerformance } from './pages/ModelPerformance';
import { Monitoring } from './pages/Monitoring';
import { Simulator } from './pages/Simulator';
import { AuditLogPage } from './pages/AuditLogPage';
import { SettingsPage } from './pages/SettingsPage';

const AppLayout: React.FC = () => {
  const { user } = useAuth();

  if (!user) {
    return <Login />;
  }

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 overflow-hidden font-sans">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Persistent Simulation Banner on Every Screen */}
        <div className="bg-amber-500 text-slate-950 px-3 py-1.5 text-center text-xs font-bold tracking-wide uppercase flex items-center justify-center gap-2 shadow-sm z-30">
          <Lock className="w-3.5 h-3.5" />
          <span>Simulation: virtual money only • No real bank or UPI connections</span>
        </div>
        <Navbar />
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8">
          <Routes>
            <Route path="/" element={<DemoStudio />} />
            <Route path="/demo" element={<DemoStudio />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/alerts" element={<LiveAlerts />} />
            <Route path="/cases/:caseId" element={<CaseDetail />} />
            <Route path="/graph" element={<NetworkExplorer />} />
            <Route path="/network" element={<NetworkExplorer />} />
            <Route path="/models" element={<ModelPerformance />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/simulator" element={<Simulator />} />
            <Route path="/audit" element={<AuditLogPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        {/* Persistent Global Footer on Every Screen */}
        <footer className="py-2 px-4 border-t border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md text-center text-xs font-mono text-slate-500 dark:text-slate-400 flex items-center justify-center gap-3">
          <span>Bots: seed 42</span>
          <span>|</span>
          <span>People: live sandbox</span>
          <span>|</span>
          <span>Pipeline: Real Redpanda & Redis</span>
        </footer>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/app" element={<CustomerApp />} />
            <Route path="/*" element={<AppLayout />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;

