import { Routes, Route, NavLink } from "react-router-dom";
import {
  ShieldAlert, Radio, Share2, Search, Upload, Settings, ScanSearch, Sprout, GitMerge,
} from "lucide-react";
import DashboardPage from "./pages/DashboardPage";
import AlertsPage from "./pages/AlertsPage";
import GraphPage from "./pages/GraphPage";
import SearchPage from "./pages/SearchPage";
import ChannelsPage from "./pages/ChannelsPage";
import ImportPage from "./pages/ImportPage";
import ScanPage from "./pages/ScanPage";
import SeedPerformancePage from "./pages/SeedPerformancePage";
import PivotQueuePage from "./pages/PivotQueuePage";

const NAV = [
  { to: "/", label: "Dashboard", icon: ShieldAlert },
  { to: "/alerts", label: "Alerts", icon: Radio },
  { to: "/scan", label: "Scanner", icon: ScanSearch },
  { to: "/seeds", label: "Seeds", icon: Sprout },
  { to: "/pivots", label: "Pivots", icon: GitMerge },
  { to: "/graph", label: "Entity Graph", icon: Share2 },
  { to: "/search", label: "Search", icon: Search },
  { to: "/channels", label: "Channels", icon: Settings },
  { to: "/import", label: "Import", icon: Upload },
];

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <ShieldAlert className="text-blue-400" size={22} />
            <span className="font-bold text-white text-sm tracking-wide">TeleMonitor</span>
          </div>
          <p className="text-gray-500 text-xs mt-1">OSINT Alert Dashboard</p>
        </div>
        <nav className="flex-1 py-4 px-2 space-y-1">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:bg-gray-800 hover:text-white"
                }`
              }
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-gray-800 text-xs text-gray-600">
          v1.3.0 · Law-enforcement OSINT use only
        </div>
      </aside>

      <main className="flex-1 overflow-auto bg-gray-950">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/seeds" element={<SeedPerformancePage />} />
          <Route path="/pivots" element={<PivotQueuePage />} />
          <Route path="/import" element={<ImportPage />} />
        </Routes>
      </main>
    </div>
  );
}
