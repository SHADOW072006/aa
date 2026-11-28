import { useEffect, useState, useRef } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core } from "cytoscape";
import {
  X,
  FileDown,
  ExternalLink,
  ShieldAlert,
  ShieldCheck,
  Flame,
  AlertTriangle,
  CheckCircle,
  Share2,
  Copy,
  Check,
  Phone,
  CreditCard,
  AtSign,
  Globe,
  Coins,
  Eye,
  Send,
  Users,
  ZoomIn,
  ZoomOut,
  Maximize2,
  RefreshCw,
  Info,
} from "lucide-react";
import {
  fetchChannelDetails,
  fetchChannelNetwork,
  expandChannelNetwork,
  getChannelPdfUrl,
  downloadAuthenticatedPdf,
  addChannel,
  deleteChannel,
  getChannelHealth,
} from "../api/client";
import type { ChannelDetails, ChannelNetworkData, NetworkExpandResult } from "../api/client";
import ScoreBreakdownPanel from "./ScoreBreakdownPanel";

interface Props {
  usernameOrId: string | number | null;
  onClose: () => void;
  onWatchStatusChange?: () => void;
}

const CY_MODAL_STYLESHEET = [
  {
    selector: "node",
    style: {
      "background-color": "data(color)",
      label: "data(label)",
      color: "#f8fafc",
      "font-size": "10px",
      "text-valign": "bottom",
      "text-margin-y": "5px",
      width: "data(degree)",
      height: "data(degree)",
      "min-width": 18,
      "min-height": 18,
      "max-width": 46,
      "max-height": 46,
      "font-weight": "bold",
    },
  },
  {
    selector: "node[?is_root]",
    style: {
      "border-width": 3,
      "border-color": "#ffffff",
      "font-size": "12px",
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.5,
      "line-color": "#475569",
      "curve-style": "bezier",
      opacity: 0.7,
      "target-arrow-shape": "triangle",
      "target-arrow-color": "#475569",
      "arrow-scale": 0.8,
    },
  },
  {
    selector: "node:selected",
    style: {
      "border-width": 3,
      "border-color": "#38bdf8",
      "background-color": "#0284c7",
    },
  },
];

