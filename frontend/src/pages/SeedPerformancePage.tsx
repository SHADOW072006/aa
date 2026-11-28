import { useEffect, useState, useCallback } from "react";
import {
  Plus,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Sprout,
  Trash2,
  X,
  BarChart2,
  AlertTriangle,
} from "lucide-react";
import {
  fetchSeeds,
  createSeed,
  deactivateSeed,
  getSeedPerformance,
} from "../api/seeds";
import type { SeedProfile, SeedCreate, SeedPerformance } from "../api/seeds";

// ── Constants ────────────────────────────────────────────────────────────────

const CREATED_SOURCES = ["manual", "analyst_promoted", "entity_pivot"] as const;

const PRIORITY_LABELS: Record<number, string> = {
  1: "P1 – Critical",
  2: "P2 – High",
  3: "P3 – Medium",
  4: "P4 – Low",
  5: "P5 – Minimal",
};

const PRIORITY_COLORS: Record<number, string> = {
  1: "text-red-400 bg-red-500/10 border-red-500/30",
  2: "text-orange-400 bg-orange-500/10 border-orange-500/30",
  3: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  4: "text-blue-400 bg-blue-500/10 border-blue-500/30",
  5: "text-gray-400 bg-gray-700/40 border-gray-600",
};

// ── Sub-components ──────────────────────────────────────────────────────────

