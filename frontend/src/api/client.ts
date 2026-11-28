import axios from "axios";

const BASE = "/api";

export const api = axios.create({ baseURL: BASE });

export async function downloadAuthenticatedPdf(apiRelativeUrl: string, fallbackFilename: string) {
  const path = apiRelativeUrl.startsWith("/api/")
    ? apiRelativeUrl.slice(4)
    : apiRelativeUrl;
  const resp = await api.get<Blob>(path, { responseType: "blob" });
  const blobUrl = URL.createObjectURL(resp.data);
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = fallbackFilename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface Channel {
  id: number;
  username: string;
  title: string | null;
  description?: string | null;
  telegram_id: number | null;
  member_count?: number | null;
  is_verified?: boolean;
  is_scam?: boolean;
  invite_link?: string | null;
  is_active: boolean;
  last_fetched_at: string | null;
}

export interface Identifier {
  type: string;
  value: string;
  normalised: string;
}

export interface MessageSnapshot {
  id: number;
  telegram_msg_id: number;
  source?: string | null;
  forwarded_from?: string | null;
  text: string | null;
  ocr_text?: string | null;
  evidence_hash?: string | null;
  original_text_hash?: string | null;
  media_hash?: string | null;
  provenance_status?: string | null;
  provenance_note?: string | null;
  raw_content_redacted?: boolean;
  created_at: string;
  channel_username: string;
  channel_title: string | null;
  sender_username: string | null;
  has_media: boolean;
  media_path: string | null;
  identifiers: Identifier[];
}

export interface Alert {
  id: number;
  risk_level: "HIGH" | "MEDIUM";
  score: number;
  categories: string[];
  evidence: {
    matched_terms: Array<{ term: string; category: string; weight: number; lexicon: string }>;
    ml_score: number | null;
    final_score: number;
    scoring_version?: string;
    category_confidence?: number;
    intent_confidence?: number;
    contact_signal?: number;
    negative_context_penalty?: number;
    reason_codes?: string[];
  };
  observation_count?: number;
  similar_channels_count?: number;
  shared_identifier_channels?: string[];
  classification_state?: "latest" | "legacy";
  scoring_version?: string;
  legacy_risk_level?: string | null;
  legacy_categories?: string[];
  category_display?: string;
  lifecycle_state?: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_reason?: string | null;
  is_reviewed: boolean;
  reviewed_by: string | null;
  created_at: string;
  message: MessageSnapshot;
  disposition?: string | null;
}

export interface AlertStats {
  HIGH: number;
  MEDIUM: number;
  total: number;
  unreviewed?: number;
  top_categories?: Array<{ category: string; count: number }>;
}

export interface GraphData {
  elements: CyElement[];
  node_count: number;
  edge_count: number;
  cluster_count: number;
}

export interface CyElement {
  data: Record<string, unknown>;
}

// ── API calls ──────────────────────────────────────────────────────────────────

export const fetchAlerts = (params?: {
  risk_level?: string;
  reviewed?: boolean;
  lifecycle_state?: string;
  include_historical?: boolean;
  skip?: number;
  limit?: number;
}) => api.get<Alert[]>("/alerts/", { params }).then((r) => r.data);

export const fetchAlertStats = () =>
  api.get<AlertStats>("/alerts/stats").then((r) => r.data);

export const reviewAlert = (id: number) =>
  api.patch(`/alerts/${id}/review`, { reviewed_by: "analyst" });

export const fetchChannels = () =>
  api.get<Channel[]>("/channels/").then((r) => r.data);

export const addChannel = (username: string) =>
  api.post<Channel>("/channels/", { username }).then((r) => r.data);

export const deleteChannel = (id: number) =>
  api.delete(`/channels/${id}`);

export const fetchGraph = (limit = 500) =>
  api.get<GraphData>("/graph/", { params: { limit } }).then((r) => r.data);

export const fetchEgoGraph = (identifier: string, radius = 2) =>
  api
    .get<GraphData>(`/graph/ego/${encodeURIComponent(identifier)}`, {
      params: { radius },
    })
    .then((r) => r.data);

export const searchIdentifier = (value: string) =>
  api.get("/search/identifier", { params: { value } }).then((r) => r.data);

export const getIdentifierSearchPdfUrl = (value: string) =>
  `/api/search/identifier/export/pdf?value=${encodeURIComponent(value)}`;

export const importCSV = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/import/csv", form).then((r) => r.data);
};

