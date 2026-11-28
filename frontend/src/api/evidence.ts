import { api } from "./client";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface ScanEvidence {
  id: number;
  scan_job_id: number;
  channel_username: string;
  telegram_message_id: number;
  message_timestamp: string | null;
  raw_text: string | null;
  normalised_text: string | null;
  classifier_score: number;
  risk_level: string;
  severity_tier: string;
  categories: string | null;
  matched_terms: string | null;
  seed_term: string | null;
  disposition: string | null;
  disposition_notes: string | null;
  disposition_by: string | null;
  disposition_at: string | null;
  provenance_status?: string | null;
  provenance_note?: string | null;
  evidence_hash?: string | null;
}

export interface DispositionRequest {
  disposition: string;
  notes?: string;
  changed_by: string;
}

export interface AuditEntry {
  id: number;
  previous_disposition: string | null;
  new_disposition: string;
  changed_by: string;
  changed_at: string;
  notes: string | null;
}

// ── API calls ──────────────────────────────────────────────────────────────────

export const fetchEvidence = (params?: {
  scan_job_id?: number;
  channel_username?: string;
  skip?: number;
  limit?: number;
}): Promise<ScanEvidence[]> =>
  api.get<ScanEvidence[]>("/evidence/", { params }).then((r) => r.data);

export const getEvidence = (id: number): Promise<ScanEvidence> =>
  api.get<ScanEvidence>(`/evidence/${id}`).then((r) => r.data);

export const setEvidenceDisposition = (
  id: number,
  data: DispositionRequest
): Promise<ScanEvidence> =>
  api
    .post<ScanEvidence>(`/dispositions/evidence/${id}`, data)
    .then((r) => r.data);

export const getDispositionHistory = (
  targetType: string,
  targetId: number
): Promise<AuditEntry[]> =>
  api
    .get<AuditEntry[]>(`/dispositions/history/${targetType}/${targetId}`)
    .then((r) => r.data);
