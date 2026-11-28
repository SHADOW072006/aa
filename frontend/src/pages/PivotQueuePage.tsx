import { useEffect, useState, useCallback } from "react";
import { CheckCircle, XCircle, GitMerge } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import {
  fetchPendingPivots,
  approvePivot,
  rejectPivot,
} from "../api/pivots";
import type { PivotCandidate } from "../api/pivots";

// ── Inline action form shown per row ──────────────────────────────────────────

interface ActionFormProps {
  mode: "approve" | "reject";
  onSubmit: (evaluated_by: string, notes: string) => Promise<void>;
  onCancel: () => void;
}

function ActionForm({ mode, onSubmit, onCancel }: ActionFormProps) {
  const [evaluatedBy, setEvaluatedBy] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!evaluatedBy.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(evaluatedBy.trim(), notes.trim());
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-2 bg-gray-800 border border-gray-700 rounded-xl p-3 flex flex-col gap-2"
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
        {mode === "approve" ? "Approve pivot" : "Reject pivot"}
      </p>
      <input
        type="text"
        required
        value={evaluatedBy}
        onChange={(e) => setEvaluatedBy(e.target.value)}
        placeholder="Your name / analyst ID *"
        className="bg-gray-900 border border-gray-700 text-sm text-white rounded-lg px-3 py-1.5 outline-none focus:border-blue-500 transition-colors"
      />
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes (optional)"
        rows={2}
        className="bg-gray-900 border border-gray-700 text-sm text-white rounded-lg px-3 py-1.5 outline-none focus:border-blue-500 transition-colors resize-none"
      />
      <div className="flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-gray-400 hover:text-gray-200 px-3 py-1.5 rounded-lg border border-gray-700 hover:bg-gray-700 transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={submitting || !evaluatedBy.trim()}
          className={`text-xs font-semibold px-4 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors disabled:opacity-50 ${
            mode === "approve"
              ? "bg-green-600 hover:bg-green-700 text-white"
              : "bg-red-600 hover:bg-red-700 text-white"
          }`}
        >
          {submitting
            ? "Saving…"
            : mode === "approve"
            ? "Confirm Approve"
            : "Confirm Reject"}
        </button>
      </div>
    </form>
  );
}

// ── Badge for candidate_type ──────────────────────────────────────────────────

const TYPE_COLOURS: Record<string, string> = {
  username:
    "bg-blue-500/10 border-blue-500/20 text-blue-400",
  phone:
    "bg-yellow-500/10 border-yellow-500/20 text-yellow-400",
  wallet:
    "bg-purple-500/10 border-purple-500/20 text-purple-400",
  url: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
  email:
    "bg-green-500/10 border-green-500/20 text-green-400",
};

function TypeBadge({ type }: { type: string }) {
  const cls =
    TYPE_COLOURS[type.toLowerCase()] ??
    "bg-gray-700 border-gray-600 text-gray-300";
  return (
    <span
      className={`inline-block text-[10px] font-medium border px-2 py-0.5 rounded-full uppercase tracking-wide ${cls}`}
    >
      {type}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "approved")
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-green-400">
        <CheckCircle size={11} /> Approved
      </span>
    );
  if (status === "rejected")
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-red-400">
        <XCircle size={11} /> Rejected
      </span>
    );
  return (
    <span className="inline-block text-[10px] font-medium text-gray-400 uppercase tracking-wide">
      {status}
    </span>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

type ActiveAction = { id: number; mode: "approve" | "reject" };

export default function PivotQueuePage() {
  const [pivots, setPivots] = useState<PivotCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<ActiveAction | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPendingPivots();
      setPivots(data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to load pivot candidates";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleAction = async (
    id: number,
    mode: "approve" | "reject",
    evaluated_by: string,
    notes: string
  ) => {
    const action = { evaluated_by, notes: notes || undefined };
    if (mode === "approve") {
      await approvePivot(id, action);
    } else {
      await rejectPivot(id, action);
    }
    setActiveAction(null);
    await load();
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-1 flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <GitMerge size={22} className="text-indigo-400" /> Pivot Queue
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Review and action pivot candidates discovered during channel scans
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mt-4 bg-red-950/40 border border-red-800 text-red-300 text-xs px-3.5 py-2.5 rounded-xl">
          {error}
        </div>
      )}

      {/* Loading skeleton */}
      {loading && pivots.length === 0 && (
        <div className="mt-8 text-center text-sm text-gray-500">Loading pivot candidates…</div>
      )}

      {/* Empty state */}
      {!loading && !error && pivots.length === 0 && (
        <div className="mt-10 text-center py-16 bg-gray-900 border border-gray-800 rounded-xl text-gray-500 text-sm">
          No pending pivots
        </div>
      )}

      {/* Table */}
      {pivots.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-xl border border-gray-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 bg-gray-900/60">
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Source Channel
                </th>
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Type
                </th>
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Candidate Value
                </th>
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Status
                </th>
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Created
                </th>
                <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {pivots.map((pivot) => {
                const isActive = activeAction?.id === pivot.id;
                return (
                  <tr
                    key={pivot.id}
                    className="border-b border-gray-800/50 bg-gray-900 hover:bg-gray-850 transition-colors last:border-b-0"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-gray-300 whitespace-nowrap">
                      @{pivot.source_channel_username}
                    </td>
                    <td className="px-4 py-3">
                      <TypeBadge type={pivot.candidate_type} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-white max-w-xs truncate">
                      {pivot.candidate_value}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <StatusBadge status={pivot.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                      {formatDistanceToNow(new Date(pivot.created_at), {
                        addSuffix: true,
                      })}
                    </td>
                    <td className="px-4 py-3">
                      {pivot.status === "pending" ? (
                        <div>
                          {!isActive && (
                            <div className="flex gap-2">
                              <button
                                onClick={() =>
                                  setActiveAction({ id: pivot.id, mode: "approve" })
                                }
                                className="text-xs bg-green-600/20 hover:bg-green-600/30 border border-green-500/30 text-green-400 px-3 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
                              >
                                <CheckCircle size={12} /> Approve
                              </button>
                              <button
                                onClick={() =>
                                  setActiveAction({ id: pivot.id, mode: "reject" })
                                }
                                className="text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-400 px-3 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
                              >
                                <XCircle size={12} /> Reject
                              </button>
                            </div>
                          )}
                          {isActive && activeAction && (
                            <ActionForm
                              mode={activeAction.mode}
                              onSubmit={(evaluated_by, notes) =>
                                handleAction(
                                  pivot.id,
                                  activeAction.mode,
                                  evaluated_by,
                                  notes
                                )
                              }
                              onCancel={() => setActiveAction(null)}
                            />
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-gray-600 italic">
                          {pivot.evaluated_by ? `by ${pivot.evaluated_by}` : "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