export const importJSON = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/import/json", form).then((r) => r.data);
};


// ── Scan & Channel Intelligence API ──────────────────────────────────────────────

export interface ScanJob {
  id: number;
  status: "pending" | "running" | "done" | "failed" | "interrupted";
  seed_terms: string[];
  total_channels_found: number;
  total_channels_scanned: number;
  total_messages_scanned: number;
  total_flagged: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  error: string | null;
}

export interface SampleMessage {
  id?: number | null;
  date?: string | null;
  text: string;
  score: number;
  categories: string[];
  risk_level: string;
  matched_terms?: string[];
  views?: number | null;
  forwards?: number | null;
  fwd_source?: string | null;
  sender_username?: string | null;
  provenance_status?: string | null;
  provenance_note?: string | null;
  evidence_hash?: string | null;
}

export interface ConnectedNodes {
  channels?: string[];
  handles?: string[];
  phones?: string[];
  upis?: string[];
  wallets?: string[];
  urls?: string[];
}

export interface ChannelScanResult {
  id: number;
  scan_job_id: number;
  channel_username: string;
  channel_title: string | null;
  channel_description?: string | null;
  telegram_id: number | null;
  member_count: number | null;
  is_verified?: boolean;
  is_scam?: boolean;
  invite_link?: string | null;
  messages_scanned: number;
  flagged_count: number;
  high_count: number;
  medium_count: number;
  avg_score: number;
  top_categories: string[];
  top_identifiers: Array<{ type: string; value: string }>;
  sample_messages: SampleMessage[];
  connected_nodes?: ConnectedNodes;
  risk_level: "HIGH" | "MEDIUM" | "LOW";
  seed_term: string;
  already_monitored: boolean;
  scanned_at: string;
}

export interface ChannelDetails {
  channel_id: number | null;
  scan_result_id: number | null;
  username: string;
  title: string;
  description: string | null;
  telegram_id: number | null;
  member_count: number | null;
  is_verified: boolean;
  is_scam: boolean;
  invite_link: string;
  is_monitored: boolean;
  risk_level: "HIGH" | "MEDIUM" | "LOW";
  avg_score: number;
  messages_scanned: number;
  flagged_count: number;
  high_count: number;
  medium_count: number;
  top_categories: string[];
  top_identifiers: Array<{ type: string; value: string }>;
  sample_messages: SampleMessage[];
  connected_nodes: ConnectedNodes;
}

export interface ChannelNetworkData {
  root_username: string;
  node_count: number;
  edge_count: number;
  elements: CyElement[];
  categories: {
    channels: string[];
    handles: string[];
    upis: string[];
    phones: string[];
    wallets: string[];
  };
}

export const runScan = (seedTerms?: string[], mode?: string, profile = "illegal_trade") =>
  api.post<{ job_id: number; status: string; profile?: string; message: string }>(
    "/scan/run",
    { seed_terms: seedTerms && seedTerms.length > 0 ? seedTerms : null, mode: mode ?? null, profile }
  ).then(r => r.data);

export interface ExpandFrontierItem {
  username: string;
  title: string;
  channel_id: number | null;
  hop: number;
  discovered_from: string;
  reasons: string[];
  evidence: string[];
  verification_status: string;
  telegram_id: number | null;
  member_count: number | null;
}

export interface NetworkExpandResult {
  root_username: string;
  mode: "dry_run" | "persist";
  verify: boolean;
  max_hops: number;
  frontier_count: number;
  persisted_count: number;
  frontier: ExpandFrontierItem[];
}