export default function ChannelDetailModal({ usernameOrId, onClose, onWatchStatusChange }: Props) {
  const [activeTab, setActiveTab] = useState<"dossier" | "network" | "evidence" | "score">("dossier");
  const [details, setDetails] = useState<ChannelDetails | null>(null);
  const [network, setNetwork] = useState<ChannelNetworkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [watching, setWatching] = useState(false);
  const [watchLoading, setWatchLoading] = useState(false);
  const [selectedGraphNode, setSelectedGraphNode] = useState<any | null>(null);
  const [cyRef, setCyRef] = useState<Core | null>(null);
  const [expandResult, setExpandResult] = useState<NetworkExpandResult | null>(null);
  const [expanding, setExpanding] = useState(false);
  const [channelScore, setChannelScore] = useState<{
    composite_score: number;
    max_message_score: number;
    high_confidence_message_count: number;
    distinct_incident_count: number;
    recency_weight: number;
    identifier_density: number;
    valid_pivot_count: number;
    analyst_confirmation_signal: number;
    scored_at?: string;
  } | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);

  useEffect(() => {
    if (!usernameOrId) return;
    let isMounted = true;
    setLoading(true);
    setError(null);
    setExpandResult(null);

    Promise.all([
      fetchChannelDetails(usernameOrId),
      fetchChannelNetwork(usernameOrId).catch(() => null),
    ])
      .then(([det, net]) => {
        if (!isMounted) return;
        setDetails(det);
        setNetwork(net);
        setWatching(det.is_monitored);
        setLoading(false);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err?.response?.data?.detail ?? "Failed to load channel intelligence");
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [usernameOrId]);

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const handleToggleWatch = async () => {
    if (!details) return;
    setWatchLoading(true);
    try {
      if (watching && details.channel_id) {
        await deleteChannel(details.channel_id);
        setWatching(false);
      } else {
        await addChannel(details.username);
        setWatching(true);
      }
      onWatchStatusChange?.();
    } catch (e) {
      console.error(e);
    } finally {
      setWatchLoading(false);
    }
  };

  const handleExportPdf = () => {
    if (!usernameOrId) return;
    const url = getChannelPdfUrl(usernameOrId);
    void downloadAuthenticatedPdf(url, `telemonitor_${usernameOrId}_dossier.pdf`);
  };

  const handleSelectScoreTab = () => {
    setActiveTab("score");
    if (!details || channelScore !== null) return;
    const sc = (details as unknown as { score_components?: Record<string, number> }).score_components;
    if (sc && typeof sc.composite_score === "number") {
      setChannelScore({
        composite_score: sc.composite_score,
        max_message_score: sc.max_message_score ?? details.avg_score,
        high_confidence_message_count: sc.high_confidence_message_count ?? details.high_count,
        distinct_incident_count: sc.distinct_incident_count ?? details.flagged_count,
        recency_weight: sc.recency_weight ?? 1.0,
        identifier_density: sc.identifier_density ?? 0.0,
        valid_pivot_count: sc.valid_pivot_count ?? 0,
        analyst_confirmation_signal: sc.analyst_confirmation_signal ?? 0.0,
      });
      return;
    }
    if (!details.channel_id) return;
    setScoreLoading(true);
    getChannelHealth(details.channel_id)
      .then(() => {
        // Build a minimal score object from the channel details avg_score.
        // A full ChannelScoreComponents endpoint is not yet exposed; use
        // what we already have from the dossier payload.
        if (details) {
          setChannelScore({
            composite_score: details.avg_score,
            max_message_score: details.avg_score,
            high_confidence_message_count: details.high_count,
            distinct_incident_count: details.flagged_count,
            recency_weight: 1.0,
            identifier_density: 0.0,
            valid_pivot_count: 0,
            analyst_confirmation_signal: 0.0,
          });
        }
      })
      .catch(() => {
        // Even on health fetch failure, surface available score data.
        if (details) {
          setChannelScore({
            composite_score: details.avg_score,
            max_message_score: details.avg_score,
            high_confidence_message_count: details.high_count,
            distinct_incident_count: details.flagged_count,
            recency_weight: 1.0,
            identifier_density: 0.0,
            valid_pivot_count: 0,
            analyst_confirmation_signal: 0.0,
          });
        }
      })
      .finally(() => setScoreLoading(false));
  };

  if (!usernameOrId) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="relative w-full max-w-5xl bg-gray-900 border border-gray-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Bar */}
        <div className="flex items-start justify-between p-5 border-b border-gray-800 bg-gray-900/90">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center text-white font-bold text-xl shadow-lg shadow-blue-500/10">
              {details?.title ? details.title[0].toUpperCase() : "@"}
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-lg font-bold text-white">
                  {details ? details.title : `Channel @${usernameOrId}`}
                </h2>
                <span className="font-mono text-sm text-blue-400">
                  @{details?.username ?? usernameOrId}
                </span>

                {details?.is_verified && (
                  <span className="bg-blue-500/20 text-blue-400 border border-blue-500/30 text-xs px-2 py-0.5 rounded-full flex items-center gap-1 font-medium">
                    <CheckCircle size={11} /> Verified
                  </span>
                )}
                {details?.is_scam && (
                  <span className="bg-red-500/20 text-red-400 border border-red-500/30 text-xs px-2 py-0.5 rounded-full flex items-center gap-1 font-bold">
                    <ShieldAlert size={11} /> SCAM WARNING
                  </span>
                )}
                {details?.risk_level === "HIGH" && (
                  <span className="bg-red-500/20 text-red-400 border border-red-500/30 text-xs px-2 py-0.5 rounded-full flex items-center gap-1 font-bold">
                    <Flame size={12} /> HIGH THREAT
                  </span>
                )}
                {details?.risk_level === "MEDIUM" && (
                  <span className="bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 text-xs px-2 py-0.5 rounded-full flex items-center gap-1 font-bold">
                    <AlertTriangle size={12} /> MEDIUM THREAT
                  </span>
                )}
              </div>

              <div className="flex items-center gap-4 mt-1 text-xs text-gray-400">
                {details?.member_count != null && (
                  <span className="flex items-center gap-1">
                    <Users size={12} className="text-gray-500" />
                    <b>{details.member_count.toLocaleString()}</b> members
                  </span>
                )}
                {details?.telegram_id && (
                  <span className="font-mono text-gray-500">ID: {details.telegram_id}</span>
                )}
                {details && (
                  <span className="text-gray-400">
                    Threat Score:{" "}
                    <b className="text-white">{(details.avg_score * 100).toFixed(0)}%</b>
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleExportPdf}
              title="Download PDF Forensic Dossier"
              className="bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 text-xs px-3 py-2 rounded-xl flex items-center gap-1.5 font-medium transition-colors"
            >
              <FileDown size={14} />
              Export PDF
            </button>

            <button
              onClick={handleToggleWatch}
              disabled={watchLoading}
              className={`text-xs px-3 py-2 rounded-xl flex items-center gap-1.5 font-medium transition-colors ${
                watching
                  ? "bg-green-600/20 border border-green-500/30 text-green-300 hover:bg-green-600/30"
                  : "bg-blue-600 hover:bg-blue-700 text-white"
              }`}
            >
              {watching ? (
                <>
                  <CheckCircle size={14} /> In Watchlist
                </>
              ) : (
                <>
                  <ShieldCheck size={14} /> Add to Watchlist
                </>
              )}
            </button>

            <a
              href={details?.invite_link || `https://t.me/${details?.username ?? usernameOrId}`}
              target="_blank"
              rel="noreferrer"
              className="bg-gray-800 hover:bg-gray-700 text-gray-300 p-2 rounded-xl transition-colors border border-gray-700"
              title="Open in Telegram"
            >
              <ExternalLink size={16} />
            </a>

            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white p-2 rounded-xl hover:bg-gray-800 transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-gray-800 bg-gray-900 px-6 gap-6 text-sm">
          <button
            onClick={() => setActiveTab("dossier")}
            className={`py-3 font-medium flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "dossier"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            <Info size={16} /> Intelligence Dossier
          </button>
          <button
            onClick={() => setActiveTab("network")}
            className={`py-3 font-medium flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "network"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            <Share2 size={16} /> Connecting Nodes & Network ({network?.node_count ?? 0})
          </button>
          <button
            onClick={() => setActiveTab("evidence")}
            className={`py-3 font-medium flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "evidence"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            <ShieldAlert size={16} /> Intercepted Messages ({details?.sample_messages.length ?? 0})
          </button>
          <button
            onClick={handleSelectScoreTab}
            className={`py-3 font-medium flex items-center gap-2 border-b-2 transition-colors ${
              activeTab === "score"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-gray-400 hover:text-gray-200"
            }`}
          >
            <ShieldCheck size={16} /> Score
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 bg-gray-950">
          {loading && (
            <div className="flex items-center justify-center py-20 text-gray-400 gap-3">
              <RefreshCw size={20} className="animate-spin text-blue-500" />
              <span>Fetching intelligence profile and network nodes...</span>
            </div>
          )}

          {error && !loading && (
            <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-xl text-red-300 text-sm">
              {error}
            </div>
          )}

          {!loading && details && (
            <>
              {/* TAB 1: DOSSIER OVERVIEW */}
              {activeTab === "dossier" && (
                <div className="space-y-6">
                  {/* Summary Metric Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <div className="bg-gray-900 border border-gray-800 p-3.5 rounded-xl">
                      <div className="text-xs text-gray-500">Threat Score</div>
                      <div className="text-xl font-bold text-white mt-1">
                        {(details.avg_score * 100).toFixed(0)}%
                      </div>
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        Classification confidence
                      </div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 p-3.5 rounded-xl">
                      <div className="text-xs text-gray-500">Flagged Messages</div>
                      <div className="text-xl font-bold text-red-400 mt-1">
                        {details.flagged_count}
                      </div>
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        out of {details.messages_scanned} scanned
                      </div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 p-3.5 rounded-xl">
                      <div className="text-xs text-gray-500">High Risk Signals</div>
                      <div className="text-xl font-bold text-orange-400 mt-1">
                        {details.high_count}
                      </div>
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        Critical slang/crime hits
                      </div>
                    </div>
                    <div className="bg-gray-900 border border-gray-800 p-3.5 rounded-xl">
                      <div className="text-xs text-gray-500">Connected Nodes</div>
                      <div className="text-xl font-bold text-blue-400 mt-1">
                        {network?.node_count ?? 0}
                      </div>
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        Linked channels, admins, UPIs
                      </div>
                    </div>
                  </div>

                  {/* Channel Description / Bio */}
                  {details.description && (
                    <div className="bg-gray-900 border border-gray-800 p-4 rounded-xl">
                      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                        Channel Bio / Description
                      </div>
                      <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
                        {details.description}
                      </p>
                    </div>
                  )}

                  {/* Top Detected Crime Categories */}
                  {details.top_categories.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                        Detected Crime Categories
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {details.top_categories.map((c) => (
                          <span
                            key={c}
                            className="bg-gray-800 border border-gray-700 text-gray-200 text-xs px-2.5 py-1 rounded-lg flex items-center gap-1.5 font-medium"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                            {c.replace(/_/g, " ").toUpperCase()}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Extracted Financial & Contact Identifiers */}
                  <div>
                    <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5 flex items-center justify-between">
                      <span>Extracted Identifiers & Instruments</span>
                      <span className="text-gray-500 font-normal">
                        Click to copy value for investigation
                      </span>
                    </div>

                    {details.top_identifiers.length === 0 ? (
                      <div className="text-sm text-gray-600 italic bg-gray-900/50 p-4 rounded-xl border border-gray-800 text-center">
                        No phone, UPI, or crypto identifiers extracted from public posts yet.
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                        {details.top_identifiers.map((it, idx) => {
                          const key = `${it.type}-${it.value}-${idx}`;
                          const isCopied = copiedKey === key;
                          let icon = <Globe size={14} className="text-gray-400" />;
                          let badgeBg = "bg-gray-800 text-gray-300";

                          if (it.type === "phone") {
                            icon = <Phone size={14} className="text-red-400" />;
                            badgeBg = "bg-red-500/10 text-red-300 border-red-500/20";
                          } else if (it.type === "upi") {
                            icon = <CreditCard size={14} className="text-orange-400" />;
                            badgeBg = "bg-orange-500/10 text-orange-300 border-orange-500/20";
                          } else if (it.type.includes("wallet")) {
                            icon = <Coins size={14} className="text-yellow-400" />;
                            badgeBg = "bg-yellow-500/10 text-yellow-300 border-yellow-500/20";
                          } else if (it.type === "handle") {
                            icon = <AtSign size={14} className="text-purple-400" />;
                            badgeBg = "bg-purple-500/10 text-purple-300 border-purple-500/20";
                          }

                          return (
                            <div
                              key={key}
                              className="flex items-center justify-between bg-gray-900 border border-gray-800 rounded-xl px-3.5 py-2.5 hover:border-gray-700 transition-colors"
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                {icon}
                                <div className="min-w-0">
                                  <div className="text-xs font-mono text-white truncate max-w-[280px]">
                                    {it.value}
                                  </div>
                                  <div className="text-[10px] text-gray-500 uppercase tracking-wider">
                                    {it.type.replace(/_/g, " ")}
                                  </div>
                                </div>
                              </div>

                              <button
                                onClick={() => handleCopy(it.value, key)}
                                className="text-gray-500 hover:text-white p-1 rounded-md transition-colors"
                                title="Copy identifier"
                              >
                                {isCopied ? (
                                  <Check size={14} className="text-green-400" />
                                ) : (
                                  <Copy size={14} />
                                )}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: CONNECTING NODES & NETWORK */}
              {activeTab === "network" && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between bg-gray-900/60 p-3 rounded-xl border border-gray-800 text-xs">
                    <div className="flex items-center gap-4 flex-wrap">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-blue-500" /> Target Channel
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-pink-500" /> Linked Channel
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-purple-500" /> Admin Handle
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-orange-500" /> Payment UPI
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Phone
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full bg-cyan-500" /> Crypto Wallet
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => cyRef?.fit(undefined, 30)}
                        className="bg-gray-800 hover:bg-gray-700 text-gray-300 p-1.5 rounded-lg border border-gray-700"
                        title="Fit Network"
                      >
                        <Maximize2 size={13} />
                      </button>
                      <button
                        onClick={async () => {
                          const target = details?.username ?? usernameOrId;
                          if (!target) return;
                          setExpanding(true);
                          try {
                            const res = await expandChannelNetwork(target, { max_hops: 2, limit: 20, persist: false, verify: false });
                            setExpandResult(res);
                          } finally {
                            setExpanding(false);
                          }
                        }}
                        disabled={expanding}
                        className="bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 px-2.5 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1 disabled:opacity-50"
                        title="Expand syndicate network offline from stored links & shared identifiers"
                      >
                        <Share2 size={12} />
                        {expanding ? "Growing..." : "Grow network from here"}
                      </button>
                      <button
                        onClick={() => cyRef?.zoom(cyRef.zoom() * 1.25)}
                        className="bg-gray-800 hover:bg-gray-700 text-gray-300 p-1.5 rounded-lg border border-gray-700"
                        title="Zoom In"
                      >
                        <ZoomIn size={13} />
                      </button>
                      <button
                        onClick={() => cyRef?.zoom(cyRef.zoom() * 0.8)}
                        className="bg-gray-800 hover:bg-gray-700 text-gray-300 p-1.5 rounded-lg border border-gray-700"
                        title="Zoom Out"
                      >
                        <ZoomOut size={13} />
                      </button>
                    </div>
                  </div>

                  {/* Cytoscape Canvas */}
                  <div className="h-[380px] bg-gray-900 border border-gray-800 rounded-2xl relative overflow-hidden">
                    {network && network.elements.length > 0 ? (
                      <CytoscapeComponent
                        elements={network.elements as any}
                        stylesheet={CY_MODAL_STYLESHEET as any}
                        style={{ width: "100%", height: "100%" }}
                        layout={{
                          name: "concentric",
                          concentric: (node: any) => (node.data("is_root") ? 10 : 2),
                          levelWidth: () => 1,
                          padding: 40,
                          animate: true,
                        }}
                        cy={(cy) => {
                          setCyRef(cy);
                          cy.on("tap", "node", (evt) => {
                            setSelectedGraphNode(evt.target.data());
                          });
                        }}
                      />
                    ) : (
                      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
                        No network connections discovered yet for this channel.
                      </div>
                    )}
                  </div>

                  {/* Node Inspector Bar */}
                  {selectedGraphNode && (
                    <div className="bg-gray-900 border border-blue-500/40 p-3 rounded-xl flex items-center justify-between text-xs">
                      <div>
                        <span className="text-gray-400 font-medium">Selected Node: </span>
                        <span className="font-mono font-bold text-white ml-1">
                          {selectedGraphNode.label}
                        </span>
                        <span className="text-gray-500 ml-2">({selectedGraphNode.type})</span>
                      </div>
                      {selectedGraphNode.type === "channel" && !selectedGraphNode.is_root && (
                        <button
                          onClick={() => {
                            const chName = selectedGraphNode.label.replace(/^@/, "");
                            fetchChannelDetails(chName).then(setDetails);
                            fetchChannelNetwork(chName).then(setNetwork);
                          }}
                          className="text-blue-400 hover:text-blue-300 font-medium"
                        >
                          Inspect Channel →
                        </button>
                      )}
                    </div>
                  )}

                  {/* Expanded Network Frontier */}
                  {expandResult && (
                    <div className="bg-gray-900 border border-indigo-500/30 p-3 rounded-xl space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-indigo-300">
                          Offline Network Expansion ({expandResult.frontier_count} channels discovered)
                        </span>
                        <span className="text-[11px] text-gray-500">
                          BFS depth {expandResult.max_hops} · {expandResult.mode}
                        </span>
                      </div>
                      {expandResult.frontier.length === 0 ? (
                        <p className="text-gray-500">No additional linked channels found.</p>
                      ) : (
                        <div className="max-h-44 overflow-y-auto space-y-1.5">
                          {expandResult.frontier.map((item) => (
                            <div
                              key={item.username}
                              className="bg-gray-950/70 border border-gray-800 rounded-lg px-2.5 py-1.5 flex items-center justify-between gap-2"
                            >
                              <div className="min-w-0">
                                <span className="font-mono text-white font-medium">@{item.username}</span>
                                <span className="text-[10px] text-gray-500 ml-2">hop {item.hop}</span>
                                {item.evidence.length > 0 && (
                                  <p className="text-[10px] text-gray-400 font-mono truncate">
                                    {item.evidence.slice(0, 3).join(" · ")}
                                  </p>
                                )}
                              </div>
                              <div className="flex items-center gap-1 shrink-0">
                                {item.reasons.map((r) => (
                                  <span
                                    key={r}
                                    className="text-[10px] bg-indigo-950/60 border border-indigo-700/40 text-indigo-300 px-1.5 py-0.5 rounded"
                                  >
                                    {r}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Connection Lists */}
                  {network && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div className="bg-gray-900 border border-gray-800 p-3 rounded-xl">
                        <div className="text-gray-400 font-semibold mb-2 flex items-center justify-between">
                          <span>Linked Channels</span>
                          <span className="text-gray-500 font-normal">
                            {network.categories.channels?.length ?? 0}
                          </span>
                        </div>
                        <div className="space-y-1 max-h-32 overflow-y-auto">
                          {network.categories.channels?.map((c) => (
                            <div key={c} className="font-mono text-pink-400">
                              @{c}
                            </div>
                          ))}
                          {(!network.categories.channels || network.categories.channels.length === 0) && (
                            <span className="text-gray-600 italic">None</span>
                          )}
                        </div>
                      </div>

                      <div className="bg-gray-900 border border-gray-800 p-3 rounded-xl">
                        <div className="text-gray-400 font-semibold mb-2 flex items-center justify-between">
                          <span>Admins & Contacts</span>
                          <span className="text-gray-500 font-normal">
                            {network.categories.handles?.length ?? 0}
                          </span>
                        </div>
                        <div className="space-y-1 max-h-32 overflow-y-auto">
                          {network.categories.handles?.map((h) => (
                            <div key={h} className="font-mono text-purple-400">
                              @{h}
                            </div>
                          ))}
                          {(!network.categories.handles || network.categories.handles.length === 0) && (
                            <span className="text-gray-600 italic">None</span>
                          )}
                        </div>
                      </div>

                      <div className="bg-gray-900 border border-gray-800 p-3 rounded-xl">
                        <div className="text-gray-400 font-semibold mb-2 flex items-center justify-between">
                          <span>Payment UPIs & Crypto</span>
                          <span className="text-gray-500 font-normal">
                            {(network.categories.upis?.length ?? 0) + (network.categories.wallets?.length ?? 0)}
                          </span>
                        </div>
                        <div className="space-y-1 max-h-32 overflow-y-auto">
                          {network.categories.upis?.map((u) => (
                            <div key={u} className="font-mono text-orange-400 truncate">
                              {u}
                            </div>
                          ))}
                          {network.categories.wallets?.map((w) => (
                            <div key={w} className="font-mono text-cyan-400 truncate">
                              {w}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: EVIDENCE & INTERCEPTED MESSAGES */}
              {activeTab === "evidence" && (
                <div className="space-y-3">
                  {details.sample_messages.length === 0 ? (
                    <div className="text-center py-16 text-gray-500 text-sm">
                      No flagged messages recorded in this dataset yet.
                    </div>
                  ) : (
                    details.sample_messages.map((msg, i) => (
                      <div
                        key={i}
                        className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2 border-l-4 border-l-red-500"
                      >
                        <div className="flex items-center justify-between text-xs text-gray-400 flex-wrap gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-white font-bold">
                              Intercept #{i + 1}
                            </span>
                            <span className="bg-red-500/20 text-red-400 px-2 py-0.5 rounded text-[10px] font-bold">
                              {(msg.score * 100).toFixed(0)}% THREAT
                            </span>
                            {msg.date && (
                              <span className="text-gray-500">
                                {new Date(msg.date).toLocaleString()}
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-3 text-gray-500">
                            {msg.views != null && (
                              <span className="flex items-center gap-1">
                                <Eye size={12} /> {msg.views.toLocaleString()}
                              </span>
                            )}
                            {msg.forwards != null && (
                              <span className="flex items-center gap-1">
                                <Send size={12} /> {msg.forwards}
                              </span>
                            )}
                            {msg.id && details.username && (
                              <a
                                href={`https://t.me/${details.username}/${msg.id}`}
                                target="_blank"
                                rel="noreferrer"
                                className="text-blue-400 hover:text-blue-300 flex items-center gap-1"
                              >
                                View in TG <ExternalLink size={11} />
                              </a>
                            )}
                          </div>
                        </div>

                        {msg.matched_terms && msg.matched_terms.length > 0 && (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-[10px] text-gray-500 uppercase tracking-wider">
                              Keywords:
                            </span>
                            {msg.matched_terms.map((t) => (
                              <span
                                key={t}
                                className="bg-red-950/60 text-red-300 border border-red-800/60 px-1.5 py-0.5 rounded text-[11px] font-mono"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        )}

                        {msg.provenance_status && (
                          <div className="flex flex-wrap items-center gap-2 text-[11px]">
                            <span
                              className={`font-mono px-1.5 py-0.5 rounded border ${
                                msg.provenance_status === "verified_hashes"
                                  ? "bg-emerald-950/50 text-emerald-300 border-emerald-700/40"
                                  : msg.provenance_status === "unverifiable_media" ||
                                    msg.provenance_status === "missing_content"
                                  ? "bg-amber-950/50 text-amber-300 border-amber-700/40"
                                  : "bg-slate-800 text-slate-300 border-slate-700"
                              }`}
                            >
                              provenance: {msg.provenance_status}
                            </span>
                            {msg.provenance_status === "unverifiable_media" && (
                              <span className="text-amber-300">
                                {msg.provenance_note ??
                                  "Original media unavailable; provenance cannot be fully recomputed."}
                              </span>
                            )}
                          </div>
                        )}

                        <p className="text-xs font-mono text-gray-300 bg-black/40 p-3 rounded-lg leading-relaxed whitespace-pre-wrap">
                          {msg.text}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              )}
              {/* TAB 4: SCORE BREAKDOWN */}
              {activeTab === "score" && (
                <ScoreBreakdownPanel
                  score={channelScore}
                  loading={scoreLoading}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

