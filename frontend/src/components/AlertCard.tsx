import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle, ArrowRight, AtSign, Bitcoin, CheckCircle, ChevronDown, ChevronRight,
  Copy, Check, CreditCard, Flame, Forward, Globe, Landmark, Phone, ShieldCheck,
} from "lucide-react";
import type { Alert } from "../api/client";
import type { AlertOccurrence } from "../utils/alertGrouping";
import { provenanceNote } from "../utils/provenance";
import DispositionControls from "./DispositionControls";

interface Props {
  alert: Alert;
  /** Other channels where the same content was flagged (grouped display). */
  occurrences?: AlertOccurrence[];
  onReview?: (id: number) => void;
  onInspectChannel?: (username: string) => void;
  onDispositionSet?: (id: number, newDisposition: string) => void;
}

const RISK_STYLES: Record<string, string> = {
  HIGH: "border-l-4 border-red-500 bg-red-950/20",
  MEDIUM: "border-l-4 border-amber-500 bg-amber-950/10",
};

const RISK_BADGE: Record<string, string> = {
  HIGH: "bg-red-500/15 text-red-400 border border-red-500/30",
  MEDIUM: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
};

const SCORE_COLOR: Record<string, string> = {
  HIGH: "text-red-400",
  MEDIUM: "text-amber-400",
};

const DISPOSITION_BADGE: Record<string, string> = {
  confirmed_threat: "bg-red-500/20 text-red-400 border border-red-500/30",
  false_positive: "bg-green-500/20 text-green-400 border border-green-500/30",
  needs_review: "bg-amber-500/20 text-amber-400 border border-amber-500/30",
  escalated: "bg-purple-500/20 text-purple-400 border border-purple-500/30",
};