export const expandChannelNetwork = (
  idOrUsername: string | number,
  opts?: { max_hops?: number; limit?: number; persist?: boolean; verify?: boolean }
) =>
  api
    .post<NetworkExpandResult>(
      `/channels/${encodeURIComponent(String(idOrUsername))}/expand`,
      opts ?? { max_hops: 2, limit: 25, persist: false, verify: false }
    )
    .then((r) => r.data);

export const fetchScanJobs = (skip = 0, limit = 20) =>
  api.get<ScanJob[]>("/scan/jobs", { params: { skip, limit } }).then(r => r.data);

export const fetchScanJob = (jobId: number) =>
  api.get<ScanJob>(`/scan/jobs/${jobId}`).then(r => r.data);

export const cancelScanJob = (jobId: number) =>
  api.post<ScanJob>(`/scan/jobs/${jobId}/cancel`).then(r => r.data);

export const fetchScanResults = (
  jobId: number,
  params?: {
    risk_level?: string;
    category?: string;
    search?: string;
    skip?: number;
    limit?: number;
  } | string
) => {
  const queryParams = typeof params === "string" ? { risk_level: params } : params;
  return api
    .get<ChannelScanResult[]>(`/scan/jobs/${jobId}/results`, {
      params: queryParams,
    })
    .then(r => r.data);
};

export const addChannelFromScan = (jobId: number, resultId: number) =>
  api.post(`/scan/jobs/${jobId}/add-channel/${resultId}`).then(r => r.data);

export const fetchDefaultSeeds = (profile = "illegal_trade") =>
  api.get<{ count: number; profile: string; by_category: Record<string, number>; seeds: string[] }>(
    "/scan/seeds",
    { params: { profile } }
  ).then(r => r.data);

export const fetchChannelDetails = (idOrUsername: string | number) =>
  api.get<ChannelDetails>(`/channels/${encodeURIComponent(String(idOrUsername))}/details`).then((r) => r.data);

export const fetchChannelNetwork = (idOrUsername: string | number) =>
  api.get<ChannelNetworkData>(`/channels/${encodeURIComponent(String(idOrUsername))}/network`).then((r) => r.data);

export const getScanJobPdfUrl = (jobId: number) => `/api/scan/jobs/${jobId}/export/pdf`;

export const getScanResultPdfUrl = (resultId: number) => `/api/scan/results/${resultId}/export/pdf`;

export const getChannelPdfUrl = (idOrUsername: string | number) =>
  `/api/channels/${encodeURIComponent(String(idOrUsername))}/export/pdf`;


// ── Channel Scoring & Health ──────────────────────────────────────────────────

export interface ChannelScoreComponents {
  id: number;
  channel_scan_result_id: number;
  composite_score: number;
  max_message_score: number;
  high_confidence_message_count: number;
  distinct_incident_count: number;
  recency_weight: number;
  identifier_density: number;
  valid_pivot_count: number;
  analyst_confirmation_signal: number;
  scored_at: string;
}

export interface ChannelHealth {
  channel_id: number;
  channel_username: string;
  poll_tier: string;
  channel_status: string;
  error_state: boolean;
  consecutive_error_count: number;
  last_poll_attempted_at: string | null;
  recent_events: Array<{
    id: number;
    event_type: string;
    error_message: string | null;
    occurred_at: string;
  }>;
}

export interface AlertDisposition {
  disposition: string;
  notes?: string;
  changed_by: string;
}

export const getChannelHealth = (channelId: number) =>
  api.get<ChannelHealth>(`/channels/${channelId}/health`).then((r) => r.data);

export const setAlertDisposition = (alertId: number, data: AlertDisposition) =>
  api.post<any>(`/dispositions/alerts/${alertId}`, data).then((r) => r.data);

export const getAlertDispositionHistory = (alertId: number) =>
  api.get<any[]>(`/dispositions/history/alert/${alertId}`).then((r) => r.data);

export const clearAllData = () =>
  api.delete<{ status: string; message: string }>("/scan/clear", {
    data: { confirm: "CLEAR" },
  }).then((r) => r.data);
