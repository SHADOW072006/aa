import { useEffect, useState, useCallback, useRef } from "react";
import {
  ScanSearch,
  Play,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  AlertTriangle,
  Flame,
  Plus,
  Clock,
  FileDown,
  Search,
  Share2,
  Users,
  ShieldAlert,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import {
  runScan,
  fetchScanJobs,
  fetchScanJob,
  cancelScanJob,
  fetchScanResults,
  addChannelFromScan,
  fetchDefaultSeeds,
  getScanJobPdfUrl,
  getScanResultPdfUrl,
  downloadAuthenticatedPdf,
} from "../api/client";
import type { ScanJob, ChannelScanResult } from "../api/client";
import ChannelDetailModal from "../components/ChannelDetailModal";
import ScanEvidencePanel from "../components/ScanEvidencePanel";

const RISK_BADGE: Record<string, string> = {
  HIGH: "bg-red-500/20 text-red-400 border border-red-500/30",
  MEDIUM: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  LOW: "bg-gray-700/50 text-gray-400 border border-gray-700",
};
const RISK_ROW: Record<string, string> = {
  HIGH: "border-l-4 border-red-500",
  MEDIUM: "border-l-4 border-yellow-500",
  LOW: "border-l-4 border-gray-700",
};
const RISK_ICON: Record<string, JSX.Element> = {
  HIGH: <Flame size={12} className="inline mr-1 text-red-400" />,
  MEDIUM: <AlertTriangle size={12} className="inline mr-1 text-yellow-400" />,
  LOW: <CheckCircle size={12} className="inline mr-1 text-gray-500" />,
};

function RiskBadge({ level }: { level: string }) {
  return (
    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${RISK_BADGE[level] ?? RISK_BADGE.LOW}`}>
      {RISK_ICON[level]}
      {level}
    </span>
  );
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="w-full bg-gray-800 rounded-full h-1.5 mt-1">
      <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

function ResultRow({
  result,
  jobId,
  onAdded,
  onInspect,
}: {
  result: ChannelScanResult;
  jobId: number;
  onAdded: (id: number) => void;
  onInspect: (username: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(result.already_monitored);

  const handleAdd = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setAdding(true);
    try {
      await addChannelFromScan(jobId, result.id);
      setAdded(true);
      onAdded(result.id);
    } finally {
      setAdding(false);
    }
  };

  const handleDownloadPdf = (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = getScanResultPdfUrl(result.id);
    void downloadAuthenticatedPdf(url, `telemonitor_${result.channel_username}_dossier.pdf`);
  };

  return (
    <div className={`bg-gray-900 rounded-xl mb-2 transition-all hover:bg-gray-850 ${RISK_ROW[result.risk_level]}`}>
      {/* Summary row */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onInspect(result.channel_username);
              }}
              className="font-mono text-sm text-white hover:text-blue-400 font-bold transition-colors underline-offset-2 hover:underline"
              title="Click to view full channel intelligence & network"
            >
              @{result.channel_username}
            </button>
            {result.channel_title && (
              <span className="text-xs text-gray-400 truncate max-w-[200px]">
                {result.channel_title}
              </span>
            )}
            <RiskBadge level={result.risk_level} />
            {result.is_scam && (
              <span className="text-xs bg-red-950/60 border border-red-800 text-red-400 px-1.5 py-0.5 rounded flex items-center gap-1 font-semibold">
                <ShieldAlert size={11} /> SCAM
              </span>
            )}
            {added && (
              <span className="text-xs text-green-400 flex items-center gap-1 font-medium">
                <CheckCircle size={11} /> In watchlist
              </span>
            )}
          </div>

          <div className="flex gap-4 mt-1.5 text-xs text-gray-500 flex-wrap">
            <span>🔍 {result.messages_scanned} scanned</span>
            <span className="text-orange-400">⚠ {result.flagged_count} flagged</span>
            {result.high_count > 0 && <span className="text-red-400 font-medium">🔴 {result.high_count} HIGH</span>}
            {result.medium_count > 0 && (
              <span className="text-yellow-400 font-medium">🟡 {result.medium_count} MEDIUM</span>
            )}
            <span>
              Threat: <b className="text-white">{(result.avg_score * 100).toFixed(0)}%</b>
            </span>
            {result.member_count != null && (
              <span className="flex items-center gap-1">
                <Users size={12} className="text-gray-500" />
                {result.member_count.toLocaleString()}
              </span>
            )}
            <span className="text-blue-400">seed: {result.seed_term}</span>
          </div>

          {result.top_categories.length > 0 && (
            <div className="flex gap-1 mt-1.5 flex-wrap">
              {result.top_categories.slice(0, 5).map((c) => (
                <span
                  key={c}
                  className="text-[11px] bg-gray-800 border border-gray-700 text-gray-300 px-1.5 py-0.5 rounded"
                >
                  {c.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}
          {(result as any).risk_explanation && (
            <p className="text-[11px] text-gray-500 mt-1">{(result as any).risk_explanation}{(result as any).composite_score != null && (<span className="ml-2 text-blue-400 font-medium">Composite: {((result as any).composite_score * 100).toFixed(1)}%</span>)}</p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onInspect(result.channel_username);
            }}
            className="text-xs bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
            title="Inspect Channel & Network Graph"
          >
            <Share2 size={12} />
            Network
          </button>

          <button
            onClick={handleDownloadPdf}
            className="text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
            title="Download PDF Dossier for this channel"
          >
            <FileDown size={12} />
            PDF
          </button>

          {!added && result.risk_level !== "LOW" && (
            <button
              onClick={handleAdd}
              disabled={adding}
              className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg flex items-center gap-1 disabled:opacity-50 transition-colors font-medium"
            >
              <Plus size={12} />
              {adding ? "Adding..." : "Watch"}
            </button>
          )}

          {expanded ? (
            <ChevronUp size={16} className="text-gray-500" />
          ) : (
            <ChevronDown size={16} className="text-gray-500" />
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-800 pt-3 space-y-3">
          {/* Top identifiers */}
          {result.top_identifiers.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1.5 uppercase tracking-wide">
                Extracted Contact & Payment Identifiers
              </p>
              <div className="flex flex-wrap gap-1.5">
                {result.top_identifiers.map((id, i) => (
                  <span
                    key={i}
                    className="text-xs bg-gray-800 border border-gray-700 text-gray-300 px-2 py-0.5 rounded font-mono"
                  >
                    <span className="text-blue-400 mr-1">{id.type}:</span>
                    {id.value}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Sample messages */}
          {result.sample_messages.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1.5 uppercase tracking-wide">
                Sample Flagged Messages
              </p>
              <div className="space-y-2">
                {result.sample_messages.map((msg, i) => (
                  <div key={i} className="bg-gray-950 border border-gray-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <RiskBadge level={msg.risk_level} />
                      <span className="text-xs text-gray-500">
                        Score: {(msg.score * 100).toFixed(0)}%
                      </span>
                      {msg.date && (
                        <span className="text-xs text-gray-600">
                          {new Date(msg.date).toLocaleString()}
                        </span>
                      )}
                      <div className="flex gap-1 flex-wrap">
                        {msg.categories.slice(0, 3).map((c) => (
                          <span
                            key={c}
                            className="text-xs text-orange-300 bg-orange-900/20 border border-orange-700/20 px-1.5 py-0.5 rounded"
                          >
                            {c.replace(/_/g, " ")}
                          </span>
                        ))}
                      </div>
                    </div>
                    <p className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words">
                      {msg.text}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ScanPage() {
  const [jobs, setJobs] = useState<ScanJob[]>([]);
  const [activeJob, setActiveJob] = useState<ScanJob | null>(null);
  const [results, setResults] = useState<ChannelScanResult[]>([]);
  const [riskFilter, setRiskFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [customSeeds, setCustomSeeds] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanProfile, setScanProfile] = useState<"discovery" | "illegal_trade">("discovery");
  const [defaultSeeds, setDefaultSeeds] = useState<string[]>([]);
  const [seedCountsByCategory, setSeedCountsByCategory] = useState<Record<string, number>>({});
  const [showSeeds, setShowSeeds] = useState(false);
  const [scanMode, setScanMode] = useState<"review" | "auto">("review");
  const [inspectUsername, setInspectUsername] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadJobs = useCallback(async () => {
    const data = await fetchScanJobs(0, 20);
    setJobs(data);
    const latest = data[0];
    if (latest && latest.status === "done" && (!activeJob || activeJob.id !== latest.id)) {
      setActiveJob(latest);
    }
  }, [activeJob]);

  const loadResults = useCallback(
    async (jobId: number) => {
      const data = await fetchScanResults(jobId, {
        risk_level: riskFilter || undefined,
        category: categoryFilter || undefined,
        search: searchQuery.trim() || undefined,
      });
      setResults(data);
    },
    [riskFilter, categoryFilter, searchQuery]
  );

  const pollActiveJob = useCallback(async () => {
    if (!activeJob) return;
    if (activeJob.status === "running" || activeJob.status === "pending") {
      const updated = await fetchScanJob(activeJob.id);
      setActiveJob(updated);
      setJobs((prev) => prev.map((j) => (j.id === updated.id ? updated : j)));
      if (updated.status === "done" || updated.status === "failed" || updated.status === "interrupted") {
        if (pollRef.current) clearInterval(pollRef.current);
        setScanning(false);
        if (updated.status === "done") loadResults(updated.id);
      }
    }
  }, [activeJob, loadResults]);

  useEffect(() => {
    loadJobs();
  }, []);

  useEffect(() => {
    fetchDefaultSeeds(scanProfile).then((d) => {
      setDefaultSeeds(d.seeds);
      setSeedCountsByCategory(d.by_category || {});
    });
  }, [scanProfile]);

  useEffect(() => {
    if (activeJob?.status === "done") loadResults(activeJob.id);
  }, [activeJob?.id, riskFilter, categoryFilter, searchQuery, loadResults]);

  useEffect(() => {
    if (activeJob && (activeJob.status === "running" || activeJob.status === "pending")) {
      pollRef.current = setInterval(pollActiveJob, 3000);
      return () => {
        if (pollRef.current) clearInterval(pollRef.current);
      };
    }
  }, [activeJob?.id, activeJob?.status, pollActiveJob]);

  const handleRunScan = async () => {
    setScanning(true);
    setResults([]);
    try {
      const seeds = customSeeds.trim()
        ? customSeeds.split("\n").map((s) => s.trim()).filter(Boolean)
        : undefined;
      const { job_id } = await runScan(seeds, scanMode, scanProfile);
      const job = await fetchScanJob(job_id);
      setActiveJob(job);
      setJobs((prev) => [job, ...prev.filter((j) => j.id !== job_id)]);
    } catch (err) {
      console.error("Scan failed", err);
      alert("Scan failed: " + (err as any)?.message);
    } finally {
      setScanning(false);
    }
  };

  const handleSelectJob = async (job: ScanJob) => {
    setActiveJob(job);
    if (job.status === "done") loadResults(job.id);
  };

  const handleAdded = (resultId: number) => {
    setResults((prev) =>
      prev.map((r) => (r.id === resultId ? { ...r, already_monitored: true } : r))
    );
  };

  const handleExportFullScanPdf = () => {
    if (!activeJob) return;
    const url = getScanJobPdfUrl(activeJob.id);
    void downloadAuthenticatedPdf(url, `telemonitor_scan_${activeJob.id}_report.pdf`);
  };

  const isRunning = activeJob?.status === "running" || activeJob?.status === "pending";

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Detail Modal */}
      {inspectUsername && (
        <ChannelDetailModal
          usernameOrId={inspectUsername}
          onClose={() => setInspectUsername(null)}
          onWatchStatusChange={() => {
            if (activeJob?.status === "done") loadResults(activeJob.id);
          }}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <ScanSearch size={24} className="text-blue-400" />
          <div>
            <h1 className="text-xl font-bold text-white">Public Channel Scanner</h1>
            <p className="text-sm text-gray-500">
              Automated multi-crime reconnaissance on public Telegram networks.
            </p>
          </div>
        </div>

        {activeJob && activeJob.status === "done" && (
          <button
            onClick={handleExportFullScanPdf}
            className="bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 text-xs px-3.5 py-2 rounded-xl flex items-center gap-2 font-medium transition-colors"
          >
            <FileDown size={14} />
            Export Full Scan PDF Report
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Left: controls + job history */}
        <div className="lg:col-span-1 space-y-4">
          {/* Run scan card */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-sm font-semibold text-gray-300 mb-3">Launch Scan</p>

            <button
              onClick={() => setShowSeeds((s) => !s)}
              className="text-xs text-blue-400 hover:text-blue-300 mb-2 flex items-center gap-1"
            >
              {showSeeds ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {showSeeds ? "Hide custom seeds" : "Specify custom seeds"}
            </button>

            {showSeeds && (
              <textarea
                value={customSeeds}
                onChange={(e) => setCustomSeeds(e.target.value)}
                placeholder={"seed_term_1\nseed_term_2\n..."}
                rows={6}
                className="w-full bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded-lg px-3 py-2 mb-2 resize-none outline-none focus:border-blue-500 font-mono"
              />
            )}

            <div className="mb-3">
              <p className="text-xs text-gray-400 mb-1.5 font-medium">Seed profile</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setScanProfile("discovery")}
                  className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${
                    scanProfile === "discovery"
                      ? "bg-blue-600 border-blue-500 text-white font-semibold"
                      : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"
                  }`}
                >
                  Discovery recon
                </button>
                <button
                  onClick={() => setScanProfile("illegal_trade")}
                  className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${
                    scanProfile === "illegal_trade"
                      ? "bg-purple-600 border-purple-500 text-white font-semibold"
                      : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"
                  }`}
                >
                  Illegal-trade recon
                </button>
              </div>
            </div>

            {!showSeeds && (
              <p className="text-xs text-gray-500 mb-3 leading-relaxed">
                Profile <b className="text-gray-300">{scanProfile}</b> ·{" "}
                <b>{defaultSeeds.length} active seeds</b>{" "}
                {scanProfile === "discovery"
                  ? "using title-style channel & gateway queries."
                  : "across core crime-vocabulary categories."}
              </p>
            )}

            <div className="mb-3">
              <p className="text-xs text-gray-400 mb-1.5 font-medium">Scan mode</p>
              <div className="flex gap-2">
                <button onClick={() => setScanMode("review")} className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${scanMode === "review" ? "bg-blue-600 border-blue-500 text-white font-semibold" : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"}`}>Review Only</button>
                <button onClick={() => setScanMode("auto")} className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${scanMode === "auto" ? "bg-orange-600 border-orange-500 text-white font-semibold" : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600"}`}>Auto-Add</button>
              </div>
              <p className="text-[10px] text-gray-600 mt-1">{scanMode === "review" ? "Results listed for analyst review. No channels added automatically." : "HIGH-risk channels with 3+ HIGH messages auto-added to watchlist."}</p>
            </div>
            <button
              onClick={handleRunScan}
              disabled={scanning || isRunning}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium py-2.5 rounded-lg flex items-center justify-center gap-2 disabled:opacity-50 transition-colors shadow-lg shadow-blue-600/20"
            >
              {isRunning ? (
                <>
                  <RefreshCw size={15} className="animate-spin" /> Scanning Telegram...
                </>
              ) : (
                <>
                  <Play size={15} /> Run Scan
                </>
              )}
            </button>

            {defaultSeeds.length > 0 && (
              <details className="mt-3">
                <summary className="text-xs text-gray-600 cursor-pointer hover:text-gray-400">
                  View {defaultSeeds.length} default seeds
                </summary>
                <div className="mt-2 flex flex-wrap gap-1 max-h-36 overflow-y-auto">
                  {defaultSeeds.map((s) => (
                    <span
                      key={s}
                      className="text-[10px] bg-gray-800 text-gray-400 border border-gray-700 px-1.5 py-0.5 rounded"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </details>
            )}
          </div>

          {/* Job history */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2.5">
              Scan History
            </p>
            {jobs.length === 0 ? (
              <p className="text-xs text-gray-600">No scans executed yet.</p>
            ) : (
              <div className="space-y-1.5 max-h-80 overflow-y-auto">
                {jobs.map((job) => (
                  <button
                    key={job.id}
                    onClick={() => handleSelectJob(job)}
                    className={`w-full text-left rounded-lg px-3 py-2 transition-colors ${
                      activeJob?.id === job.id
                        ? "bg-blue-900/40 border border-blue-700/40"
                        : "bg-gray-800 hover:bg-gray-750 border border-gray-700/60"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs text-white font-mono font-bold">Job #{job.id}</span>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                          job.status === "done"
                            ? "text-green-400 bg-green-900/30"
                            : job.status === "running"
                            ? "text-blue-400 bg-blue-900/30 animate-pulse"
                            : job.status === "interrupted"
                            ? "text-amber-400 bg-amber-900/30"
                            : job.status === "failed"
                            ? "text-red-400 bg-red-900/30"
                            : "text-gray-400"
                        }`}
                      >
                        {job.status.toUpperCase()}
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-400 mt-0.5">
                      {job.total_channels_scanned} scanned · {job.total_flagged} flagged
                    </p>
                    <p className="text-[10px] text-gray-600 mt-0.5">
                      {formatDistanceToNow(new Date(job.created_at), { addSuffix: true })}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: active job status + results */}
        <div className="lg:col-span-3 space-y-4">
          {/* Active job progress card */}
          {activeJob && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <Clock size={16} className="text-blue-400" />
                  <span className="text-sm font-bold text-white">Scan Job #{activeJob.id}</span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded font-bold ${
                      activeJob.status === "done"
                        ? "text-green-400 bg-green-900/30"
                        : activeJob.status === "running"
                        ? "text-blue-400 bg-blue-900/30 animate-pulse"
                        : activeJob.status === "interrupted"
                        ? "text-amber-400 bg-amber-900/30"
                        : activeJob.status === "failed"
                        ? "text-red-400 bg-red-900/30"
                        : "text-gray-400 bg-gray-800"
                    }`}
                  >
                    {activeJob.status.toUpperCase()}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-500">
                    {activeJob.seed_terms.length} seed terms
                  </span>
                  {isRunning && (
                    <button
                      onClick={async () => {
                        const cancelled = await cancelScanJob(activeJob.id);
                        setActiveJob(cancelled);
                        setJobs((prev) => prev.map((j) => (j.id === cancelled.id ? cancelled : j)));
                      }}
                      className="text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 px-2.5 py-1 rounded-lg font-medium"
                    >
                      Stop Scan
                    </button>
                  )}
                  {activeJob.status === "done" && (
                    <button
                      onClick={handleExportFullScanPdf}
                      className="text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 px-2.5 py-1 rounded-lg flex items-center gap-1 font-medium"
                    >
                      <FileDown size={12} /> PDF Report
                    </button>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                {[
                  ["Found", activeJob.total_channels_found, "text-blue-400"],
                  ["Scanned", activeJob.total_channels_scanned, "text-white"],
                  ["Messages", activeJob.total_messages_scanned, "text-purple-400"],
                  ["Flagged", activeJob.total_flagged, "text-orange-400"],
                ].map(([label, val, cls]) => (
                  <div key={label as string} className="bg-gray-800/80 rounded-lg px-3 py-2 text-center">
                    <p className={`text-xl font-bold ${cls}`}>{val}</p>
                    <p className="text-xs text-gray-500">{label}</p>
                  </div>
                ))}
              </div>

              {isRunning && (
                <ProgressBar
                  value={activeJob.total_channels_scanned}
                  max={Math.max(activeJob.total_channels_found, 1)}
                />
              )}

              {activeJob.error && (
                <p className="text-xs text-red-400 mt-2 bg-red-900/20 px-3 py-2 rounded-lg">
                  Error: {activeJob.error}
                </p>
              )}
            </div>
          )}

          {/* Results Filters & Header */}
          {activeJob?.status === "done" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-bold text-white">Discovered Channels</h2>
                  <span className="text-xs text-gray-500">
                    ({results.length} channels loaded)
                  </span>
                </div>

                {/* Filter Controls */}
                <div className="flex items-center gap-2 flex-wrap">
                  {/* Search box */}
                  <div className="relative">
                    <Search size={13} className="absolute left-2.5 top-2 text-gray-500" />
                    <input
                      type="text"
                      placeholder="Search channel or seed..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="bg-gray-800 border border-gray-700 text-xs text-white rounded-lg pl-8 pr-3 py-1.5 outline-none focus:border-blue-500 w-44"
                    />
                  </div>

                  {/* Category Filter */}
                  <select
                    value={categoryFilter}
                    onChange={(e) => setCategoryFilter(e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded-lg px-2.5 py-1.5 outline-none"
                  >
                    <option value="">All Categories</option>
                    <option value="cybercrime">Cybercrime</option>
                    <option value="financial_fraud">Financial / Mules</option>
                    <option value="drug_sale">Narcotics</option>
                    <option value="arms">Weapons / Arms</option>
                    <option value="forged">Forged Documents</option>
                    <option value="counterfeit">Fake Currency</option>
                    <option value="gambling">Betting / Gambling</option>
                    <option value="extortion">Extortion / Blackmail</option>
                  </select>

                  {/* Risk filter */}
                  <select
                    value={riskFilter}
                    onChange={(e) => setRiskFilter(e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-xs text-gray-300 rounded-lg px-2.5 py-1.5 outline-none"
                  >
                    <option value="">All Risk Levels</option>
                    <option value="HIGH">HIGH only</option>
                    <option value="MEDIUM">MEDIUM only</option>
                    <option value="LOW">LOW only</option>
                  </select>
                </div>
              </div>

              {/* Results list */}
              {results.length === 0 ? (
                <div className="text-center py-16 text-gray-600 text-sm bg-gray-900 border border-gray-800 rounded-xl">
                  No channels matched the filter criteria.
                </div>
              ) : (
                <div>
                  {results.map((r) => (
                    <ResultRow
                      key={r.id}
                      result={r}
                      jobId={activeJob.id}
                      onAdded={handleAdded}
                      onInspect={(un) => setInspectUsername(un)}
                    />
                  ))}
                </div>
              )}

              {/* Scan Evidence sub-panel */}
              {activeJob.id && (
                <div className="mt-6">
                  <h3 className="text-lg font-semibold mb-3">Scan Evidence</h3>
                  <ScanEvidencePanel scanJobId={activeJob.id} />
                </div>
              )}
            </div>
          )}

          {!activeJob && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
              <div className="flex items-start gap-3">
                <ScanSearch size={28} className="text-blue-400 shrink-0 mt-0.5" />
                <div>
                  <h2 className="text-sm font-bold text-white">How Discovery Recon Works</h2>
                  <p className="text-xs text-gray-400 mt-1 leading-relaxed">
                    Public Telegram sellers rarely name channels with explicit crime keywords.{" "}
                    <b className="text-gray-200">Title-seed search</b> queries realistic channel titles and
                    adjacent gateway funnels (e.g. prediction games, job alerts, wholesale hubs),{" "}
                    <b className="text-gray-200">channel scan</b> pulls recent public posts,{" "}
                    <b className="text-gray-200">illegal-trade classification</b> scores every message against
                    the 6 PS02 crime categories and extracts phones/UPIs/handles/wallets, and{" "}
                    <b className="text-gray-200">network expansion</b> grows the syndicate graph offline from
                    shared identifiers and forwarded links.
                  </p>
                </div>
              </div>

              <div>
                <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                  Active Seed Catalogue ({scanProfile} · {defaultSeeds.length} seeds)
                </p>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {[
                    { key: "drugs", label: "Drugs & Narcotics", color: "border-emerald-500/30 text-emerald-300" },
                    { key: "arms", label: "Arms & Ammunition", color: "border-red-500/30 text-red-300" },
                    { key: "fake_documents", label: "Fake Documents", color: "border-amber-500/30 text-amber-300" },
                    { key: "mule_accounts", label: "Mule Accounts", color: "border-blue-500/30 text-blue-300" },
                    { key: "cards", label: "ATM / Carding", color: "border-purple-500/30 text-purple-300" },
                    { key: "sim_cards", label: "Pre-Activated SIMs", color: "border-cyan-500/30 text-cyan-300" },
                  ].map((cat) => (
                    <div
                      key={cat.key}
                      className={`bg-gray-950/70 border ${cat.color} rounded-lg p-3 flex items-center justify-between`}
                    >
                      <span className="text-xs font-medium text-gray-200">{cat.label}</span>
                      <span className="text-sm font-mono font-bold">
                        {seedCountsByCategory[cat.key] ?? 0}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
