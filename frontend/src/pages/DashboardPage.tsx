import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, Trash2, AlertTriangle, Activity, Flame, Eye } from "lucide-react";
import StatCard from "../components/StatCard";
import AlertCard from "../components/AlertCard";
import ChannelDetailModal from "../components/ChannelDetailModal";
import { groupAlerts } from "../utils/alertGrouping";
import { fetchAlertStats, fetchAlerts, reviewAlert, clearAllData } from "../api/client";
import type { Alert, AlertStats } from "../api/client";

export default function DashboardPage() {
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [recent, setRecent] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [inspectUsername, setInspectUsername] = useState<string | null>(null);

  // Clear-data modal state
  const [showClearModal, setShowClearModal] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearMsg, setClearMsg] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [s, a] = await Promise.all([
        fetchAlertStats(),
        fetchAlerts({ limit: 30 }),
      ]);
      setStats(s);
      setRecent(a);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Auto-refresh every 30 s
  useEffect(() => {
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, []);

  const handleReview = async (id: number) => {
    await reviewAlert(id);
    setRecent((prev) =>
      prev.map((a) => (a.id === id ? { ...a, is_reviewed: true } : a))
    );
  };

  const handleClear = async () => {
    setClearing(true);
    setClearMsg(null);
    try {
      const res = await clearAllData();
      setClearMsg(res.message);
      // Reload stats after clearing
      await load();
      setTimeout(() => setShowClearModal(false), 1500);
    } catch (err: any) {
      setClearMsg("Error: " + (err?.response?.data?.detail ?? err?.message ?? "Unknown error"));
    } finally {
      setClearing(false);
    }
  };

  const groups = groupAlerts(recent);
  const topCats = stats?.top_categories ?? [];

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Live summary of flagged activity across monitored channels
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => { setClearMsg(null); setShowClearModal(true); }}
            className="flex items-center gap-2 text-xs bg-red-900/40 hover:bg-red-900/70 border border-red-700/50 text-red-400 px-3 py-2 rounded-lg transition-colors"
          >
            <Trash2 size={14} />
            Clear Data
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
        <StatCard
          label="Total Alerts"
          value={stats?.total ?? "—"}
          color="text-blue-400"
          accent="border-l-2 border-l-blue-500"
          icon={<Activity size={14} className="text-blue-400" />}
        />
        <StatCard
          label="High Risk"
          value={stats?.HIGH ?? "—"}
          color="text-red-400"
          sub="Requires immediate attention"
          accent="border-l-2 border-l-red-500"
          icon={<Flame size={14} className="text-red-400" />}
        />
        <StatCard
          label="Medium Risk"
          value={stats?.MEDIUM ?? "—"}
          color="text-amber-400"
          sub="Review recommended"
          accent="border-l-2 border-l-amber-500"
          icon={<AlertTriangle size={14} className="text-amber-400" />}
        />
        <StatCard
          label="Unreviewed"
          value={stats?.unreviewed ?? "—"}
          color="text-purple-400"
          sub="Awaiting analyst review"
          accent="border-l-2 border-l-purple-500"
          icon={<Eye size={14} className="text-purple-400" />}
        />
      </div>

      {/* Top categories — compact chip strip */}
      {topCats.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-8">
          <span className="text-[10px] text-gray-500 uppercase tracking-widest mr-1">Top categories</span>
          {topCats.map(({ category, count }) => (
            <Link
              key={category}
              to="/alerts"
              className="text-xs bg-gray-800/70 border border-gray-700/70 text-gray-300 px-2 py-0.5 rounded-full hover:border-gray-500 hover:text-white transition-colors"
              title={`Open alerts filtered by ${category}`}
            >
              {category.replace(/_/g, " ")} <span className="text-gray-500 font-mono">{count}</span>
            </Link>
          ))}
        </div>
      )}

      {/* Channel detail modal */}
      {inspectUsername && (
        <ChannelDetailModal
          usernameOrId={inspectUsername}
          onClose={() => setInspectUsername(null)}
        />
      )}

      {/* Clear data confirmation modal */}
      {showClearModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="bg-gray-900 border border-red-700/50 rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="text-red-400 shrink-0" size={22} />
              <h2 className="text-white font-semibold text-base">Clear All Data?</h2>
            </div>
            <p className="text-gray-400 text-sm mb-2">
              This will permanently delete:
            </p>
            <ul className="text-gray-400 text-sm list-disc list-inside mb-4 space-y-1">
              <li>All scan jobs and results</li>
              <li>All alerts and messages</li>
              <li>All evidence, pivot candidates, and scores</li>
              <li>All disposition history</li>
            </ul>
            <p className="text-gray-500 text-xs mb-5">
              Your <span className="text-white">channel watchlist</span> and{" "}
              <span className="text-white">seed profiles</span> will be kept.
            </p>

            {clearMsg && (
              <p className={`text-xs mb-4 px-3 py-2 rounded-lg border ${
                clearMsg.startsWith("Error")
                  ? "text-red-400 bg-red-900/20 border-red-700/40"
                  : "text-green-400 bg-green-900/20 border-green-700/40"
              }`}>
                {clearMsg}
              </p>
            )}

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowClearModal(false)}
                disabled={clearing}
                className="text-sm px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleClear}
                disabled={clearing}
                className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-red-700 hover:bg-red-600 text-white font-medium transition-colors disabled:opacity-50"
              >
                {clearing ? (
                  <RefreshCw size={14} className="animate-spin" />
                ) : (
                  <Trash2 size={14} />
                )}
                {clearing ? "Clearing…" : "Yes, Clear Everything"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Recent alerts (duplicates across channels grouped into one card) */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-300">
          Recent Alerts
          {recent.length > groups.length && (
            <span className="text-gray-600 font-normal"> · {groups.length} unique of {recent.length}</span>
          )}
        </h2>
        <Link
          to="/alerts"
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          View all →
        </Link>
      </div>

      {loading && recent.length === 0 ? (
        <div className="text-center py-16 text-gray-600">Loading…</div>
      ) : groups.length === 0 ? (
        <div className="text-center py-16 text-gray-600">
          No alerts yet. Add channels and start monitoring.
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((g) => (
            <AlertCard
              key={g.representative.id}
              alert={g.representative}
              occurrences={g.occurrences}
              onReview={handleReview}
              onInspectChannel={(un) => setInspectUsername(un)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
