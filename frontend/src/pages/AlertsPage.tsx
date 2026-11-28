import { useEffect, useState, useCallback, useMemo } from "react";
import AlertCard from "../components/AlertCard";
import ChannelDetailModal from "../components/ChannelDetailModal";
import { groupAlerts } from "../utils/alertGrouping";
import { fetchAlerts, reviewAlert } from "../api/client";
import type { Alert } from "../api/client";

const PAGE_SIZE = 25;

const DISPOSITION_OPTIONS = [
  { value: "", label: "All dispositions" },
  { value: "confirmed_threat", label: "Confirmed Threat" },
  { value: "false_positive", label: "False Positive" },
  { value: "needs_review", label: "Needs Review" },
  { value: "escalated", label: "Escalated" },
  { value: "unreviewed", label: "Unreviewed (none)" },
];

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(false);
  const [skip, setSkip] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [riskFilter, setRiskFilter] = useState<string>("");
  const [reviewedFilter, setReviewedFilter] = useState<string>("");
  const [lifecycleFilter, setLifecycleFilter] = useState<string>("active");
  const [dispositionFilter, setDispositionFilter] = useState<string>("");
  const [groupDuplicates, setGroupDuplicates] = useState<boolean>(true);
  const [inspectUsername, setInspectUsername] = useState<string | null>(null);

  const load = useCallback(
    async (reset = false) => {
      setLoading(true);
      const offset = reset ? 0 : skip;
      try {
        const data = await fetchAlerts({
          risk_level: riskFilter || undefined,
          reviewed: reviewedFilter === "" ? undefined : reviewedFilter === "true",
          lifecycle_state: lifecycleFilter === "all" ? undefined : lifecycleFilter,
          include_historical: lifecycleFilter === "all" ? true : undefined,
          skip: offset,
          limit: PAGE_SIZE,
        });
        if (reset) {
          setAlerts(data);
          setSkip(PAGE_SIZE);
        } else {
          setAlerts((prev) => [...prev, ...data]);
          setSkip((s) => s + PAGE_SIZE);
        }
        setHasMore(data.length === PAGE_SIZE);
      } finally {
        setLoading(false);
      }
    },
    [riskFilter, reviewedFilter, lifecycleFilter, skip]
  );

  useEffect(() => {
    setSkip(0);
    setHasMore(true);
    load(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskFilter, reviewedFilter, lifecycleFilter]);

  const handleReview = async (id: number) => {
    await reviewAlert(id);
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, is_reviewed: true } : a))
    );
  };

  const handleDispositionSet = (id: number, newDisposition: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, disposition: newDisposition } : a))
    );
  };

  // In-memory disposition filter
  const displayedAlerts = dispositionFilter
    ? alerts.filter((a) => {
        if (dispositionFilter === "unreviewed") return a.disposition == null;
        return a.disposition === dispositionFilter;
      })
    : alerts;

  const groups = useMemo(
    () => (groupDuplicates ? groupAlerts(displayedAlerts) : null),
    [displayedAlerts, groupDuplicates]
  );

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {inspectUsername && (
        <ChannelDetailModal
          usernameOrId={inspectUsername}
          onClose={() => setInspectUsername(null)}
        />
      )}

      <h1 className="text-xl font-bold text-white mb-1">All Alerts</h1>
      <p className="text-sm text-gray-500 mb-5">
        Every flagged post, with evidence and extracted identifiers
      </p>

      {/* Filters */}
      <div className="flex gap-3 mb-5 flex-wrap">
        <select
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-1.5"
        >
          <option value="">All risk levels</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
        </select>
        <select
          value={reviewedFilter}
          onChange={(e) => setReviewedFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-1.5"
        >
          <option value="">All</option>
          <option value="false">Unreviewed</option>
          <option value="true">Reviewed</option>
        </select>
        <select
          value={lifecycleFilter}
          onChange={(e) => setLifecycleFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-1.5"
        >
          <option value="active">Active Alerts</option>
          <option value="resolved_by_reclassification">Resolved by Reclassification</option>
          <option value="suppressed">Suppressed</option>
          <option value="all">All (incl. Historical)</option>
        </select>
        <select
          value={dispositionFilter}
          onChange={(e) => setDispositionFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-1.5"
        >
          {DISPOSITION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-xs text-gray-400 bg-gray-800/60 border border-gray-700 rounded-lg px-3 py-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={groupDuplicates}
            onChange={(e) => setGroupDuplicates(e.target.checked)}
            className="accent-blue-500"
          />
          Group duplicates
        </label>
      </div>

      {/* Alert list */}
      <div className="space-y-3">
        {groups
          ? groups.map((g) => (
              <AlertCard
                key={g.representative.id}
                alert={g.representative}
                occurrences={g.occurrences}
                onReview={handleReview}
                onInspectChannel={(un) => setInspectUsername(un)}
                onDispositionSet={handleDispositionSet}
              />
            ))
          : displayedAlerts.map((a) => (
              <AlertCard
                key={a.id}
                alert={a}
                onReview={handleReview}
                onInspectChannel={(un) => setInspectUsername(un)}
                onDispositionSet={handleDispositionSet}
              />
            ))}
      </div>

      {/* Load more */}
      {hasMore && (
        <div className="mt-6 text-center">
          <button
            onClick={() => load(false)}
            disabled={loading}
            className="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-sm text-gray-300 px-6 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        </div>
      )}

      {!loading && displayedAlerts.length === 0 && (
        <div className="text-center py-16 text-gray-600">No alerts match your filters.</div>
      )}
    </div>
  );
}
