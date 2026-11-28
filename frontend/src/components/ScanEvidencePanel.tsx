import { useState, useEffect, useCallback } from "react";
import { formatDistanceToNow } from "date-fns";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { fetchEvidence } from "../api/evidence";
import type { ScanEvidence } from "../api/evidence";
import { provenanceBadgeClass, provenanceNote } from "../utils/provenance";
import DispositionControls from "./DispositionControls";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ScanEvidencePanelProps {
  scanJobId?: number;
  channelUsername?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(score: number): string {
  if (score >= 0.8) return "text-red-400";
  if (score >= 0.5) return "text-yellow-400";
  return "text-green-400";
}

function scoreBg(score: number): string {
  if (score >= 0.8) return "bg-red-500/20 text-red-400 border border-red-500/30";
  if (score >= 0.5) return "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30";
  return "bg-green-500/20 text-green-400 border border-green-500/30";
}

const RISK_BADGE: Record<string, string> = {
  HIGH: "bg-red-500/20 text-red-400 border border-red-500/30",
  MEDIUM: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  LOW: "bg-green-500/20 text-green-400 border border-green-500/30",
};

const TIER_BADGE: Record<string, string> = {
  CRITICAL: "bg-red-700/30 text-red-300 border border-red-600/40",
  HIGH: "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  MEDIUM: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  LOW: "bg-blue-500/20 text-blue-400 border border-blue-500/30",
};

const DISPOSITION_BADGE: Record<string, string> = {
  confirmed_threat: "bg-red-500/20 text-red-400 border border-red-500/30",
  false_positive: "bg-green-500/20 text-green-400 border border-green-500/30",
  needs_review: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  escalated: "bg-purple-500/20 text-purple-400 border border-purple-500/30",
};

function dispositionLabel(value: string): string {
  return value.replace(/_/g, " ");
}

// ── Evidence Row ──────────────────────────────────────────────────────────────

interface EvidenceRowProps {
  item: ScanEvidence;
  onDispositionSet: (id: number, newDisposition: string) => void;
}

function EvidenceRow({ item, onDispositionSet }: EvidenceRowProps) {
  const [expanded, setExpanded] = useState(false);

  const displayText = item.normalised_text ?? item.raw_text ?? "";
  const timestamp = item.message_timestamp
    ? formatDistanceToNow(new Date(item.message_timestamp), { addSuffix: true })
    : "—";

  return (
    <div className="border border-gray-800 rounded-xl overflow-hidden">
      {/* Summary row */}
      <button
        className="w-full flex items-center gap-3 px-4 py-3 bg-gray-900 hover:bg-gray-800/70 transition-colors text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="shrink-0 text-gray-500">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>

        {/* Channel */}
        <span className="font-mono text-xs text-blue-400 w-32 shrink-0 truncate">
          @{item.channel_username}
        </span>

        {/* Message ID */}
        <span className="font-mono text-xs text-gray-500 w-20 shrink-0">
          #{item.telegram_message_id}
        </span>

        {/* Score */}
        <span
          className={`text-xs font-mono font-bold w-14 shrink-0 ${scoreColor(item.classifier_score)}`}
        >
          {item.classifier_score.toFixed(2)}
        </span>

        {/* Risk level */}
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full w-20 shrink-0 text-center ${
            RISK_BADGE[item.risk_level] ?? "bg-gray-700 text-gray-300 border border-gray-600"
          }`}
        >
          {item.risk_level}
        </span>

        {/* Severity tier */}
        <span
          className={`text-xs font-semibold px-2 py-0.5 rounded-full w-20 shrink-0 text-center ${
            TIER_BADGE[item.severity_tier] ?? "bg-gray-700 text-gray-300 border border-gray-600"
          }`}
        >
          {item.severity_tier}
        </span>

        {/* Seed term */}
        <span className="text-xs text-gray-400 flex-1 truncate font-mono">
          {item.seed_term ?? "—"}
        </span>

        {/* Disposition */}
        {item.disposition ? (
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${
              DISPOSITION_BADGE[item.disposition] ??
              "bg-gray-700 text-gray-300 border border-gray-600"
            }`}
          >
            {dispositionLabel(item.disposition)}
          </span>
        ) : (
          <span className="text-xs text-gray-600 shrink-0 w-20 text-center">—</span>
        )}

        {/* Timestamp */}
        <span className="text-xs text-gray-600 shrink-0 w-28 text-right">{timestamp}</span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="bg-gray-950 border-t border-gray-800 p-4 space-y-4">
          {/* Message text */}
          {displayText ? (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">
                {item.normalised_text ? "Normalised text" : "Raw text"}
              </p>
              <pre className="text-xs font-mono text-gray-200 bg-black/40 border border-gray-800 rounded-lg p-3 whitespace-pre-wrap break-words leading-relaxed">
                {displayText}
              </pre>
            </div>
          ) : (
            <p className="text-xs text-gray-600 italic">No text available.</p>
          )}

          {/* Score detail */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-gray-500 uppercase tracking-widest">Score</span>
            <span
              className={`text-sm font-bold font-mono px-2 py-0.5 rounded-full ${scoreBg(
                item.classifier_score
              )}`}
            >
              {item.classifier_score.toFixed(2)}
            </span>
            {item.provenance_status && (
              <span
                className={`text-[11px] font-mono px-2 py-0.5 rounded border ${provenanceBadgeClass(
                  item.provenance_status
                )}`}
              >
                {item.provenance_status}
              </span>
            )}
          </div>

          {provenanceNote(item.provenance_status, item.provenance_note) && (
            <p className="text-xs text-amber-300 bg-amber-950/30 border border-amber-800/40 rounded px-2 py-1">
              {provenanceNote(item.provenance_status, item.provenance_note)}
            </p>
          )}

          {/* Categories */}
          {item.categories && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Categories</p>
              <div className="flex flex-wrap gap-1">
                {item.categories.split(",").map((cat) => (
                  <span
                    key={cat}
                    className="text-xs bg-gray-800 text-gray-300 border border-gray-700 px-2 py-0.5 rounded-full"
                  >
                    {cat.trim().replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Matched terms */}
          {item.matched_terms && (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Matched terms</p>
              <div className="flex flex-wrap gap-1">
                {item.matched_terms.split(",").map((term) => (
                  <span
                    key={term}
                    className="text-xs bg-gray-900 border border-gray-700 text-orange-300 px-2 py-0.5 rounded font-mono"
                  >
                    {term.trim()}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Disposition controls */}
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">Disposition</p>
            <DispositionControls
              targetType="evidence"
              targetId={item.id}
              currentDisposition={item.disposition}
              onDispositionSet={(newDisposition) => onDispositionSet(item.id, newDisposition)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ScanEvidencePanel({
  scanJobId,
  channelUsername,
}: ScanEvidencePanelProps) {
  const [evidence, setEvidence] = useState<ScanEvidence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEvidence({
        scan_job_id: scanJobId,
        channel_username: channelUsername,
        limit: 50,
      });
      setEvidence(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load evidence.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [scanJobId, channelUsername]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDispositionSet = useCallback((id: number, newDisposition: string) => {
    setEvidence((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, disposition: newDisposition } : item
      )
    );
    // Refresh the full list to pick up server-side changes
    load();
  }, [load]);

  // ── Table header labels ───────────────────────────────────────────────────

  const HEADERS = [
    { label: "", width: "w-5" },
    { label: "Channel", width: "w-32" },
    { label: "Msg ID", width: "w-20" },
    { label: "Score", width: "w-14" },
    { label: "Risk", width: "w-20" },
    { label: "Tier", width: "w-20" },
    { label: "Seed term", width: "flex-1" },
    { label: "Disposition", width: "w-20" },
    { label: "Time", width: "w-28" },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      {/* Panel header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-widest">
          Scan Evidence
          {channelUsername && (
            <span className="text-blue-400 font-mono normal-case ml-2">
              @{channelUsername}
            </span>
          )}
        </h3>
        <button
          onClick={load}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40"
          title="Refresh"
        >
          Refresh
        </button>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex items-center gap-2 text-gray-500 text-sm py-6 justify-center">
          <Loader2 size={16} className="animate-spin" />
          <span>Loading evidence…</span>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="text-xs text-red-400 bg-red-900/20 border border-red-700/40 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && evidence.length === 0 && (
        <div className="text-sm text-gray-600 text-center py-8">
          No evidence found.
        </div>
      )}

      {/* Column headers */}
      {!loading && evidence.length > 0 && (
        <>
          <div className="flex items-center gap-3 px-4 pb-1 border-b border-gray-800">
            {HEADERS.map((h) => (
              <span
                key={h.label}
                className={`text-xs text-gray-600 uppercase tracking-widest ${h.width}`}
              >
                {h.label}
              </span>
            ))}
          </div>

          {/* Evidence rows */}
          <div className="space-y-2">
            {evidence.map((item) => (
              <EvidenceRow
                key={item.id}
                item={item}
                onDispositionSet={handleDispositionSet}
              />
            ))}
          </div>

          <p className="text-xs text-gray-700 text-right">
            {evidence.length} item{evidence.length !== 1 ? "s" : ""}
          </p>
        </>
      )}
    </div>
  );
}
