# Market Watch

Windows desktop factor screener for **6–12 month** stock ideas. Ranks US equities using momentum, value, and quality signals built from free data sources.

Also available as a **web app** (FastAPI + HTML/CSS/JS).

## Data sources

| Source | Used for |
|--------|----------|
| **Wikipedia** | S&P 500 universe (tickers, sectors) |
| **SEC EDGAR** | CIK map + company facts (fundamentals) |
| **Yahoo Finance** (`yfinance`) | Daily prices + snapshot fundamentals |
| **Stooq** | Price fallback when Yahoo history is thin |

Data is cached locally in `data/market_watch.db`.

## Requirements

- Windows 10/11 (desktop) or any OS with Python 3.11+ (web)
- Python 3.11+ ([python.org](https://www.python.org/downloads/))

## Quick start — Web app (recommended)

Double-click **`run_web.bat`**, then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Or manually:

```powershell
cd c:\JB\GitHub\market-watch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m market_watch.web_main
```

### Web API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/picks` | Latest cached screen |
| POST | `/api/screen` | Re-rank stocks (`min_market_cap` in body) |
| POST | `/api/refresh` | Start background data download (`universe_limit` in body) |
| GET | `/api/jobs/{id}` | Poll refresh job status |
| GET | `/api/sectors/{name}` | Sector leaders |
| GET | `/api/companies/{ticker}` | Company detail |

## Quick start — Desktop app

Double-click **`run.bat`** (creates a venv, installs deps, launches the PySide6 UI).

Or manually:

```powershell
cd c:\JB\GitHub\market-watch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m market_watch
```

## How to use

1. Set **universe size** (default 100 S&P 500 names for faster first run; up to 503 for full index).
2. Click **Refresh Data** — downloads universe, ~2 years of prices, and fundamentals. First run may take several minutes.
3. Click **Run Screen** — computes factor z-scores and shows ranked picks.
4. Review **Score**, **12-1M %**, **Value Z**, **Quality Z** columns.

### Factor model (6–12 month)

- **Momentum (45%)**: 12-month return skipping last month + 6-month return
- **Value (25%)**: Earnings yield and book-to-market proxy
- **Quality (25%)**: ROE, profit margin, lower leverage
- **Low volatility (5%)**: Prefer lower 60-day annualized vol

## SEC User-Agent

Edit `SEC_USER_AGENT` in `market_watch/config.py` with your contact email per [SEC fair access](https://www.sec.gov/os/webmaster-faq#code-support).

## Disclaimer

This tool is for research and education only. It does not provide investment advice. Past factor performance does not guarantee future results.
