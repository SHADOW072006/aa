import { useEffect, useState, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core } from "cytoscape";
import { fetchGraph, fetchEgoGraph, expandChannelNetwork, api } from "../api/client";
import type { GraphData, NetworkExpandResult } from "../api/client";
import { Share2, ZoomIn, ZoomOut, Maximize2, Focus, RotateCcw, Search } from "lucide-react";

interface ClusterSummary {
  size: number;
  members: string[];
}

interface SelectedNodeInfo {
  id: string;
  label: string;
  raw: string;
  type: string;
  degree: number;
  neighbors: Array<{ id: string; label: string; type: string; reason: string }>;
}

const CY_STYLESHEET = [
  {
    selector: "node",
    style: {
      "background-color": "data(color)",
      label: "data(label)",
      color: "#e2e8f0",
      "font-size": "10px",
      "text-outline-width": 2,
      "text-outline-color": "#090d16",
      "text-valign": "bottom",
      "text-margin-y": "5px",
      width: "mapData(degree, 1, 20, 20, 46)",
      height: "mapData(degree, 1, 20, 20, 46)",
    },
  },
  {
    selector: "node[type='channel']",
    style: {
      shape: "round-rectangle",
      "border-width": 2,
      "border-color": "#93c5fd",
      "font-weight": "bold",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#475569",
      opacity: 0.75,
      "curve-style": "bezier",
    },
  },
  {
    selector: "edge[reason*='near_duplicate_image']",
    style: {
      "line-color": "#06b6d4",
      "line-style": "dashed",
      width: 2.5,
    },
  },
  {
    selector: "edge[reason*='near_duplicate_text']",
    style: {
      "line-color": "#f59e0b",
      "line-style": "dashed",
      width: 2.5,
    },
  },
  {
    selector: "edge[reason*='forwarded_from']",
    style: {
      "line-color": "#a855f7",
      width: 2.5,
    },
  },
  {
    selector: "node:selected",
    style: {
      "border-width": 3,
      "border-color": "#ffffff",
    },
  },
];

