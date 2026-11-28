import { api } from "./client";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface PivotCandidate {
  id: number;
  source_channel_username: string;
  candidate_type: string;
  candidate_value: string;
  status: string;
  created_at: string;
  evaluated_at: string | null;
  evaluated_by: string | null;
  notes: string | null;
}

export interface PivotAction {
  evaluated_by: string;
  notes?: string;
}

// ── API calls ──────────────────────────────────────────────────────────────────

export async function fetchPendingPivots(
  params?: { skip?: number; limit?: number }
): Promise<PivotCandidate[]> {
  return api.get<PivotCandidate[]>("/pivots/", { params }).then((r) => r.data);
}

export async function approvePivot(
  id: number,
  action: PivotAction
): Promise<PivotCandidate> {
  return api
    .post<PivotCandidate>(`/pivots/${id}/approve`, action)
    .then((r) => r.data);
}

export async function rejectPivot(
  id: number,
  action: PivotAction
): Promise<PivotCandidate> {
  return api
    .post<PivotCandidate>(`/pivots/${id}/reject`, action)
    .then((r) => r.data);
}
