import React, { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import { ZoomIn, ZoomOut, Maximize2, Layers } from "lucide-react";

export interface ParticipantNodeData {
  account_id: string;
  display_name: string;
  balance: number;
  device_id: string;
  raw_ip?: string;
  network_prefix?: string;
  masked_ip?: string;
  network_label: string;
  is_simulated_network?: boolean;
  is_bot: boolean;
  engine_status?: "NORMAL" | "MONITORING" | "HELD" | "BLOCKED";
  fan_in_count?: number;
  inflow?: number;
  outflow?: number;
  pass_through?: number;
  reasons?: string[];
  role_card?: any;
}

export interface MoneyTransferEdgeData {
  txn_id?: string;
  sender_id: string;
  receiver_id: string;
  amount: number;
  status?: string;
  tier?: string;
  timestamp?: number;
}

interface LiveMoneyFlowGraphProps {
  participants: ParticipantNodeData[];
  transfers: MoneyTransferEdgeData[];
  showDevicesAndNetworks: boolean;
  onSelectParticipant?: (p: ParticipantNodeData) => void;
  height?: string;
}

export const LiveMoneyFlowGraph: React.FC<LiveMoneyFlowGraphProps> = ({
  participants,
  transfers,
  showDevicesAndNetworks,
  onSelectParticipant,
  height = "420px",
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [singleSharedNetworkNote, setSingleSharedNetworkNote] = useState<string | null>(null);

  // Status Color Map for Node Rings
  const getStatusColor = (status?: string) => {
    switch (status) {
      case "BLOCKED":
        return "#EF4444"; // Red ring
      case "HELD":
        return "#3B82F6"; // Blue ring
      case "MONITORING":
        return "#F59E0B"; // Amber ring
      default:
        return "#10B981"; // Emerald green ring
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;

    // Detect if all active participants share exactly one network label
    const userNetworks = new Set<string>();
    participants.forEach((p) => {
      if (p.network_label) userNetworks.add(p.network_label);
    });

    const isSingleSharedNetwork = userNetworks.size === 1 && participants.length > 1;
    const sharedNetName = isSingleSharedNetwork ? Array.from(userNetworks)[0] : null;
    setSingleSharedNetworkNote(
      isSingleSharedNetwork && showDevicesAndNetworks
        ? `All on ${sharedNetName} (ignored as a weak signal)`
        : null
    );

    // Build Cytoscape Elements
    const elements: any[] = [];

    // 1. Account Nodes
    participants.forEach((p) => {
      const inflow = p.inflow || 0;
      // Node size grows smoothly with received inflow
      const size = Math.min(68, Math.max(42, 42 + Math.sqrt(inflow) * 0.35));
      const ringColor = getStatusColor(p.engine_status);
      const fanIn = p.fan_in_count || 0;

      // Construct readable projector label
      let label = `${p.display_name}\n₹${Math.round(p.balance).toLocaleString()}`;
      if (fanIn >= 2) {
        label += `\n⚠️ ${fanIn} senders`;
      }

      elements.push({
        group: "nodes",
        data: {
          id: p.account_id,
          label: label,
          node_type: "account",
          ring_color: ringColor,
          size: size,
          participant: p,
        },
      });

      // Optional Device & Network layer (When ON)
      if (showDevicesAndNetworks) {
        // Devices as small grey squares
        if (p.device_id && !p.is_bot) {
          const devId = `dev_${p.device_id}`;
          if (!elements.find((e) => e.data.id === devId)) {
            elements.push({
              group: "nodes",
              data: {
                id: devId,
                label: p.device_id,
                node_type: "device",
                size: 26,
              },
            });
          }
          elements.push({
            group: "edges",
            data: {
              id: `edge_dev_${p.account_id}_${p.device_id}`,
              source: p.account_id,
              target: devId,
              edge_type: "DEVICE_LINK",
            },
          });
        }

        // Networks as hexagons (Only if multi-network! Ignored if single shared Wi-Fi)
        if (!isSingleSharedNetwork && p.network_label) {
          const netId = `net_${p.network_label}`;
          if (!elements.find((e) => e.data.id === netId)) {
            elements.push({
              group: "nodes",
              data: {
                id: netId,
                label: p.network_label,
                node_type: "network",
                size: 28,
              },
            });
          }
          elements.push({
            group: "edges",
            data: {
              id: `edge_net_${p.account_id}_${p.network_label}`,
              source: p.account_id,
              target: netId,
              edge_type: "NETWORK_LINK",
            },
          });
        }
      }
    });

    // 2. Money Flow Edges (Directed arrows with amounts)
    // Consolidate recent transfers between pairs to prevent clutter
    const edgeMap = new Map<string, { sender: string; receiver: string; totalAmount: number; isRecent: boolean }>();
    const now = Date.now();

    transfers.forEach((t) => {
      if (!t.sender_id || !t.receiver_id || t.sender_id === t.receiver_id) return;
      const key = `${t.sender_id}->${t.receiver_id}`;
      const existing = edgeMap.get(key);
      const isWithinPulse = t.timestamp ? now - t.timestamp * 1000 < 3000 : false;

      if (existing) {
        existing.totalAmount += t.amount;
        if (isWithinPulse) existing.isRecent = true;
      } else {
        edgeMap.set(key, {
          sender: t.sender_id,
          receiver: t.receiver_id,
          totalAmount: t.amount,
          isRecent: isWithinPulse,
        });
      }
    });

    edgeMap.forEach((edge, key) => {
      const width = Math.min(8, Math.max(2.5, Math.sqrt(edge.totalAmount) / 12));
      elements.push({
        group: "edges",
        data: {
          id: `tx_${key}`,
          source: edge.sender,
          target: edge.receiver,
          label: `₹${Math.round(edge.totalAmount).toLocaleString()}`,
          width: width,
          is_recent: edge.isRecent,
          edge_type: "TRANSFER",
        },
      });
    });

    // Initialize Cytoscape Instance
    const cy = cytoscape({
      container: containerRef.current,
      elements: elements,
      boxSelectionEnabled: false,
      autounselectify: true,
      style: [
        // ── ACCOUNT NODES ───────────────────────────────────────────
        {
          selector: 'node[node_type = "account"]',
          style: {
            shape: "ellipse",
            width: "data(size)",
            height: "data(size)",
            "background-color": "#1E293B",
            "border-width": 4,
            "border-color": "data(ring_color)",
            label: "data(label)",
            "font-size": "12px",
            "font-weight": 700,
            "font-family": "Inter, system-ui, sans-serif",
            color: "#F8FAFC",
            "text-valign": "center",
            "text-halign": "center",
            "text-wrap": "wrap",
            "text-max-width": "110px",
            "text-outline-color": "#0F172A",
            "text-outline-width": 2.5,
            "text-outline-opacity": 0.9,
          },
        },
        // ── DEVICE NODES (Grey small squares) ───────────────────────
        {
          selector: 'node[node_type = "device"]',
          style: {
            shape: "round-rectangle",
            width: 26,
            height: 26,
            "background-color": "#64748B",
            "border-width": 1.5,
            "border-color": "#94A3B8",
            label: "data(label)",
            "font-size": "9px",
            "font-family": "monospace",
            color: "#94A3B8",
            "text-valign": "bottom",
            "text-margin-y": 4,
          },
        },
        // ── NETWORK NODES (Cyan hexagons) ───────────────────────────
        {
          selector: 'node[node_type = "network"]',
          style: {
            shape: "hexagon",
            width: 28,
            height: 28,
            "background-color": "#0284C7",
            "border-width": 1.5,
            "border-color": "#38BDF8",
            label: "data(label)",
            "font-size": "9px",
            color: "#38BDF8",
            "text-valign": "bottom",
            "text-margin-y": 4,
          },
        },
        // ── MONEY TRANSFER EDGES (Directed Arrows with Amount) ───────
        {
          selector: 'edge[edge_type = "TRANSFER"]',
          style: {
            width: "data(width)",
            "line-color": "#6366F1",
            "target-arrow-color": "#6366F1",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.2,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "11px",
            "font-weight": 700,
            "font-family": "Inter, sans-serif",
            color: "#FFFFFF",
            "text-background-opacity": 0.95,
            "text-background-color": "#0F172A",
            "text-background-padding": "3px",
            "text-background-shape": "roundrectangle",
            "text-border-width": 1,
            "text-border-color": "#4338CA",
          },
        },
        // Recent Pulse Edge
        {
          selector: "edge[?is_recent]",
          style: {
            "line-color": "#A855F7",
            "target-arrow-color": "#A855F7",
            width: 6,
          },
        },
        // Dotted links for hardware/network associations
        {
          selector: 'edge[edge_type = "DEVICE_LINK"], edge[edge_type = "NETWORK_LINK"]',
          style: {
            width: 1,
            "line-style": "dotted",
            "line-color": "#475569",
            opacity: 0.45,
            "target-arrow-shape": "none",
            "curve-style": "bezier",
          },
        },
      ],
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 40,
        spacingFactor: 1.2,
        animate: false,
      },
    });

    // Fit with generous padding so no nodes are clipped
    cy.fit(undefined, 40);

    // Click handler for node inspection side card
    cy.on("tap", 'node[node_type = "account"]', (evt) => {
      const p = evt.target.data("participant");
      if (p && onSelectParticipant) {
        onSelectParticipant(p);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, [participants, transfers, showDevicesAndNetworks]);

  // Fit & Zoom helper functions
  const handleFit = () => {
    cyRef.current?.fit(undefined, 40);
  };
  const handleZoomIn = () => {
    if (!cyRef.current) return;
    cyRef.current.zoom(cyRef.current.zoom() * 1.25);
  };
  const handleZoomOut = () => {
    if (!cyRef.current) return;
    cyRef.current.zoom(cyRef.current.zoom() * 0.8);
  };

  return (
    <div className="relative w-full rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-900/90 overflow-hidden shadow-inner flex flex-col">
      {/* ── TOP CONTROLS & SHARED NETWORK NOTE ── */}
      <div className="absolute top-3 left-3 right-3 z-10 flex items-center justify-between pointer-events-none">
        {/* Single Shared Network Note */}
        {singleSharedNetworkNote ? (
          <div className="pointer-events-auto px-3 py-1 rounded-full bg-slate-800/90 border border-slate-700 text-slate-300 text-[11px] font-semibold backdrop-blur-md shadow-md flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            <span>{singleSharedNetworkNote}</span>
          </div>
        ) : <div />}

        {/* Zoom & Fit Action Buttons */}
        <div className="pointer-events-auto flex items-center gap-1 bg-slate-800/90 border border-slate-700 p-1 rounded-xl backdrop-blur-md shadow-md">
          <button
            onClick={handleZoomIn}
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-700 transition-all"
            title="Zoom In"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-700 transition-all"
            title="Zoom Out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleFit}
            className="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-slate-700 transition-all flex items-center gap-1 text-[11px] font-bold"
            title="Fit to Screen"
          >
            <Maximize2 className="w-3.5 h-3.5" />
            <span>Fit</span>
          </button>
        </div>
      </div>

      {/* ── CANVAS VIEWPORT ── */}
      <div ref={containerRef} style={{ height, width: "100%" }} />

      {/* ── OUTSIDE CANVAS LEGEND (SHOWING ONLY ACTIVE TYPES) ── */}
      <div className="p-3 bg-slate-950/80 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500">
            Node Status Ring:
          </span>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-emerald-500 bg-slate-900" />
            <span className="text-slate-300 font-medium">Normal</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-amber-500 bg-slate-900" />
            <span className="text-slate-300 font-medium">Monitoring</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-blue-500 bg-slate-900" />
            <span className="text-slate-300 font-medium">Held in Review</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full border-2 border-rose-500 bg-slate-900" />
            <span className="text-slate-300 font-medium">Blocked</span>
          </div>

          {showDevicesAndNetworks && (
            <>
              <div className="flex items-center gap-1.5 pl-2 border-l border-slate-800">
                <span className="w-2.5 h-2.5 rounded-sm bg-slate-500" />
                <span className="text-slate-300 font-medium">Device</span>
              </div>
              {!singleSharedNetworkNote && (
                <div className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded bg-sky-500" />
                  <span className="text-slate-300 font-medium">Subnet</span>
                </div>
              )}
            </>
          )}
        </div>

        <div className="text-[11px] text-slate-500 italic">
          Click any node to inspect profile & risk reasons
        </div>
      </div>
    </div>
  );
};
