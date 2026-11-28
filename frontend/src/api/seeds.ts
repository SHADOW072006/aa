import { api } from "./client";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface SeedProfile {
  id: number;
  seed_text: string;
  seed_text_normalised: string;
  threat_category: string;
  language_region: string;
  intent_type: string;
  priority: number;
  is_active: boolean;
  created_source: string;
  created_at: string;
  updated_at: string;
}

export interface SeedCreate {
  seed_text: string;
  threat_category: string;
  language_region?: string;
  intent_type: string;
  priority?: number;
  created_source?: string;
}

export interface SeedUpdate {
  threat_category?: string;
  language_region?: string;
  intent_type?: string;
  priority?: number;
  is_active?: boolean;
}

export interface SeedPerformance {
  seed_profile_id: number;
  total_variants: number;
  total_executions: number;
  total_channels_found: number;
  total_channels_added: number;
  variants: Array<{ variant_text: string; variant_type: string; executions: number }>;
}

// ── API calls ──────────────────────────────────────────────────────────────────

export async function fetchSeeds(params?: {
  is_active?: boolean;
  threat_category?: string;
  skip?: number;
  limit?: number;
}): Promise<SeedProfile[]> {
  return api.get<SeedProfile[]>("/seeds/", { params }).then((r) => r.data);
}

export async function createSeed(data: SeedCreate): Promise<SeedProfile> {
  return api.post<SeedProfile>("/seeds/", data).then((r) => r.data);
}

export async function getSeed(id: number): Promise<SeedProfile> {
  return api.get<SeedProfile>(`/seeds/${id}`).then((r) => r.data);
}

export async function updateSeed(id: number, data: SeedUpdate): Promise<SeedProfile> {
  return api.patch<SeedProfile>(`/seeds/${id}`, data).then((r) => r.data);
}

export async function deactivateSeed(id: number): Promise<void> {
  await api.delete(`/seeds/${id}`);
}

export async function getSeedPerformance(id: number): Promise<SeedPerformance> {
  return api.get<SeedPerformance>(`/seeds/${id}/performance`).then((r) => r.data);
}
