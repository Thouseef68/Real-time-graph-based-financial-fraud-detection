import React, { useState } from "react";
import { Filter, Network, Search } from "lucide-react";
import { CytoscapeGraph } from "../components/common/CytoscapeGraph";
import { MOCK_CASE_DETAIL } from "../lib/mockData";

export const NetworkExplorer: React.FC = () => {
  const [searchAccount, setSearchAccount] = useState("C1948201948");
  const [hops, setHops] = useState(2);
  const [subgraph, setSubgraph] = useState<any>(MOCK_CASE_DETAIL.subgraph);
  const [selectedNode, setSelectedNode] = useState<any>(null);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchAccount.trim()) return;
    fetch(`/api/v1/graph/account/${searchAccount}?hops=${hops}`)
      .then((res) => {
        if (!res.ok) throw new Error("Search failed");
        return res.json();
      })
      .then(setSubgraph)
      .catch(() => {
        setSubgraph({
          ...MOCK_CASE_DETAIL.subgraph,
          center_account: searchAccount,
        });
      });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="pb-2 border-b border-slate-200 dark:border-slate-800">
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
          <Network className="w-5 h-5 text-indigo-500" />
          <span>Entity Network & Linkage Explorer</span>
        </h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Multi-hop graph visualization mapping account interactions, shared devices, and fraud ring associations.
        </p>
      </div>

      {/* Search Bar & Hop Depth Filters */}
      <form onSubmit={handleSearch} className="flex flex-col sm:flex-row items-center gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search account ID or hardware device ID (e.g., C1948201948 or dev_ring_08)..."
            value={searchAccount}
            onChange={(e) => setSearchAccount(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-xs rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Depth:</span>
          {[1, 2, 3].map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setHops(h)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                hops === h
                  ? "bg-indigo-600 text-white"
                  : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400"
              }`}
            >
              {h} {h === 1 ? "Hop" : "Hops"}
            </button>
          ))}
          <button
            type="submit"
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm"
          >
            Explore Graph
          </button>
        </div>
      </form>

      {/* Main Graph Viewport */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-3">
          <CytoscapeGraph
            elements={subgraph}
            centerId={searchAccount}
            height="540px"
            onNodeClick={(id, data) => setSelectedNode({ id, ...data })}
          />
        </div>

        {/* Selected Entity Inspector Panel */}
        <div className="p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-4">
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 border-b border-slate-100 dark:border-slate-800 pb-2">
            Entity Inspector
          </h3>

          {selectedNode ? (
            <div className="space-y-3 text-xs">
              <div>
                <p className="text-slate-400">Node Identifier</p>
                <p className="font-mono font-bold text-slate-900 dark:text-slate-100 break-all">{selectedNode.id}</p>
              </div>
              <div>
                <p className="text-slate-400">Node Type</p>
                <span className="inline-block uppercase font-bold text-[10px] px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-500 mt-1">
                  {selectedNode.type}
                </span>
              </div>
              <div>
                <p className="text-slate-400">Fraud Association</p>
                <p className="font-semibold mt-0.5">
                  {selectedNode.is_fraud ? (
                    <span className="text-rose-500 font-bold">Confirmed / High Risk</span>
                  ) : (
                    <span className="text-emerald-500 font-bold">Normal / Low Risk</span>
                  )}
                </p>
              </div>
              <button
                onClick={() => {
                  setSearchAccount(selectedNode.id);
                  handleSearch({ preventDefault: () => {} } as any);
                }}
                className="w-full mt-4 py-2 rounded-lg bg-slate-100 dark:bg-slate-800 hover:bg-indigo-600 hover:text-white transition-colors font-semibold text-xs text-slate-700 dark:text-slate-200"
              >
                Re-Center Graph
              </button>
            </div>
          ) : (
            <div className="text-xs text-slate-400 py-12 text-center">
              Click on any node in the graph viewport to inspect its properties and linkages.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