function dispositionLabel(value: string): string {
  const labels: Record<string, string> = {
    confirmed_threat: "Confirmed Threat",
    false_positive: "False Positive",
    needs_review: "Needs Review",
    escalated: "Escalated",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}

const IDENT_ICON: Record<string, React.ReactNode> = {
  phone: <Phone size={12} />,
  upi: <CreditCard size={12} />,
  handle: <AtSign size={12} />,
  wallet_btc: <Bitcoin size={12} />,
  wallet_eth: <Bitcoin size={12} />,
  wallet_usdt: <Bitcoin size={12} />,
  bank_account: <Landmark size={12} />,
  ifsc: <Landmark size={12} />,
  site: <Globe size={12} />,
  bank_card: <CreditCard size={12} />,
  imei: <ShieldCheck size={12} />,
};

const IDENT_LABEL: Record<string, string> = {
  phone: "phone",
  upi: "UPI",
  handle: "handle",
  wallet_usdt: "USDT",
  wallet_btc: "BTC",
  wallet_eth: "ETH",
  bank_account: "account",
  ifsc: "IFSC",
  site: "site",
  bank_card: "card",
  imei: "IMEI",
};

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Highlight matched lexicon terms inside the post text. */
function HighlightedText({ text, terms }: { text: string; terms: Array<{ term: string }> }) {
  const needles = Array.from(
    new Set(
      terms
        .map((t) => t.term.replace(/^emoji:/, "").trim())
        .filter((t) => Array.from(t).length >= 2)
    )
  ).sort((a, b) => b.length - a.length);
  if (!needles.length) return <>{text}</>;
  let re: RegExp;
  try {
    re = new RegExp(`(${needles.map(escapeRegExp).join("|")})`, "gi");
  } catch {
    return <>{text}</>;
  }
  const parts = text.split(re);
  const lower = new Set(needles.map((n) => n.toLowerCase()));
  return (
    <>
      {parts.map((part, i) =>
        part && lower.has(part.toLowerCase()) ? (
          <mark key={i} className="bg-orange-500/25 text-orange-200 rounded-[3px] px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

/** Collapse a whole-block duplication inside one line ("X X" -> "X"). */
function dedupeBlock(text: string): string {
  const t = text.trim();
  if (t.length < 50) return t;
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9\u0080-\uffff]/g, "");
  const half = Math.floor(t.length / 2);
  for (let n = half; n >= 25; n--) {
    const first = t.slice(0, n).trim();
    const second = t.slice(n).trim();
    if (first.length >= 25 && norm(first).length >= 20 && norm(first) === norm(second)) return first;
  }
  return t;
}

/** OCR text arrives with repeated lines/blocks from the recogniser — keep first occurrence. */
function cleanOcrLines(ocr: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const line of ocr.split(/\r?\n/)) {
    const t = dedupeBlock(line.trim());
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
  }
  return out;
}

function CopyChip({ value, label, icon }: { value: string; label?: string; icon?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
      title={`Copy: ${value}`}
      className="inline-flex items-center gap-1.5 text-xs bg-gray-800/80 border border-gray-700 text-gray-300 px-2 py-0.5 rounded font-mono hover:border-gray-500 hover:text-white transition-colors"
    >
      {icon}
      {label ?? value}
      {copied ? <Check size={11} className="text-green-400" /> : <Copy size={10} className="text-gray-600" />}
    </button>
  );
}

function Section({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="mt-2 group">
      <summary className="flex items-center gap-1 text-xs text-gray-500 cursor-pointer hover:text-gray-300 select-none list-none">
        <ChevronRight size={12} className="group-open:hidden" />
        <ChevronDown size={12} className="hidden group-open:block" />
        {title}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export default function AlertCard({ alert, occurrences, onReview, onInspectChannel, onDispositionSet }: Props) {
  const msg = alert.message;
  const ago = formatDistanceToNow(new Date(alert.created_at), { addSuffix: true });
  const [showFullText, setShowFullText] = useState(false);
  const [showFullOcr, setShowFullOcr] = useState(false);

  const rawText = msg.raw_content_redacted ? null : (msg.text || "").trim();
  const bodyText = rawText || "[no text — content only in attached image]";
  const textClamped = !showFullText && bodyText.length > 420;
  const shownText = textClamped ? bodyText.slice(0, 420) : bodyText;

  const ocrLines = msg.ocr_text ? cleanOcrLines(msg.ocr_text) : [];
  const ocrShown = showFullOcr ? ocrLines : ocrLines.slice(0, 3);

  const otherChannels = (occurrences ?? []).filter(
    (o) => o.channel_username !== msg.channel_username
  );
  const sharedIdent = alert.shared_identifier_channels ?? [];

  return (
    <div className={`rounded-xl p-4 ${RISK_STYLES[alert.risk_level] ?? "border-l-4 border-gray-600 bg-gray-900/60"}`}>
      {/* ── Header: risk · channel · time ─────────────────────────────────── */}
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className={`text-[11px] font-bold tracking-wide px-2 py-0.5 rounded-full ${RISK_BADGE[alert.risk_level]}`}>
          {alert.risk_level === "HIGH" ? <Flame size={10} className="inline mr-1 -mt-0.5" /> : <AlertTriangle size={10} className="inline mr-1 -mt-0.5" />}
          {alert.risk_level}
        </span>
        <span className={`text-sm font-bold font-mono ${SCORE_COLOR[alert.risk_level] ?? "text-gray-300"}`}>
          {(alert.score * 100).toFixed(0)}
        </span>
        <button
          onClick={() => onInspectChannel?.(msg.channel_username)}
          className="text-sm text-blue-400 hover:text-blue-300 font-semibold hover:underline transition-colors truncate max-w-[240px]"
          title="Inspect channel dossier"
        >
          {msg.channel_title || `@${msg.channel_username}`}
        </button>
        <span className="text-xs text-gray-600 font-mono">@{msg.channel_username}</span>
        {msg.source && (
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700">
            {msg.source.replace(/_/g, " ")}
          </span>
        )}
        {msg.forwarded_from && (
          <span className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-indigo-950/60 text-indigo-300 border border-indigo-700/40" title={`Forwarded from ${msg.forwarded_from}`}>
            <Forward size={10} />
            forwarded
          </span>
        )}
        {alert.disposition && (
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${DISPOSITION_BADGE[alert.disposition] ?? "bg-gray-700 text-gray-300 border border-gray-600"}`}>
            {dispositionLabel(alert.disposition)}
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto shrink-0">{ago}</span>
        {alert.is_reviewed ? (
          <span className="text-xs text-green-400 flex items-center gap-1 shrink-0">
            <CheckCircle size={13} /> Reviewed
          </span>
        ) : (
          onReview && (
            <button
              onClick={() => onReview(alert.id)}
              className="text-xs bg-gray-800/80 hover:bg-gray-700 border border-gray-700 text-gray-300 px-2.5 py-1 rounded-lg transition-colors shrink-0"
            >
              Mark reviewed
            </button>
          )
        )}
      </div>

      {/* ── Cross-channel strip (the syndicate signal) ────────────────────── */}
      {(otherChannels.length > 0 || (alert.similar_channels_count ?? 0) > 0 || sharedIdent.length > 0) && (
        <div className="mt-2.5 flex items-center gap-2 flex-wrap text-xs bg-purple-950/30 border border-purple-800/40 rounded-lg px-2.5 py-1.5">
          <span className="text-purple-300 font-semibold">
            {otherChannels.length > 0
              ? `Same content flagged in ${otherChannels.length + 1} channels`
              : `Similar post seen in ${alert.similar_channels_count} channels`}
          </span>
          {otherChannels.slice(0, 6).map((o) => (
            <button
              key={o.alert_id}
              onClick={() => onInspectChannel?.(o.channel_username)}
              className="text-[11px] font-mono bg-purple-900/40 text-purple-200 border border-purple-700/50 px-1.5 py-0.5 rounded hover:border-purple-400 transition-colors"
            >
              @{o.channel_username}
            </button>
          ))}
          {sharedIdent.length > 0 && (
            <span className="text-[11px] text-amber-300" title={`Shared contact infrastructure with: ${sharedIdent.join(", ")}`}>
              · shared contacts with {sharedIdent.length} channel{sharedIdent.length > 1 ? "s" : ""}
            </span>
          )}
        </div>
      )}

      {/* ── Post text (the hero) ──────────────────────────────────────────── */}
      <p className="mt-3 text-[15px] leading-relaxed text-gray-100 whitespace-pre-wrap break-words">
        {msg.raw_content_redacted ? (
          <span className="text-gray-500 italic">[Raw content hidden — operator authentication required]</span>
        ) : (
          <HighlightedText text={shownText} terms={alert.evidence?.matched_terms ?? []} />
        )}
        {textClamped && (
          <button
            onClick={() => setShowFullText(true)}
            className="ml-2 text-xs text-blue-400 hover:text-blue-300 inline-flex items-center gap-0.5"
          >
            Show more <ArrowRight size={11} />
          </button>
        )}
        {showFullText && bodyText.length > 420 && (
          <button onClick={() => setShowFullText(false)} className="ml-2 text-xs text-gray-500 hover:text-gray-300">
            Show less
          </button>
        )}
      </p>

      {/* ── OCR: text recovered from the attached image ───────────────────── */}
      {ocrLines.length > 0 && (
        <div className="mt-2.5 rounded-lg border border-cyan-800/30 bg-cyan-950/20 px-3 py-2">
          <p className="text-[10px] uppercase tracking-widest text-cyan-500/80 mb-1">From image (OCR)</p>
          <p className={`text-[13px] leading-relaxed text-cyan-100/80 whitespace-pre-wrap break-words ${showFullOcr ? "" : "line-clamp-3"}`}>
            {ocrShown.join("\n")}
          </p>
          {ocrLines.length > 3 && (
            <button
              onClick={() => setShowFullOcr((v) => !v)}
              className="mt-1 text-[11px] text-cyan-400/80 hover:text-cyan-300"
            >
              {showFullOcr ? "Show less" : `Show all ${ocrLines.length} lines`}
            </button>
          )}
        </div>
      )}

      {/* ── Provenance warning (only when something is off) ───────────────── */}
      {provenanceNote(msg.provenance_status, msg.provenance_note) &&
        msg.provenance_status !== "verified_hashes" && msg.provenance_status !== "hash_backfilled" && (
          <p className="mt-2.5 text-xs text-amber-300 bg-amber-950/30 border border-amber-800/40 rounded px-2 py-1">
            {provenanceNote(msg.provenance_status, msg.provenance_note)}
          </p>
        )}

      {/* ── Identifiers (copy-on-click) + categories ──────────────────────── */}
      {(msg.identifiers.length > 0 || alert.categories.length > 0) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {msg.identifiers.map((ident, i) => (
            <CopyChip
              key={`id${i}`}
              value={ident.normalised || ident.value}
              label={ident.value}
              icon={
                <>
                  {IDENT_ICON[ident.type] ?? null}
                  {IDENT_LABEL[ident.type] && (
                    <span className="text-[9px] uppercase text-gray-500 font-sans">{IDENT_LABEL[ident.type]}</span>
                  )}
                </>
              }
            />
          ))}
          {alert.categories.map((cat) => (
            <span
              key={cat}
              className="text-[11px] bg-gray-800/70 text-gray-400 border border-gray-700/70 px-2 py-0.5 rounded-full"
            >
              {cat.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      )}

      {/* ── Collapsible: occurrences · evidence chain · score · disposition ── */}
      <div className="mt-2 border-t border-gray-800/70 pt-1">
        {otherChannels.length > 0 && (
          <Section title={`All occurrences (${otherChannels.length + 1})`}>
            <div className="space-y-1">
              {[{ channel_username: msg.channel_username, channel_title: msg.channel_title, created_at: alert.created_at, score: alert.score, risk_level: alert.risk_level }, ...otherChannels].map(
                (o, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-gray-400 bg-gray-900/60 border border-gray-800 rounded px-2 py-1">
                    <span className={o.risk_level === "HIGH" ? "text-red-400 font-semibold" : "text-amber-400"}>
                      {(o.score * 100).toFixed(0)}
                    </span>
                    <button
                      onClick={() => onInspectChannel?.(o.channel_username)}
                      className="font-mono text-gray-300 hover:text-blue-300 hover:underline"
                    >
                      @{o.channel_username}
                    </button>
                    <span className="text-gray-600 ml-auto">{formatDistanceToNow(new Date(o.created_at), { addSuffix: true })}</span>
                  </div>
                )
              )}
            </div>
          </Section>
        )}

        <Section title="Evidence chain & provenance">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-400 bg-gray-950/60 border border-gray-800 rounded-lg p-2.5">
            {msg.evidence_hash && <CopyChip value={String(msg.evidence_hash)} label={`ev_hash: ${String(msg.evidence_hash).slice(0, 10)}…`} />}
            {msg.original_text_hash && <CopyChip value={String(msg.original_text_hash)} label={`text: ${String(msg.original_text_hash).slice(0, 10)}…`} />}
            {msg.media_hash && <CopyChip value={String(msg.media_hash)} label={`media: ${String(msg.media_hash).slice(0, 10)}…`} />}
            {typeof alert.observation_count === "number" && (
              <span className="bg-gray-800/60 border border-gray-700/70 px-1.5 py-0.5 rounded">observed {alert.observation_count}×</span>
            )}
            {alert.scoring_version && (
              <span className="bg-gray-800/60 border border-gray-700/70 px-1.5 py-0.5 rounded">scorer: {alert.scoring_version}</span>
            )}
            {msg.provenance_status && (
              <span className="bg-gray-800/60 border border-gray-700/70 px-1.5 py-0.5 rounded">
                provenance: {msg.provenance_status}
                {provenanceNote(msg.provenance_status, msg.provenance_note) ? ` — ${provenanceNote(msg.provenance_status, msg.provenance_note)}` : ""}
              </span>
            )}
            {alert.lifecycle_state && alert.lifecycle_state !== "active" && (
              <span className="bg-gray-800/60 border border-gray-700/70 px-1.5 py-0.5 rounded">lifecycle: {alert.lifecycle_state}</span>
            )}
            {(alert.legacy_categories?.length ?? 0) > 0 && (
              <span className="bg-gray-800/60 border border-gray-700/70 px-1.5 py-0.5 rounded">legacy: {alert.legacy_categories!.join(", ")}</span>
            )}
          </div>
        </Section>

        {(alert.evidence?.scoring_version || (alert.evidence?.matched_terms?.length ?? 0) > 0) && (
          <Section title={`Score breakdown (${alert.evidence?.matched_terms?.length ?? 0} matched terms)`}>
            {alert.evidence?.scoring_version && (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs bg-gray-950/60 border border-gray-800 rounded-lg p-2.5">
                <div><span className="text-gray-500 block">Category Conf</span><span className="font-mono text-gray-200">{((alert.evidence.category_confidence ?? 0) * 100).toFixed(0)}%</span></div>
                <div><span className="text-gray-500 block">Intent Conf</span><span className="font-mono text-gray-200">{((alert.evidence.intent_confidence ?? 0) * 100).toFixed(0)}%</span></div>
                <div><span className="text-gray-500 block">Contact Signal</span><span className="font-mono text-gray-200">{((alert.evidence.contact_signal ?? 0) * 100).toFixed(0)}%</span></div>
                <div><span className="text-gray-500 block">Neg Penalty</span><span className="font-mono text-amber-400">-{((alert.evidence.negative_context_penalty ?? 0) * 100).toFixed(0)}%</span></div>
                <div><span className="text-gray-500 block">Final Score</span><span className="font-mono text-white font-bold">{((alert.evidence.final_score ?? alert.score) * 100).toFixed(0)}%</span></div>
                {Array.isArray(alert.evidence.reason_codes) && alert.evidence.reason_codes.length > 0 && (
                  <div className="col-span-2 sm:col-span-5 flex flex-wrap gap-1 pt-1 border-t border-gray-800/80">
                    {alert.evidence.reason_codes.map((rc: string, idx: number) => (
                      <span key={idx} className="text-[11px] font-mono bg-blue-950/50 text-blue-300 border border-blue-800/40 px-1.5 py-0.5 rounded">{rc}</span>
                    ))}
                  </div>
                )}
              </div>
            )}
            {(alert.evidence?.matched_terms?.length ?? 0) > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {alert.evidence.matched_terms.map((t, i) => (
                  <span key={i} className="text-xs bg-gray-900 border border-gray-700 text-orange-300 px-2 py-0.5 rounded font-mono" title={`weight: ${t.weight} | ${t.lexicon}`}>
                    {t.term}
                  </span>
                ))}
              </div>
            )}
          </Section>
        )}

        {onDispositionSet && (
          <Section title="Set disposition">
            <DispositionControls
              targetType="alert"
              targetId={alert.id}
              currentDisposition={alert.disposition || null}
              onDispositionSet={(newDisp) => onDispositionSet(alert.id, newDisp)}
            />
          </Section>
        )}
      </div>
    </div>
  );
}
