from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    TELEGRAM_API_ID: int = Field(..., description="From my.telegram.org/apps")
    TELEGRAM_API_HASH: str = Field(..., description="From my.telegram.org/apps")
    TELEGRAM_PHONE: Optional[str] = Field(None)
    TELEGRAM_SESSION_FILE: str = "monitor_session"
    DATABASE_URL: str = "sqlite+aiosqlite:///./tele_monitor.db"
    SECRET_KEY: str = "changeme"
    MODEL_PATH: str = "../data/models/classifier.joblib"
    POLL_INTERVAL_SECONDS: int = 60
    HIGH_RISK_THRESHOLD: float = 0.75
    MEDIUM_RISK_THRESHOLD: float = 0.45
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    DRUG_LEXICON_PATH: str = "../data/lexicons/drug_slang.json"
    FINANCIAL_LEXICON_PATH: str = "../data/lexicons/financial_crime_slang.json"
    ARMS_LEXICON_PATH: str = "../data/lexicons/arms_slang.json"
    SCAM_LEXICON_PATH: str = "../data/lexicons/scam_slang.json"
    EXTENDED_LEXICON_PATH: str = "../data/lexicons/extended_crime_slang.json"
    DISCOVERY_ENABLED: bool = True
    TESTING: bool = False
    DISABLE_BACKGROUND_TASKS: bool = False
    DISCOVERY_PROFILE: str = "illegal_trade"
    DISCOVERY_INTERVAL_SECONDS: int = 3600
    DISCOVERY_MAX_RESULTS_PER_QUERY: int = 20
    DISCOVERY_MIN_SCORE_TO_ADD: float = 0.65
    DISCOVERY_MIN_MESSAGES_TO_SCORE: int = 20

    # Poll tier intervals (seconds)
    POLL_INTERVAL_HIGH: int = 30
    POLL_INTERVAL_MEDIUM: int = 60
    POLL_INTERVAL_LOW: int = 300

    # FloodWait / backoff
    MIN_BACKOFF: int = 10
    BACKOFF_MULTIPLIER: float = 2.0
    MAX_RETRY_COUNT: int = 5

    # Error state management
    ERROR_STATE_WINDOW_HOURS: int = 24
    ERROR_STATE_THRESHOLD: int = 3

    # Scheduler concurrency and timing
    COLLECTOR_MAX_CONCURRENT: int = 3
    COLLECTOR_SCHEDULER_INTERVAL: int = 10   # seconds between scheduler ticks

    # Error / FloodWait backoff
    MAX_BACKOFF_SECONDS: int = 3600          # cap for FloodWait next_poll_at offset
    ERROR_BACKOFF_SECONDS: int = 3600        # next_poll_at offset after error_state

    # Composite scoring caps
    COMPOSITE_HIGH_MSG_CAP: int = 10
    COMPOSITE_INCIDENT_CAP: int = 5
    COMPOSITE_PIVOT_CAP: int = 5

    # Scan quality gates
    # Minimum score for a channel-level result to be considered HIGH risk
    SCAN_HIGH_RISK_MIN_SCORE: float = 0.55
    # Minimum score for MEDIUM risk
    SCAN_MEDIUM_RISK_MIN_SCORE: float = 0.40
    # Minimum HIGH-scored messages before auto-adding to watchlist
    SCAN_AUTO_ADD_MIN_HIGH_MSGS: int = 3
    # Minimum composite score for auto-watchlist promotion
    SCAN_AUTO_ADD_MIN_COMPOSITE: float = 0.55
    # Default scan mode: "auto" (auto-add) or "review" (analyst reviews)
    SCAN_DEFAULT_MODE: str = "review"

    # Analyst review & evaluation
    MIN_REVIEWED_FOR_METRIC: int = 20

    # Stage 3: Intent-aware explainable scoring weights
    SCORING_VERSION: str = "intent_v3"
    SCORE_CATEGORY_WEIGHT: float = 0.55
    SCORE_INTENT_WEIGHT: float = 0.25
    SCORE_CONTACT_WEIGHT: float = 0.20
    SCORE_NEGATIVE_PENALTY: float = 0.35
    SCORE_KEYWORD_ONLY_CAP: float = 0.65
    USE_ML_SCORING: bool = False
    SCORE_LEXICON_WEIGHT: float = 0.70
    SCORE_ML_WEIGHT: float = 0.30

    # Stage 4: Retention & Access Control
    RETENTION_DAYS_RAW_TEXT: int = 90
    RETENTION_DAYS_MEDIA: int = 30
    RETENTION_DAYS_OCR_TEXT: int = 90
    RETENTION_DAYS_EXPORTS: int = 30
    API_ACCESS_TOKEN: Optional[str] = None
    IMPORT_MEDIA_ROOT: str = "./import_media"
    RECLASSIFICATION_HEARTBEAT_TIMEOUT_SECONDS: int = 120

    # Stage 5 (P1): MinHash / LSH near-duplicate detection
    MINHASH_SIMILARITY_THRESHOLD: float = 0.7
    MINHASH_NUM_PERM: int = 128
    MINHASH_MIN_WORDS: int = 5

settings = Settings()