export default function GraphPage() {
  const navigate = useNavigate();
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [clusters, setClusters] = useState<ClusterSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [egoNode, setEgoNode] = useState<string | null>(null);
  const [selectedInfo, setSelectedInfo] = useState<SelectedNodeInfo | null>(null);
  const [filterMode, setFilterMode] = useState<"syndicate" | "all" | "channels" | "actors">("syndicate");
  const [layoutName, setLayoutName] = useState<"cose" | "concentric" | "circle" | "breadthfirst">("cose");
  const [expandResult, setExpandResult] = useState<NetworkExpandResult | null>(null);
  const [expanding, setExpanding] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [cyRef, setCyRef] = useState<Core | null>(null);

  const loadFull = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, clusterRes] = await Promise.all([
        fetchGraph(500),
        api.get<{ cluster_count: number; clusters: ClusterSummary[] }>("/graph/clusters").then((r) => r.data).catch(() => null),
      ]);
      setGraphData(data);
      if (clusterRes?.clusters) setClusters(clusterRes.clusters);
      setEgoNode(null);
      setSelectedInfo(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load entity graph");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEgo = useCallback(async (nodeId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEgoGraph(nodeId, 2);
      setGraphData(data);
      setEgoNode(nodeId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load ego graph");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFull();
  }, [loadFull]);

  const filteredElements = useMemo(() => {
    if (!graphData) return [];
    const rawEls = graphData.elements;
    const term = searchTerm.trim().toLowerCase();

    const nodes = rawEls.filter((el) => !("source" in el.data));
    const edges = rawEls.filter((el) => "source" in el.data);

    // Count degree per node in the current graph
    const degMap = new Map<string, number>();
    for (const ed of edges) {
      const s = String(ed.data.source ?? "");
      const t = String(ed.data.target ?? "");
      degMap.set(s, (degMap.get(s) ?? 0) + 1);
      degMap.set(t, (degMap.get(t) ?? 0) + 1);
    }

    const keptIds = new Set<string>();
    const keptNodes = nodes.filter((el) => {
      const id = String(el.data.id ?? "");
      const typ = String(el.data.type ?? "");
      const label = String(el.data.label ?? "").toLowerCase();
      if (filterMode === "channels" && typ !== "channel") return false;
      if (filterMode === "actors" && typ === "channel") return false;
      if (filterMode === "syndicate" && !term && !egoNode) {
        // Keep channels and multi-linked hub identifiers (degree >= 2)
        if (typ !== "channel" && (degMap.get(id) ?? 0) < 2) return false;
      }
      if (term && !id.toLowerCase().includes(term) && !label.includes(term)) return false;
      keptIds.add(id);
      return true;
    });

    const keptEdges = edges.filter(
      (el) =>
        keptIds.has(String(el.data.source ?? "")) &&
        keptIds.has(String(el.data.target ?? ""))
    );
    return [...keptNodes, ...keptEdges];
  }, [graphData, filterMode, searchTerm, egoNode]);

  const inspectNode = useCallback(
    (nodeId: string) => {
      if (!graphData) return;
      const nodes = graphData.elements.filter((el) => !("source" in el.data));
      const edges = graphData.elements.filter((el) => "source" in el.data);
      const nodeEl = nodes.find((n) => String(n.data.id) === nodeId);
      if (!nodeEl) return;

      const nodeById = new Map(nodes.map((n) => [String(n.data.id), n]));
      const neighbors: SelectedNodeInfo["neighbors"] = [];
      for (const ed of edges) {
        const s = String(ed.data.source);
        const t = String(ed.data.target);
        if (s === nodeId || t === nodeId) {
          const otherId = s === nodeId ? t : s;
          const other = nodeById.get(otherId);
          if (other) {
            neighbors.push({
              id: otherId,
              label: String(other.data.label ?? otherId),
              type: String(other.data.type ?? "unknown"),
              reason: String(ed.data.reason ?? "shared_identifier"),
            });
          }
        }
      }
      setSelectedInfo({
        id: nodeId,
        label: String(nodeEl.data.label ?? nodeId),
        raw: String(nodeEl.data.raw ?? nodeId),
        type: String(nodeEl.data.type ?? "unknown"),
        degree: Number(nodeEl.data.degree ?? neighbors.length),
        neighbors,
      });
    },
    [graphData]
  );

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Share2 size={20} className="text-blue-400" /> Entity &amp; Syndicate Graph
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Channels and identifiers linked by shared contacts, forwards, and near-duplicate media/text. Click a node to inspect connections or focus its 2-hop ego network.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {egoNode && (
            <button
              onClick={loadFull}
              className="flex items-center gap-1.5 text-xs bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/40 text-blue-300 px-3 py-1.5 rounded-lg"
            >
              <RotateCcw size={12} /> Full graph
            </button>
          )}
          <button
            onClick={() => cyRef?.zoom((cyRef.zoom() || 1) * 1.25)}
            className="p-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-lg"
            title="Zoom in"
          >
            <ZoomIn size={14} />
          </button>
          <button
            onClick={() => cyRef?.zoom((cyRef.zoom() || 1) * 0.8)}
            className="p-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-lg"
            title="Zoom out"
          >
            <ZoomOut size={14} />
          </button>
          <button
            onClick={() => cyRef?.fit(undefined, 30)}
            className="p-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-lg"
            title="Fit to screen"
          >
            <Maximize2 size={14} />
          </button>
        </div>
      </div>

      {/* Filter & Search bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex rounded-lg overflow-hidden border border-gray-800 text-xs">
          {(
            [
              ["syndicate", "Syndicate Hubs"],
              ["all", "All Nodes"],
              ["channels", "Channels Only"],
              ["actors", "Identifiers Only"],
            ] as const
          ).map(([mode, label]) => (
            <button
              key={mode}
              onClick={() => setFilterMode(mode)}
              className={`px-3 py-1.5 ${
                filterMode === mode
                  ? "bg-blue-600 text-white"
                  : "bg-gray-900 text-gray-400 hover:bg-gray-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Filter nodes by handle, phone, UPI, channel..."
          className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-1.5 text-xs text-gray-200 placeholder-gray-600 w-64 focus:outline-none focus:border-blue-500"
        />
        <select
          value={layoutName}
          onChange={(e) => setLayoutName(e.target.value as typeof layoutName)}
          className="bg-gray-900 border border-gray-800 rounded-lg px-2.5 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500"
          title="Graph layout algorithm"
        >
          <option value="cose">Force (Cose)</option>
          <option value="concentric">Concentric Hubs</option>
          <option value="breadthfirst">Hierarchy</option>
          <option value="circle">Circle</option>
        </select>
        {graphData && (
          <div className="flex gap-4 text-xs text-gray-400 ml-auto">
            <span>Nodes: <strong className="text-white">{graphData.node_count}</strong></span>
            <span>Edges: <strong className="text-white">{graphData.edge_count}</strong></span>
            <span>Clusters: <strong className="text-white">{graphData.cluster_count}</strong></span>
            {egoNode && <span className="text-blue-400">Ego: <strong>{egoNode}</strong></span>}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 text-xs text-amber-300 bg-amber-950/40 border border-amber-700/40 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-3 mb-3 flex-wrap text-xs items-center">
        {[
          ["#3b82f6", "Channel"],
          ["#ef4444", "Phone"],
          ["#f97316", "UPI"],
          ["#8b5cf6", "Handle"],
          ["#06b6d4", "USDT Wallet"],
          ["#f59e0b", "Bank Account"],
          ["#ec4899", "Site"],
          ["#10b981", "Email"],
        ].map(([color, label]) => (
          <span key={label} className="flex items-center gap-1.5 text-gray-400">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
        <span className="text-gray-600 mx-1">|</span>
        <span className="text-cyan-400">- - Near-Dup Image</span>
        <span className="text-amber-400">- - Near-Dup Text</span>
        <span className="text-purple-400">― Forwarded</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Cytoscape canvas */}
        <div className="lg:col-span-3 cy-container relative bg-gray-900/50 border border-gray-800 rounded-xl overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900/70 z-10 rounded-lg">
              <span className="text-gray-400 text-sm">Building graph…</span>
            </div>
          )}
          {filteredElements.length > 0 ? (
            <CytoscapeComponent
              key={`${filterMode}-${layoutName}-${egoNode ?? "full"}-${filteredElements.length}`}
              elements={filteredElements}
              stylesheet={CY_STYLESHEET as never}
              layout={{
                name: layoutName,
                animate: false,
                nodeRepulsion: 800000,
                idealEdgeLength: 130,
                edgeElasticity: 200,
                gravity: 0.25,
                padding: 40,
              } as never}
              style={{ width: "100%", height: "600px" }}
              cy={(cy) => {
                setCyRef(cy);
                cy.off("tap", "node");
                cy.on("tap", "node", (evt) => {
                  const id = evt.target.id() as string;
                  inspectNode(id);
                });
              }}
            />
          ) : !loading ? (
            <div className="flex items-center justify-center h-[400px] text-gray-500 text-sm">
              {error ? error : "No matching nodes in graph."}
            </div>
          ) : null}
        </div>

        {/* Right Inspector & Clusters Panel */}
        <div className="space-y-4">
          {selectedInfo ? (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-blue-950/60 text-blue-300 border border-blue-700/40">
                    {selectedInfo.type}
                  </span>
                  <p className="text-sm font-mono text-white font-semibold break-all mt-1">
                    {selectedInfo.raw}
                  </p>
                  <p className="text-xs text-gray-500">
                    {selectedInfo.neighbors.length} visible connections (degree {selectedInfo.degree})
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => loadEgo(selectedInfo.id)}
                  className="flex-1 flex items-center justify-center gap-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-3 py-1.5 font-medium"
                >
                  <Focus size={12} /> 2-Hop Ego
                </button>
                {selectedInfo.type === "channel" ? (
                  <button
                    onClick={async () => {
                      setExpanding(true);
                      try {
                        const res = await expandChannelNetwork(selectedInfo.raw, {
                          max_hops: 2,
                          limit: 20,
                          persist: false,
                          verify: false,
                        });
                        setExpandResult(res);
                      } finally {
                        setExpanding(false);
                      }
                    }}
                    disabled={expanding}
                    className="flex items-center justify-center gap-1 text-xs bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 rounded-lg px-2.5 py-1.5 font-medium disabled:opacity-50"
                    title="Expand network offline from stored links & shared identifiers"
                  >
                    <Share2 size={12} /> {expanding ? "Growing..." : "Grow network"}
                  </button>
                ) : (
                  <button
                    onClick={() => navigate(`/search?q=${encodeURIComponent(selectedInfo.raw)}`)}
                    className="flex items-center justify-center gap-1 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 rounded-lg px-3 py-1.5 font-medium"
                    title="Search where this identifier is used and export PDF"
                  >
                    <Search size={12} /> Search
                  </button>
                )}
              </div>
              {expandResult && expandResult.root_username.toLowerCase() === selectedInfo.raw.toLowerCase() && (
                <div className="bg-gray-950/80 border border-indigo-500/30 rounded-lg p-2.5 space-y-1.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-indigo-300 font-semibold">
                      Frontier ({expandResult.frontier_count} channels)
                    </span>
                    <span className="text-gray-500">BFS {expandResult.max_hops}-hop</span>
                  </div>
                  <div className="max-h-40 overflow-y-auto space-y-1">
                    {expandResult.frontier.map((item) => (
                      <div
                        key={item.username}
                        className="text-[11px] bg-gray-900 border border-gray-800 rounded px-2 py-1"
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="font-mono text-white truncate">@{item.username}</span>
                          <span className="text-[10px] text-indigo-300 shrink-0">
                            {item.reasons.join(", ")}
                          </span>
                        </div>
                        {item.evidence.length > 0 && (
                          <p className="text-[10px] text-gray-500 font-mono truncate">
                            {item.evidence.slice(0, 2).join(" · ")}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="max-h-72 overflow-y-auto space-y-1.5 pt-1 border-t border-gray-800">
                {selectedInfo.neighbors.map((n, idx) => (
                  <button
                    key={`${n.id}-${idx}`}
                    onClick={() => inspectNode(n.id)}
                    className="w-full text-left flex items-center justify-between gap-2 text-xs bg-gray-950/70 hover:bg-gray-800 rounded px-2 py-1.5 border border-gray-800/80"
                  >
                    <span className="font-mono text-gray-200 truncate">{n.label}</span>
                    <span className="text-[10px] text-gray-400 shrink-0">{n.reason}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-xs text-gray-500">
              Click any node in the graph to inspect its linked channels, shared identifiers, and edge reasons.
            </div>
          )}

          {clusters.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
              <h2 className="text-xs font-bold text-gray-300 uppercase tracking-wider">
                Syndicate Clusters ({clusters.length})
              </h2>
              <div className="max-h-72 overflow-y-auto space-y-1.5">
                {clusters.slice(0, 12).map((cl, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      if (cl.members[0]) {
                        loadEgo(cl.members[0]);
                      }
                    }}
                    className="w-full text-left bg-gray-950/60 hover:bg-gray-800 border border-gray-800 rounded-lg px-2.5 py-2 transition-colors"
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-white font-semibold">Cluster #{idx + 1}</span>
                      <span className="text-blue-400 font-mono">{cl.size} nodes</span>
                    </div>
                    <p className="text-[11px] text-gray-500 font-mono truncate mt-0.5">
                      {cl.members.slice(0, 4).join(", ")}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