function PerformancePanel({ seedId }: { seedId: number }) {
  const [perf, setPerf] = useState<SeedPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getSeedPerformance(seedId)
      .then(setPerf)
      .catch(() => setError("Failed to load performance data."))
      .finally(() => setLoading(false));
  }, [seedId]);

  if (loading) {
    return (
      <div className="px-4 pb-4 border-t border-gray-800 pt-3 text-xs text-gray-500 animate-pulse">
        Loading performance data…
      </div>
    );
  }

  if (error || !perf) {
    return (
      <div className="px-4 pb-4 border-t border-gray-800 pt-3 text-xs text-red-400 flex items-center gap-1.5">
        <AlertTriangle size={12} /> {error ?? "No data available."}
      </div>
    );
  }

  return (
    <div className="px-4 pb-4 border-t border-gray-800 pt-3 space-y-4">
      {/* Stat row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          ["Variants", perf.total_variants, "text-purple-400"],
          ["Executions", perf.total_executions, "text-blue-400"],
          ["Channels Found", perf.total_channels_found, "text-green-400"],
          ["Channels Added", perf.total_channels_added, "text-yellow-400"],
        ].map(([label, val, cls]) => (
          <div key={label as string} className="bg-gray-800/80 rounded-lg px-3 py-2 text-center">
            <p className={`text-xl font-bold ${cls}`}>{val}</p>
            <p className="text-xs text-gray-500">{label}</p>
          </div>
        ))}
      </div>

      {/* Variants table */}
      {perf.variants.length > 0 ? (
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Variant Executions</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="pb-2 pr-4 text-gray-500 font-medium">Variant Text</th>
                  <th className="pb-2 pr-4 text-gray-500 font-medium">Type</th>
                  <th className="pb-2 text-gray-500 font-medium text-right">Executions</th>
                </tr>
              </thead>
              <tbody>
                {perf.variants.map((v, i) => (
                  <tr key={i} className="border-b border-gray-800/60 hover:bg-gray-800/30">
                    <td className="py-1.5 pr-4 font-mono text-gray-200 max-w-xs truncate">
                      {v.variant_text}
                    </td>
                    <td className="py-1.5 pr-4">
                      <span className="text-blue-400 bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 rounded text-[11px]">
                        {v.variant_type}
                      </span>
                    </td>
                    <td className="py-1.5 text-right text-white font-medium">{v.executions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="text-xs text-gray-600 italic">No variants recorded yet.</p>
      )}
    </div>
  );
}

function SeedRow({
  seed,
  onDeactivate,
}: {
  seed: SeedProfile;
  onDeactivate: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deactivating, setDeactivating] = useState(false);

  const handleDeactivate = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setDeactivating(true);
    try {
      await deactivateSeed(seed.id);
      onDeactivate(seed.id);
    } finally {
      setDeactivating(false);
      setConfirming(false);
    }
  };

  const priorityColor = PRIORITY_COLORS[seed.priority] ?? PRIORITY_COLORS[3];

  return (
    <div className="bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl transition-all">
      {/* Summary row */}
      <div
        className="flex items-start gap-3 px-4 py-3 cursor-pointer select-none"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0 pr-2">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-mono text-sm text-white font-semibold truncate max-w-xs">
              {seed.seed_text}
            </span>

            {seed.is_active ? (
              <span className="text-[10px] bg-green-500/10 border border-green-500/20 text-green-400 px-2 py-0.5 rounded-full flex items-center gap-1 font-medium shrink-0">
                <CheckCircle size={10} /> Active
              </span>
            ) : (
              <span className="text-[10px] bg-gray-800 border border-gray-700 text-gray-500 px-2 py-0.5 rounded-full flex items-center gap-1 shrink-0">
                <XCircle size={10} /> Inactive
              </span>
            )}

            <span
              className={`text-[10px] border px-2 py-0.5 rounded-full font-medium shrink-0 ${priorityColor}`}
            >
              {PRIORITY_LABELS[seed.priority] ?? `P${seed.priority}`}
            </span>
          </div>

          <div className="flex gap-3 text-xs text-gray-500 flex-wrap">
            <span>
              Category:{" "}
              <span className="text-orange-300 font-medium">
                {seed.threat_category.replace(/_/g, " ")}
              </span>
            </span>
            <span>
              Lang:{" "}
              <span className="text-gray-300">{seed.language_region}</span>
            </span>
            <span>
              Intent:{" "}
              <span className="text-gray-300">{seed.intent_type}</span>
            </span>
            <span>
              Source:{" "}
              <span className="text-gray-300">{seed.created_source}</span>
            </span>
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {seed.is_active && (
            <>
              {confirming ? (
                <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                  <span className="text-xs text-yellow-400">Deactivate?</span>
                  <button
                    onClick={handleDeactivate}
                    disabled={deactivating}
                    className="text-xs bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded-lg font-medium disabled:opacity-50 transition-colors"
                  >
                    {deactivating ? "…" : "Confirm"}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirming(false);
                    }}
                    className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleDeactivate}
                  className="text-gray-500 hover:text-red-400 hover:bg-gray-800 p-1.5 rounded-lg transition-colors"
                  title="Deactivate seed"
                >
                  <Trash2 size={14} />
                </button>
              )}
            </>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
            className="text-xs bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 text-blue-300 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
          >
            <BarChart2 size={12} />
            {expanded ? "Hide" : "Performance"}
          </button>

          {expanded ? (
            <ChevronUp size={16} className="text-gray-500" />
          ) : (
            <ChevronDown size={16} className="text-gray-500" />
          )}
        </div>
      </div>

      {/* Expanded panel */}
      {expanded && <PerformancePanel seedId={seed.id} />}
    </div>
  );
}

// ── New Seed Form ────────────────────────────────────────────────────────────

interface NewSeedFormProps {
  onCreated: (seed: SeedProfile) => void;
  onClose: () => void;
}

function NewSeedForm({ onCreated, onClose }: NewSeedFormProps) {
  const [form, setForm] = useState<SeedCreate>({
    seed_text: "",
    threat_category: "",
    language_region: "en",
    intent_type: "",
    priority: 3,
    created_source: "manual",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (field: keyof SeedCreate, value: string | number) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.seed_text.trim() || !form.threat_category.trim() || !form.intent_type.trim()) {
      setError("seed_text, threat_category, and intent_type are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createSeed(form);
      onCreated(created);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to create seed.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-blue-700/40 rounded-xl p-5 mb-5 relative">
      <button
        onClick={onClose}
        className="absolute top-3 right-3 text-gray-500 hover:text-gray-300 transition-colors"
        title="Close"
      >
        <X size={16} />
      </button>

      <h2 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
        <Plus size={15} className="text-blue-400" /> New Seed Profile
      </h2>

      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* seed_text */}
        <div className="md:col-span-2">
          <label className="block text-xs text-gray-400 mb-1">
            Seed Text <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            required
            value={form.seed_text}
            onChange={(e) => set("seed_text", e.target.value)}
            placeholder="e.g. colour prediction fraud"
            className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors font-mono"
          />
        </div>

        {/* threat_category */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Threat Category <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            required
            value={form.threat_category}
            onChange={(e) => set("threat_category", e.target.value)}
            placeholder="e.g. financial_fraud"
            className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {/* language_region */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Language / Region</label>
          <input
            type="text"
            value={form.language_region ?? "en"}
            onChange={(e) => set("language_region", e.target.value)}
            placeholder="en"
            className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {/* intent_type */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Intent Type <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            required
            value={form.intent_type}
            onChange={(e) => set("intent_type", e.target.value)}
            placeholder="e.g. recruitment, sale, scam"
            className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        {/* priority */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Priority (1–5)</label>
          <select
            value={form.priority ?? 3}
            onChange={(e) => set("priority", Number(e.target.value))}
            className="w-full bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors"
          >
            {[1, 2, 3, 4, 5].map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>

        {/* created_source */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Created Source</label>
          <select
            value={form.created_source ?? "manual"}
            onChange={(e) => set("created_source", e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-sm text-gray-300 rounded-lg px-3 py-2 outline-none focus:border-blue-500 transition-colors"
          >
            {CREATED_SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Error */}
        {error && (
          <div className="md:col-span-2 bg-red-950/40 border border-red-800 text-red-300 text-xs px-3 py-2 rounded-lg">
            {error}
          </div>
        )}

        {/* Submit */}
        <div className="md:col-span-2 flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-gray-200 px-4 py-2 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-5 py-2 rounded-lg flex items-center gap-2 disabled:opacity-50 transition-colors shadow-lg shadow-blue-600/20"
          >
            <Plus size={14} />
            {submitting ? "Creating…" : "Create Seed"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function SeedPerformancePage() {
  const [seeds, setSeeds] = useState<SeedProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [activeFilter, setActiveFilter] = useState<string>("");

  const loadSeeds = useCallback(async () => {
    setLoading(true);
    try {
      const params =
        activeFilter === "active"
          ? { is_active: true }
          : activeFilter === "inactive"
          ? { is_active: false }
          : undefined;
      const data = await fetchSeeds(params);
      setSeeds(data);
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  useEffect(() => {
    loadSeeds();
  }, [loadSeeds]);

  const handleCreated = (seed: SeedProfile) => {
    setSeeds((prev) => [seed, ...prev]);
    setShowForm(false);
  };

  const handleDeactivated = (id: number) => {
    setSeeds((prev) =>
      prev.map((s) => (s.id === id ? { ...s, is_active: false } : s))
    );
  };

  const activeCount = seeds.filter((s) => s.is_active).length;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Sprout size={22} className="text-green-400" />
          <div>
            <h1 className="text-xl font-bold text-white">Seed Performance</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Manage seed profiles and inspect variant execution coverage.
            </p>
          </div>
        </div>

        <button
          onClick={() => setShowForm((v) => !v)}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-xl flex items-center gap-2 transition-colors shadow-lg shadow-blue-600/20"
        >
          <Plus size={15} />
          {showForm ? "Cancel" : "+ New Seed"}
        </button>
      </div>

      {/* Inline new seed form */}
      {showForm && (
        <NewSeedForm onCreated={handleCreated} onClose={() => setShowForm(false)} />
      )}

      {/* Filters + count bar */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          {seeds.length} seed{seeds.length !== 1 ? "s" : ""} · {activeCount} active
        </span>

        <div className="flex gap-1.5">
          {[
            { label: "All", value: "" },
            { label: "Active", value: "active" },
            { label: "Inactive", value: "inactive" },
          ].map((opt) => (
            <button
              key={opt.value}
              onClick={() => setActiveFilter(opt.value)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors font-medium ${
                activeFilter === opt.value
                  ? "bg-blue-600/30 border-blue-500/50 text-blue-300"
                  : "bg-gray-800/60 border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Seed list */}
      <div className="space-y-2.5">
        {loading ? (
          <div className="text-center py-14 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl animate-pulse">
            Loading seed profiles…
          </div>
        ) : seeds.length === 0 ? (
          <div className="text-center py-14 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl">
            No seed profiles found.{" "}
            <button
              onClick={() => setShowForm(true)}
              className="text-blue-400 hover:text-blue-300 underline"
            >
              Create one above.
            </button>
          </div>
        ) : (
          seeds.map((seed) => (
            <SeedRow key={seed.id} seed={seed} onDeactivate={handleDeactivated} />
          ))
        )}
      </div>
    </div>
  );
}
