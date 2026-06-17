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

# Default universe: S&P 100-ish for reasonable free-tier fetch times.
# User can refresh full S&P 500 from the UI.
DEFAULT_UNIVERSE = "sp500"
MAX_TICKERS_FULL_SP500 = 503

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
