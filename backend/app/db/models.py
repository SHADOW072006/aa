"""
SQLAlchemy ORM models for the Telegram monitor database.

Tables
------
channels                – tracked Telegram channels / groups
messages                – raw collected messages
alerts                  – flagged messages with risk metadata
identifiers             – extracted phones, UPI IDs, handles, wallets, etc.
entity_links            – edges in the identifier co-occurrence graph
scan_jobs               – one scan run
channel_scan_results    – per-channel summary from a scan job
seed_profiles           – canonical threat search seeds
query_variants          – text variants derived from seed profiles
query_variant_executions – per-variant execution log
scan_evidence           – individual flagged messages with full evidence
pivot_candidates        – identifiers / channels worth investigating
channel_score_components – composite scoring breakdown per scan result
channel_health_events   – health / error event log per channel
disposition_history     – audit trail for disposition changes
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    member_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # --- New polling / health columns (Req 7.9, 15.3) ---
    poll_tier: Mapped[Optional[str]] = mapped_column(String(16), default="LOW", nullable=True)
    last_poll_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    consecutive_error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_state: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel_status: Mapped[Optional[str]] = mapped_column(String(16), default="active", nullable=True)
    discovery_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("query_variants.id"), nullable=True
    )
    # --- Scheduler column (Req 2.1) ---
    next_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    messages: Mapped[List["Message"]] = relationship(back_populates="channel")

    def __repr__(self) -> str:
        return f"<Channel {self.username}>"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("channel_id", "telegram_msg_id", name="uq_channel_msg"),
        Index("ix_messages_created_at", "created_at"),
        Index("ix_messages_text_hash", "text_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    telegram_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    sender_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SHA-256 of normalised text for dedup
    text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Stage 4: Evidence hashing & separate OCR fields
    original_text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    provenance_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    media_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    ocr_skip_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # MinHash signature (hex-encoded) for near-duplicate detection
    minhash_sig: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # pHash of image (hex) for image dedup
    image_phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    forwarded_from: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    # Import source: 'telegram' | 'csv_import' | 'json_import'
    source: Mapped[str] = mapped_column(String(32), default="telegram")

    channel: Mapped["Channel"] = relationship(back_populates="messages")
    alert: Mapped[Optional["Alert"]] = relationship(back_populates="message", uselist=False)
    identifiers: Mapped[List["Identifier"]] = relationship(back_populates="message")

    @staticmethod
    def compute_hash(text: str) -> str:
        normalised = " ".join(text.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True, nullable=False)
    # Risk level: HIGH | MEDIUM | LOW
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # Composite risk score 0.0 – 1.0
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # Comma-separated matched categories, e.g. "heroin,drug_sale"
    categories: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # JSON blob: {"matched_terms": [...], "matched_emojis": [...], "ml_score": 0.9}
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # --- New disposition columns (Req 5.2, 14.5) ---
    disposition: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    disposition_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disposition_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    disposition_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # --- Stage B: Alert lifecycle & legacy category preservation ---
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latest_scoring_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    legacy_categories: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    message: Mapped["Message"] = relationship(back_populates="alert")


# ---------------------------------------------------------------------------
# Identifier
# ---------------------------------------------------------------------------

class Identifier(Base):
    """
    An extracted contact / payment identifier from a message.
    type: phone | upi | handle | wallet_btc | wallet_eth | wallet_usdt | email | url
    """
    __tablename__ = "identifiers"
    __table_args__ = (
        Index("ix_identifiers_value", "value"),
        Index("ix_identifiers_type", "type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)
    # Normalised form used for entity linking
    normalised: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    message: Mapped["Message"] = relationship(back_populates="identifiers")


# ---------------------------------------------------------------------------
# EntityLink
# ---------------------------------------------------------------------------

class EntityLink(Base):
    """
    An edge in the entity co-occurrence graph.
    Two identifiers that appear in the same message (or same channel within
    a time window) are linked.  weight accumulates with each co-occurrence.
    """
    __tablename__ = "entity_links"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_entity_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("identifiers.id"), nullable=False)
    target_id: Mapped[int] = mapped_column(ForeignKey("identifiers.id"), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=func.now())


# ---------------------------------------------------------------------------
# ScanJob
# ---------------------------------------------------------------------------

class ScanJob(Base):
    """
    One scan run - searches Telegram for channels matching crime seed terms
    and classifies messages in each found channel.
    """
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seed_terms: Mapped[str] = mapped_column(Text, nullable=False)        # JSON array
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending|running|done|failed
    total_channels_found: Mapped[int] = mapped_column(Integer, default=0)
    total_channels_scanned: Mapped[int] = mapped_column(Integer, default=0)
    total_messages_scanned: Mapped[int] = mapped_column(Integer, default=0)
    total_flagged: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    results: Mapped[List["ChannelScanResult"]] = relationship(back_populates="scan_job")


# ---------------------------------------------------------------------------
# ChannelScanResult
# ---------------------------------------------------------------------------

class ChannelScanResult(Base):
    """
    Per-channel result of a ScanJob — summary of what was found in that channel.
    """
    __tablename__ = "channel_scan_results"
    __table_args__ = (Index("ix_scan_results_job_id", "scan_job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_job_id: Mapped[int] = mapped_column(ForeignKey("scan_jobs.id"), nullable=False)
    channel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    channel_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    member_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_link: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    messages_scanned: Mapped[int] = mapped_column(Integer, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float] = mapped_column(Float, default=0.0)
    top_categories: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON array
    top_identifiers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    sample_messages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    connected_nodes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON blob
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW")
    severity_tier: Mapped[str] = mapped_column(String(16), default="LOW")
    is_serious: Mapped[bool] = mapped_column(Boolean, default=False)
    seed_term: Mapped[str] = mapped_column(String(255), nullable=False)
    already_monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # --- New columns (Req 3.2, 4.1) ---
    discovered_by_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("query_variants.id"), nullable=True
    )
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    scan_job: Mapped["ScanJob"] = relationship(back_populates="results")


# ---------------------------------------------------------------------------
# SeedProfile  (Req 1.1, 2.1)
# ---------------------------------------------------------------------------

class SeedProfile(Base):
    """
    Canonical threat search seed — the authoritative definition of a search
    intent.  Many QueryVariants are derived from one SeedProfile.
    """
    __tablename__ = "seed_profiles"
    __table_args__ = (
        UniqueConstraint("seed_text_normalised", name="uq_seed_profiles_normalised"),
        Index("ix_seed_profiles_is_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seed_text: Mapped[str] = mapped_column(String(120), nullable=False)
    seed_text_normalised: Mapped[str] = mapped_column(String(120), nullable=False)
    threat_category: Mapped[str] = mapped_column(String(64), nullable=False)
    language_region: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    intent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # CHECK 1–5 enforced at application layer for SQLite/PostgreSQL compatibility
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Stage 2: profile separation, role, lifecycle, rationale, feedback stats
    profile: Mapped[str] = mapped_column(String(32), nullable=False, default="illegal_trade")
    seed_role: Mapped[str] = mapped_column(String(32), nullable=False, default="indicator")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    catalogue_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_fp_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # one of: manual | analyst_promoted | entity_pivot | default
    created_source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    variants: Mapped[List["QueryVariant"]] = relationship(back_populates="seed_profile")


# ---------------------------------------------------------------------------
# QueryVariant  (Req 1.1, 2.1)
# ---------------------------------------------------------------------------

class QueryVariant(Base):
    """
    A specific text variant derived from a SeedProfile — e.g. spacing variant,
    transliteration, hyphen variant, etc.
    """
    __tablename__ = "query_variants"
    __table_args__ = (
        UniqueConstraint("variant_text", name="uq_query_variants_variant_text"),
        Index("ix_query_variants_seed_profile_id", "seed_profile_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seed_profile_id: Mapped[int] = mapped_column(
        ForeignKey("seed_profiles.id"), nullable=False
    )
    variant_text: Mapped[str] = mapped_column(String(120), nullable=False)
    # spacing | hyphen | transliteration_to_latin | transliteration_to_devanagari
    variant_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )



    seed_profile: Mapped["SeedProfile"] = relationship(back_populates="variants")
    executions: Mapped[List["QueryVariantExecution"]] = relationship(
        back_populates="query_variant"
    )


# ---------------------------------------------------------------------------
# QueryVariantExecution  (Req 2.1)
# ---------------------------------------------------------------------------

class QueryVariantExecution(Base):
    """
    Log of each time a QueryVariant was executed as part of a ScanJob.
    """
    __tablename__ = "query_variant_executions"
    __table_args__ = (
        Index("ix_qve_variant_id", "query_variant_id"),
        Index("ix_qve_scan_job_id", "scan_job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_variant_id: Mapped[int] = mapped_column(
        ForeignKey("query_variants.id"), nullable=False
    )
    scan_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scan_jobs.id"), nullable=True
    )
    execution_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    channels_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channels_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    query_variant: Mapped["QueryVariant"] = relationship(back_populates="executions")


# ---------------------------------------------------------------------------
# ScanEvidence  (Req 3.2)
# ---------------------------------------------------------------------------

class ScanEvidence(Base):
    """
    Individual flagged message with full evidence payload, produced during a
    scan job.  One row per (channel, telegram_message_id) pair.
    """
    __tablename__ = "scan_evidence"
    __table_args__ = (
        UniqueConstraint(
            "channel_username", "telegram_message_id",
            name="uq_scan_evidence_channel_msg",
        ),
        Index("ix_scan_evidence_scan_job_id", "scan_job_id"),
        Index("ix_scan_evidence_channel_username", "channel_username"),
        Index("ix_scan_evidence_risk_level", "risk_level"),
        Index("ix_scan_evidence_last_classified_at", "last_classified_at"),
        Index("ix_scan_evidence_disposition", "disposition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_job_id: Mapped[int] = mapped_column(ForeignKey("scan_jobs.id"), nullable=False)
    channel_scan_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("channel_scan_results.id"), nullable=True
    )
    channel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalised_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    classifier_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    severity_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    # JSON arrays stored as Text for SQLite + PostgreSQL compatibility
    categories: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_identifiers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seed_term: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    query_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("query_variants.id"), nullable=True
    )
    media_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    ocr_success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ocr_skip_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_classified_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    disposition: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    disposition_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disposition_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    disposition_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# PivotCandidate  (Req 4.1)
# ---------------------------------------------------------------------------

class PivotCandidate(Base):
    """
    An identifier or channel handle extracted from evidence that may warrant
    pivoting to a new investigation thread.
    """
    __tablename__ = "pivot_candidates"
    __table_args__ = (
        UniqueConstraint(
            "candidate_value", "source_channel_username",
            name="uq_pivot_candidates_value_channel",
        ),
        Index("ix_pivot_candidates_status", "status"),
        Index("ix_pivot_candidates_source_channel", "source_channel_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_channel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    source_scan_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("channel_scan_results.id"), nullable=True
    )
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_value: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    evaluated_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# ChannelScoreComponents  (Req 4.1, 17.1)
# ---------------------------------------------------------------------------

class ChannelScoreComponents(Base):
    """
    Detailed scoring breakdown for a single ChannelScanResult.
    One-to-one with channel_scan_results.
    """
    __tablename__ = "channel_score_components"
    __table_args__ = (
        UniqueConstraint(
            "channel_scan_result_id",
            name="uq_channel_score_components_result_id",
        ),
        Index("ix_channel_score_components_result_id", "channel_scan_result_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_scan_result_id: Mapped[int] = mapped_column(
        ForeignKey("channel_scan_results.id"), nullable=False
    )
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    max_message_score: Mapped[float] = mapped_column(Float, nullable=False)
    high_confidence_message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_incident_count: Mapped[int] = mapped_column(Integer, nullable=False)
    recency_weight: Mapped[float] = mapped_column(Float, nullable=False)
    identifier_density: Mapped[float] = mapped_column(Float, nullable=False)
    valid_pivot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    analyst_confirmation_signal: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# ChannelHealthEvent  (Req 7.9, 15.3)
# ---------------------------------------------------------------------------

class ChannelHealthEvent(Base):
    """
    Event log for channel health changes — errors, rate-limit hits, bans, etc.
    """
    __tablename__ = "channel_health_events"
    __table_args__ = (
        Index(
            "ix_channel_health_channel_id_occurred_at",
            "channel_id", "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# DispositionHistory  (Req 5.2, 14.5)
# ---------------------------------------------------------------------------

class DispositionHistory(Base):
    """
    Immutable audit trail recording every change to a disposition field on any
    target object (alert, scan_evidence, pivot_candidate, etc.).
    """
    __tablename__ = "disposition_history"
    __table_args__ = (
        Index("ix_disposition_history_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_disposition: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    new_disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# EvidenceMessage  (Req 6)
# ---------------------------------------------------------------------------

class EvidenceMessage(Base):
    """
    Canonical per-Telegram-message forensic record.
    One row per real Telegram message, ever — never deleted or overwritten.

    Unique on (channel_username, telegram_message_id).
    Disposition fields live here so they survive re-scans.
    """
    __tablename__ = "evidence_messages"
    __table_args__ = (
        UniqueConstraint(
            "channel_username", "telegram_message_id",
            name="uq_evidence_messages_channel_msgid",
        ),
        Index("ix_evidence_messages_channel", "channel_username"),
        Index("ix_evidence_messages_first_seen", "first_seen_at"),
        Index("ix_evidence_messages_disposition", "disposition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caption_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    normalised_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_identifiers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    media_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_text_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    provenance_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # ocr_outcome: not_applicable | skipped | success | failed
    ocr_outcome: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    ocr_skip_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Disposition — stored here so it survives re-scans
    disposition: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    disposition_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disposition_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    disposition_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    observations: Mapped[List["EvidenceObservation"]] = relationship(
        back_populates="evidence_message",
        order_by="EvidenceObservation.classified_at.desc()",
    )


# ---------------------------------------------------------------------------
# EvidenceObservation  (Req 7)
# ---------------------------------------------------------------------------

class EvidenceObservation(Base):
    """
    One row per time an EvidenceMessage was classified/processed.
    Always INSERT — never overwrite an existing observation.

    source_type values:
        scheduled_scan | discovery | pivot | manual | continuous_monitor
    """
    __tablename__ = "evidence_observations"
    __table_args__ = (
        Index("ix_evidence_obs_message_id", "evidence_message_id"),
        Index("ix_evidence_obs_scan_job_id", "scan_job_id"),
        Index("ix_evidence_obs_risk_level", "risk_level"),
        Index("ix_evidence_obs_classified_at", "classified_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_message_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_messages.id"), nullable=False
    )
    scan_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("scan_jobs.id"), nullable=True
    )
    channel_scan_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("channel_scan_results.id"), nullable=True
    )
    seed_profile_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("seed_profiles.id"), nullable=True
    )
    query_variant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("query_variants.id"), nullable=True
    )
    # scheduled_scan | discovery | pivot | manual | continuous_monitor
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    classifier_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="lexicon_v1"
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    severity_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    categories: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    matched_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    observation_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    import_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    evidence_message: Mapped["EvidenceMessage"] = relationship(
        back_populates="observations"
    )


# ---------------------------------------------------------------------------
# AnalystReview
# ---------------------------------------------------------------------------

class AnalystReview(Base):
    """
    Analyst review of an automatically generated alert or evidence record.

    Stores structured labelling (label, category, intent), provenance
    (reviewed_by, reviewed_at), and optional notes.

    target_type: 'alert' | 'evidence_message'
    target_id:   primary key in the respective table

    label values:
        confirmed_relevant | false_positive | benign_or_news |
        needs_review | uncertain

    category values (illegal-trade scope):
        drugs | arms | fake_documents | mule_accounts |
        cards | sim_cards | other | benign

    intent values:
        sale_or_supply | rental_or_recruitment | discussion_or_news |
        prevention_or_awareness | unrelated | unknown
    """
    __tablename__ = "analyst_reviews"
    __table_args__ = (
        UniqueConstraint(
            "target_type", "target_id",
            name="uq_analyst_review_target",
        ),
        Index("ix_analyst_reviews_target", "target_type", "target_id"),
        Index("ix_analyst_reviews_reviewed_at", "reviewed_at"),
        Index("ix_analyst_reviews_label", "label"),
        Index("ix_analyst_reviews_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Classifier state at time of review — for drift tracking
    classifier_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classifier_risk_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Stratified sampling stratum (for non-flagged evaluation sample)
    sampling_stratum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class AnalystReviewHistory(Base):
    """
    Append-only history of every analyst label submission/update.
    Evidence is never modified.
    """
    __tablename__ = "analyst_review_history"
    __table_args__ = (
        Index("ix_arh_target", "target_type", "target_id"),
        Index("ix_arh_reviewed_at", "reviewed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("analyst_reviews.id"), nullable=True
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sampling_stratum: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    classifier_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    classifier_risk_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class AuditLog(Base):
    """
    Append-only security & governance audit trail.
    Stores actor, action, target ID/hash, and non-text metadata only.
    """
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    record_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )




class ImportBatch(Base):
    """Tracks CSV/JSON import batches for deduplication and operational monitoring."""
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class ReclassificationJob(Base):
    """Tracks resumable batch reclassification runs without losing prior observations."""
    __tablename__ = "reclassification_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scoring_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_processed_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_risk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_category_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    newly_flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_longer_flagged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_by: Mapped[str] = mapped_column(String(128), nullable=False)
    worker_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
