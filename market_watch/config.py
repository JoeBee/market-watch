"""Application configuration."""
from pathlib import Path

APP_NAME = "Market Watch"
APP_VERSION = "1.0.0"

# Project paths
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "market_watch.db"

# SEC EDGAR requires a descriptive User-Agent (no generic bots).
SEC_USER_AGENT = "MarketWatch/1.0 (personal research tool; contact@example.com)"

# Default universe size for refresh (smaller = faster downloads).
DEFAULT_UNIVERSE_LIMIT = 50
MAX_TICKERS_FULL_SP500 = 503

# Price history: ~400 calendar days covers 12-1 momentum (252 + 21 trading days).
PRICE_HISTORY_CALENDAR_DAYS = 400
PRICE_BATCH_SIZE = 100

# Fundamentals: parallel Yahoo Finance lookups (SEC enrichment is slow and optional).
FUNDAMENTALS_MAX_WORKERS = 10
USE_SEC_ENRICHMENT = False
USE_STOOQ_FALLBACK = False

# Factor weights for 6–12 month composite (sum ≈ 1.0)
WEIGHT_MOMENTUM_12_1 = 0.30
WEIGHT_MOMENTUM_6M = 0.15
WEIGHT_VALUE = 0.25
WEIGHT_QUALITY = 0.25
WEIGHT_LOW_VOL = 0.05

# Minimum history (trading days) required for momentum
MIN_PRICE_HISTORY_DAYS = 252

# Stooq uses .us suffix for US equities
STOOQ_SUFFIX = ".us"

# UI typography (points)
UI_FONT_FAMILY = "Segoe UI"
UI_FONT_SIZE = 14
UI_FONT_SIZE_TITLE = 20
UI_FONT_SIZE_GUIDE = 14
UI_FONT_SIZE_DISCLAIMER = 13
UI_TABLE_FONT_SIZE = 14
UI_TABLE_ROW_HEIGHT = 36
