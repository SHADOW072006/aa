import { format } from "date-fns";

interface ScoreBreakdownPanelProps {
  score: {
    composite_score: number;
    max_message_score: number;
    high_confidence_message_count: number;
    distinct_incident_count: number;
    recency_weight: number;
    identifier_density: number;
    valid_pivot_count: number;
    analyst_confirmation_signal: number;
    scored_at?: string;
  } | null;
  loading?: boolean;
}

function compositeColor(pct: number): string {
  if (pct >= 70) return "text-red-400";
  if (pct >= 40) return "text-yellow-400";
  return "text-green-400";
}

function compositeBg(pct: number): string {
  if (pct >= 70) return "bg-red-500/10 border-red-500/30";
  if (pct >= 40) return "bg-yellow-500/10 border-yellow-500/30";
  return "bg-green-500/10 border-green-500/30";
}

function compositeLabel(pct: number): string {
  if (pct >= 70) return "High Risk";
  if (pct >= 40) return "Medium Risk";
  return "Low Risk";
}

function compositeBadgeStyle(pct: number): string {
  if (pct >= 70) return "bg-red-500/20 text-red-400 border border-red-500/30";
  if (pct >= 40) return "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30";
  return "bg-green-500/20 text-green-400 border border-green-500/30";
}

interface BreakdownRow {
  label: string;
  value: React.ReactNode;
}

export default function ScoreBreakdownPanel({ score, loading }: ScoreBreakdownPanelProps) {
  if (loading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 animate-pulse">
        <div className="h-4 bg-gray-800 rounded w-1/3 mb-4" />
        <div className="h-10 bg-gray-800 rounded w-1/2 mb-6" />
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="flex justify-between py-2 border-b border-gray-800">
            <div className="h-3 bg-gray-800 rounded w-1/3" />
            <div className="h-3 bg-gray-800 rounded w-1/6" />
          </div>
        ))}
      </div>
    );
  }

  if (score === null) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-center justify-center min-h-[120px]">
        <p className="text-sm text-gray-500">No score data available</p>
      </div>
    );
  }

  const pct = Math.round(score.composite_score * 100 * 10) / 10;

  const rows: BreakdownRow[] = [
    {
      label: "Max Message Score",
      value: (
        <span className="font-mono">{score.max_message_score.toFixed(2)}</span>
      ),
    },
    {
      label: "High Confidence Messages",
      value: (
        <span className="font-mono">{Math.round(score.high_confidence_message_count)}</span>
      ),
    },
    {
      label: "Distinct Incident Tiers",
      value: (
        <span className="font-mono">{Math.round(score.distinct_incident_count)}</span>
      ),
    },
    {
      label: "Recency Weight",
      value: (
        <span className="font-mono">{score.recency_weight.toFixed(2)}</span>
      ),
    },
    {
      label: "Identifier Density",
      value: (
        <span className="font-mono">{score.identifier_density.toFixed(2)}</span>
      ),
    },
    {
      label: "Valid Pivots",
      value: (
        <span className="font-mono">{Math.round(score.valid_pivot_count)}</span>
      ),
    },
    {
      label: "Analyst Signal",
      value: (
        <span className="font-mono">{score.analyst_confirmation_signal.toFixed(2)}</span>
      ),
    },
  ];

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      {/* Header */}
      <p className="text-xs text-gray-500 uppercase tracking-widest mb-3">
        Threat Score Breakdown
      </p>

      {/* Composite score */}
      <div className={`rounded-lg border p-4 mb-5 flex items-center justify-between ${compositeBg(pct)}`}>
        <div>
          <p className="text-xs text-gray-400 mb-0.5">Composite Score</p>
          <p className={`text-4xl font-bold font-mono ${compositeColor(pct)}`}>
            {pct.toFixed(1)}%
          </p>
        </div>
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${compositeBadgeStyle(pct)}`}>
          {compositeLabel(pct)}
        </span>
      </div>

      {/* Breakdown rows */}
      <div className="divide-y divide-gray-800">
        {rows.map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between py-2.5">
            <span className="text-xs text-gray-400">{label}</span>
            <span className="text-sm text-gray-200">{value}</span>
          </div>
        ))}
      </div>

      {/* Scored at timestamp */}
      {score.scored_at && (
        <p className="text-xs text-gray-600 mt-4">
          Scored{" "}
          {format(new Date(score.scored_at), "d MMM yyyy, HH:mm")}
        </p>
      )}
    </div>
  );
}
