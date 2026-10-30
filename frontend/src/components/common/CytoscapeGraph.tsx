import React, { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

interface CytoscapeGraphProps {
  elements: {
    nodes: Array<{ data: any }>;
    edges: Array<{ data: any }>;
  };
  centerId?: string;
  onNodeClick?: (nodeId: string, nodeData: any) => void;
  height?: string;
}

export const CytoscapeGraph: React.FC<CytoscapeGraphProps> = ({
  elements,
  centerId,
  onNodeClick,
  height = "420px",
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Build elements payload
    const cyElements = [
      ...elements.nodes.map((n) => ({
        data: {
          id: n.data.id,
          label: n.data.label || n.data.id,
          type: n.data.type || "account",
          is_fraud: n.data.is_fraud || 0,
          is_center: n.data.id === centerId,
        },
      })),
      ...elements.edges.map((e, idx) => ({
        data: {
          id: `e_${idx}`,
          source: e.data.source,
          target: e.data.target,
          amount: e.data.amount,
          type: e.data.type || "TRANSFER",
          label: e.data.amount ? `₹${(e.data.amount / 1000).toFixed(0)}k` : "",
        },
      })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements: cyElements,
      boxSelectionEnabled: false,
      autounselectify: true,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-valign": "bottom",
            "text-margin-y": 6,
            "font-size": "10px",
            "font-family": "Inter, sans-serif",
            color: "#64748B",
            width: 32,
            height: 32,
            "background-color": "#4F46E5",
            "border-width": 2,
            "border-color": "#FFFFFF",
          },
        },
        {
          selector: 'node[type = "device"]',
          style: {
            shape: "round-rectangle",
            "background-color": "#8B5CF6", // Purple for hardware device
            width: 30,
            height: 30,
          },
        },
        {
          selector: "node[is_fraud = 1]",
          style: {
            "background-color": "#EF4444", // Red for confirmed/suspect fraud
            "border-color": "#FCA5A5",
            "border-width": 3,
          },
        },
        {
          selector: "node[?is_center]",
          style: {
            width: 44,
            height: 44,
            "border-color": "#F59E0B", // Gold border for focal center node
            "border-width": 4,
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#CBD5E1",
            "target-arrow-color": "#94A3B8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": "9px",
            "text-background-opacity": 0.8,
            "text-background-color": "#FFFFFF",
            "text-background-padding": "2px",
            color: "#475569",
          },
        },
        {
          selector: 'edge[type = "USED_DEVICE"]',
          style: {
            "line-style": "dashed",
            "line-color": "#C4B5FD",
            "target-arrow-shape": "none",
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        nodeDimensionsIncludeLabels: true,
        padding: 30,
      },
    });

    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      if (onNodeClick) {
        onNodeClick(node.id(), node.data());
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, [elements, centerId]);

  return (
    <div className="relative w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 overflow-hidden">
      <div ref={containerRef} style={{ height, width: "100%" }} />

      {/* Graph Legend */}
      <div className="absolute bottom-3 left-3 bg-white/90 dark:bg-slate-900/90 backdrop-blur-sm border border-slate-200 dark:border-slate-800 px-3 py-2 rounded-lg text-[11px] shadow-sm flex items-center gap-4 text-slate-600 dark:text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-indigo-600" /> Account
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-rose-500" /> Flagged / Fraud
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded bg-purple-500" /> Hardware Device
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full border-2 border-amber-400 bg-indigo-600" /> Center Node
        </span>
      </div>
    </div>
  );
};
