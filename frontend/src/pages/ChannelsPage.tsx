import { useEffect, useState } from "react";
import {
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Share2,
  FileDown,
  Search,
  Users,
  Shield,
} from "lucide-react";
import { fetchChannels, addChannel, deleteChannel, getChannelPdfUrl, downloadAuthenticatedPdf } from "../api/client";
import type { Channel } from "../api/client";
import { formatDistanceToNow } from "date-fns";
import ChannelDetailModal from "../components/ChannelDetailModal";

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null);

  const load = async () => {
    const data = await fetchChannels();
    setChannels(data);
  };

  useEffect(() => {
    load();
  }, []);

  const handleAdd = async () => {
    const username = input.trim().replace(/^@/, "");
    if (!username) return;
    setAdding(true);
    setError(null);
    try {
      const ch = await addChannel(username);
      setChannels((prev) => [ch, ...prev]);
      setInput("");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to add channel";
      setError(msg);
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id: number) => {
    await deleteChannel(id);
    setChannels((prev) =>
      prev.map((c) => (c.id === id ? { ...c, is_active: false } : c))
    );
  };

  const filteredChannels = channels.filter(
    (c) =>
      c.username.toLowerCase().includes(search.toLowerCase()) ||
      (c.title && c.title.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Detail Modal */}
      {selectedChannel && (
        <ChannelDetailModal
          usernameOrId={selectedChannel}
          onClose={() => setSelectedChannel(null)}
          onWatchStatusChange={load}
        />
      )}

      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Shield size={22} className="text-blue-400" /> Monitored Watchlist Channels
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Real-time automated polling every 60s. Click any channel to inspect connecting nodes,
            dossiers, and evidence.
          </p>
        </div>
      </div>

      {/* Add channel bar */}
      <div className="flex gap-2 mb-5">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="channel_username (without @)"
          className="flex-1 bg-gray-800 border border-gray-700 text-sm text-white rounded-xl px-4 py-2.5 outline-none focus:border-blue-500 transition-colors"
        />
        <button
          onClick={handleAdd}
          disabled={adding || !input.trim()}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-5 py-2.5 rounded-xl flex items-center gap-2 disabled:opacity-50 transition-colors font-medium shadow-lg shadow-blue-600/20"
        >
          <Plus size={16} />
          Add Channel
        </button>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800 text-red-300 text-xs px-3.5 py-2 rounded-xl mb-4">
          {error}
        </div>
      )}

      {/* Filter / Search Bar */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
          Watchlist ({channels.length})
        </span>

        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-2.5 text-gray-500" />
          <input
            type="text"
            placeholder="Filter channels..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-gray-800/80 border border-gray-700/80 text-xs text-white rounded-lg pl-8 pr-3 py-1.5 outline-none focus:border-blue-500 w-52"
          />
        </div>
      </div>

      {/* Channel list */}
      <div className="space-y-2.5">
        {filteredChannels.map((ch) => (
          <div
            key={ch.id}
            onClick={() => setSelectedChannel(ch.username)}
            className="flex items-center justify-between bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl px-4 py-3 cursor-pointer transition-all hover:bg-gray-850"
          >
            <div className="flex-1 min-w-0 pr-4">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-mono text-white font-bold hover:text-blue-400 transition-colors">
                  @{ch.username}
                </span>
                {ch.is_active ? (
                  <span className="text-[10px] bg-green-500/10 border border-green-500/20 text-green-400 px-2 py-0.5 rounded-full flex items-center gap-1 font-medium">
                    <CheckCircle size={10} /> Active Monitor
                  </span>
                ) : (
                  <span className="text-[10px] bg-gray-800 text-gray-500 border border-gray-700 px-2 py-0.5 rounded-full flex items-center gap-1">
                    <XCircle size={10} /> Inactive
                  </span>
                )}
                {ch.member_count != null && (
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <Users size={11} className="text-gray-500" />
                    {ch.member_count.toLocaleString()}
                  </span>
                )}
              </div>

              {ch.title && (
                <p className="text-xs text-gray-300 font-medium mt-0.5 truncate">{ch.title}</p>
              )}

              <p className="text-[11px] text-gray-500 mt-1">
                {ch.last_fetched_at
                  ? `Last fetched ${formatDistanceToNow(new Date(ch.last_fetched_at), { addSuffix: true })}`
                  : "Not yet polled by collector"}
              </p>
            </div>

            {/* Quick Actions */}
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedChannel(ch.username);
                }}
                className="text-xs bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
                title="Inspect Network & Nodes"
              >
                <Share2 size={12} />
                Network
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  void downloadAuthenticatedPdf(getChannelPdfUrl(ch.username), `telemonitor_${ch.username}_dossier.pdf`);
                }}
                className="text-xs bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 px-2.5 py-1.5 rounded-lg flex items-center gap-1 font-medium transition-colors"
                title="Export PDF Dossier"
              >
                <FileDown size={12} />
                PDF
              </button>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(ch.id);
                }}
                className="text-gray-500 hover:text-red-400 hover:bg-gray-800 p-1.5 rounded-lg transition-colors ml-1"
                title="Deactivate channel"
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}

        {filteredChannels.length === 0 && (
          <div className="text-center py-14 text-gray-500 text-sm bg-gray-900 border border-gray-800 rounded-xl">
            {search ? "No monitored channels match your search." : "No channels in watchlist yet. Add one above or from the Scanner."}
          </div>
        )}
      </div>
    </div>
  );
}
