import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, FileDown } from "lucide-react";
import {
  searchIdentifier,
  getIdentifierSearchPdfUrl,
  downloadAuthenticatedPdf,
} from "../api/client";
import { formatDistanceToNow } from "date-fns";

interface SearchResult {
  identifier: { type: string; value: string; normalised: string };
  message: {
    id: number;
    text: string | null;
    created_at: string;
    channel: string | null;
    channel_title: string | null;
    source: string;
  };
  alert: { risk_level: string; score: number } | null;
}

interface SearchResponse {
  query: string;
  count: number;
  results: SearchResult[];
}

const RISK_COLOR: Record<string, string> = {
  HIGH: "text-red-400",
  MEDIUM: "text-yellow-400",
};

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const initialQ = searchParams.get("q") ?? "";
  const [query, setQuery] = useState(initialQ);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runSearch = async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchIdentifier(trimmed);
      setResults(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Search failed. Check the backend connection.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialQ.trim().length >= 3) {
      void runSearch(initialQ);
    }
  }, [initialQ]);

  const handleSearch = () => void runSearch(query);

  const handleExportPdf = async () => {
    if (!results?.query) return;
    setDownloadingPdf(true);
    setError(null);
    try {
      const safe = results.query.replace(/[^a-zA-Z0-9_-]+/g, "_").slice(0, 40) || "identifier";
      await downloadAuthenticatedPdf(
        getIdentifierSearchPdfUrl(results.query),
        `telemonitor_identifier_${safe}.pdf`
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "PDF export failed.");
    } finally {
      setDownloadingPdf(false);
    }
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-1">Identifier Search</h1>
      <p className="text-sm text-gray-500 mb-5">
        Find all posts containing a phone number, UPI ID, Telegram handle or crypto wallet, and export a PDF usage report.
      </p>

      {/* Search input */}
      <div className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="+919876543210 · user@paytm · @username · 1A1zP1..."
            className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-lg pl-9 pr-4 py-2.5 outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        <button
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-5 py-2.5 rounded-lg disabled:opacity-50 transition-colors"
        >
          {loading ? "…" : "Search"}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      {/* Results */}
      {results && (
        <>
          <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
            <p className="text-sm text-gray-400">
              {results.count} result{results.count !== 1 ? "s" : ""} for{" "}
              <span className="text-white font-mono">{results.query}</span>
            </p>
            {results.count > 0 && (
              <button
                onClick={handleExportPdf}
                disabled={downloadingPdf}
                className="flex items-center gap-1.5 text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 px-3 py-1.5 rounded-lg font-medium transition-colors disabled:opacity-50"
                title="Download PDF report showing where this identifier is used"
              >
                <FileDown size={13} />
                {downloadingPdf ? "Generating PDF…" : "Export PDF Report"}
              </button>
            )}
          </div>
          {results.count === 0 ? (
            <div className="text-gray-600 text-sm py-8 text-center">No matches found.</div>
          ) : (
            <div className="space-y-3">
              {results.results.map((r, i) => (
                <div
                  key={i}
                  className="bg-gray-900 border border-gray-800 rounded-xl p-4"
                >
                  <div className="flex items-start gap-3 mb-2">
                    <span className="text-xs bg-blue-900/40 border border-blue-700/30 text-blue-300 px-2 py-0.5 rounded font-mono">
                      {r.identifier.type}
                    </span>
                    <span className="text-sm font-mono text-white break-all">
                      {r.identifier.value}
                    </span>
                    {r.alert && (
                      <span
                        className={`ml-auto text-xs font-bold ${RISK_COLOR[r.alert.risk_level] ?? "text-gray-400"}`}
                      >
                        {r.alert.risk_level} ({(r.alert.score * 100).toFixed(0)}%)
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mb-1">
                    <span className="text-blue-400">@{r.message.channel}</span>
                    {r.message.channel_title && (
                      <span className="text-gray-600 ml-1">{r.message.channel_title}</span>
                    )}{" "}
                    · {formatDistanceToNow(new Date(r.message.created_at), { addSuffix: true })}
                    {" "}· <span className="text-gray-600">{r.message.source}</span>
                  </p>
                  <p className="text-sm text-gray-300 font-mono whitespace-pre-wrap break-words line-clamp-3">
                    {r.message.text || "[no text]"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
