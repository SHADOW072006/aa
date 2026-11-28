import { useState, useCallback } from "react";
import { setAlertDisposition } from "../api/client";
import { setEvidenceDisposition } from "../api/evidence";

// ── Types ──────────────────────────────────────────────────────────────────────

interface DispositionControlsProps {
  targetType: "alert" | "evidence";
  targetId: number;
  currentDisposition: string | null;
  onDispositionSet: (newDisposition: string) => void;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const DISPOSITION_OPTIONS = [
  { value: "confirmed_threat", label: "Confirmed Threat" },
  { value: "false_positive", label: "False Positive" },
  { value: "needs_review", label: "Needs Review" },
  { value: "escalated", label: "Escalated" },
] as const;

const DISPOSITION_BADGE: Record<string, string> = {
  confirmed_threat:
    "bg-red-500/20 text-red-400 border border-red-500/30",
  false_positive:
    "bg-green-500/20 text-green-400 border border-green-500/30",
  needs_review:
    "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  escalated:
    "bg-purple-500/20 text-purple-400 border border-purple-500/30",
};

function dispositionLabel(value: string): string {
  return (
    DISPOSITION_OPTIONS.find((o) => o.value === value)?.label ??
    value.replace(/_/g, " ")
  );
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function DispositionControls({
  targetType,
  targetId,
  currentDisposition,
  onDispositionSet,
}: DispositionControlsProps) {
  const [selected, setSelected] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [changedBy, setChangedBy] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    if (!selected) return;

    setLoading(true);
    setError(null);

    try {
      const payload = {
        disposition: selected,
        notes: notes.trim() || undefined,
        changed_by: changedBy.trim() || "analyst",
      };

      if (targetType === "alert") {
        await setAlertDisposition(targetId, payload);
      } else {
        await setEvidenceDisposition(targetId, payload);
      }

      onDispositionSet(selected);
      setSelected("");
      setNotes("");
      setChangedBy("");
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to save disposition.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [selected, notes, changedBy, targetType, targetId, onDispositionSet]);

  return (
    <div className="rounded-xl bg-gray-900 border border-gray-700 p-4 space-y-4">
      {/* Current disposition badge */}
      {currentDisposition && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">Current disposition:</span>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
              DISPOSITION_BADGE[currentDisposition] ??
              "bg-gray-700 text-gray-300 border border-gray-600"
            }`}
          >
            {dispositionLabel(currentDisposition)}
          </span>
        </div>
      )}

      {/* Disposition select */}
      <div className="space-y-1">
        <label className="block text-xs text-gray-400 font-medium">
          Disposition
        </label>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          disabled={loading}
          className="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <option value="">— select disposition —</option>
          {DISPOSITION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Notes textarea */}
      <div className="space-y-1">
        <label className="block text-xs text-gray-400 font-medium">
          Notes <span className="text-gray-600">(optional)</span>
        </label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={loading}
          rows={3}
          placeholder="Add context or reasoning…"
          className="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed placeholder-gray-600"
        />
      </div>

      {/* Changed by input */}
      <div className="space-y-1">
        <label className="block text-xs text-gray-400 font-medium">
          Changed by
        </label>
        <input
          type="text"
          value={changedBy}
          onChange={(e) => setChangedBy(e.target.value)}
          disabled={loading}
          placeholder="Analyst name"
          className="w-full bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed placeholder-gray-600"
        />
      </div>

      {/* Error message */}
      {error && (
        <p className="text-xs text-red-400 bg-red-900/20 border border-red-700/40 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={loading || !selected}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors disabled:cursor-not-allowed flex items-center justify-center gap-2"
      >
        {loading ? (
          <>
            <svg
              className="animate-spin h-4 w-4 text-white"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            Saving…
          </>
        ) : (
          "Save"
        )}
      </button>
    </div>
  );
}
