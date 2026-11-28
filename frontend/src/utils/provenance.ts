export function provenanceNote(status?: string | null, note?: string | null): string | null {
  if (note) return note;
  if (status === "unverifiable_media") {
    return "Original media unavailable; provenance cannot be fully recomputed.";
  }
  if (status === "missing_content") {
    return "Original content unavailable; provenance cannot be recomputed.";
  }
  return null;
}

export function provenanceBadgeClass(status?: string | null): string {
  if (status === "verified_hashes") {
    return "bg-emerald-950/50 text-emerald-300 border-emerald-700/40";
  }
  if (status === "unverifiable_media" || status === "missing_content") {
    return "bg-amber-950/50 text-amber-300 border-amber-700/40";
  }
  return "bg-slate-800 text-slate-300 border-slate-700";
}

