// Group duplicate alerts — the same ad text posted across several channels —
// so the dashboard shows one card per unique content with all occurrences.
import type { Alert } from "../api/client";

export interface AlertOccurrence {
  alert_id: number;
  channel_username: string;
  channel_title: string | null;
  created_at: string;
  score: number;
  risk_level: string;
}

export interface AlertGroup {
  representative: Alert;
  occurrences: AlertOccurrence[]; // every member incl. the representative
}

function groupKey(a: Alert): string {
  if (a.message.original_text_hash) return `h:${a.message.original_text_hash}`;
  const text = (a.message.text || "").trim();
  if (text) return `t:${text.slice(0, 300)}`;
  return `id:${a.id}`;
}

/**
 * Group alerts whose content hash (or text) matches. The representative is
 * the highest-scoring member; every member is listed as an occurrence.
 * Order of first appearance in the input (newest first) is preserved.
 */
export function groupAlerts(alerts: Alert[]): AlertGroup[] {
  const byKey = new Map<string, AlertGroup>();
  const order: string[] = [];
  for (const a of alerts) {
    const key = groupKey(a);
    let g = byKey.get(key);
    if (!g) {
      g = { representative: a, occurrences: [] };
      byKey.set(key, g);
      order.push(key);
    }
    g.occurrences.push({
      alert_id: a.id,
      channel_username: a.message.channel_username,
      channel_title: a.message.channel_title,
      created_at: a.created_at,
      score: a.score,
      risk_level: a.risk_level,
    });
    if (a.score > g.representative.score) g.representative = a;
  }
  return order.map((k) => byKey.get(k)!);
}
