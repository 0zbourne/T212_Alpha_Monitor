# T212 Alpha Monitor

A high-signal investment intelligence dashboard designed for quality investors. This "Ultra-Lean" MVP prioritizes core portfolio health and relative performance over feature bloat, providing professional-grade insights into weight-adjusted quality benchmarks.

## 🚀 Key Features

- **Quality Benchmarking**: Real-time weighted portfolio metrics including ROCE, Gross/Operating Margins, Cash Conversion, and Interest Cover (uncapped).
- **Asset Quality Audit**: An integrated audit table that aligns capital allocation with underlying company fundamentals.
- **Relative Performance (TWR)**: Time-Weighted Return (TWR) indexing against the S&P 500 (converted to GBP) to track true alpha.
- **Modular Data Engine**: Cleanly separated background jobs for fundamental indexing, historical backfills, and daily snapshots.

## 🛡️ Privacy & Security

This repository is built with a **Privacy-First** architecture:
- **Local Data Handling**: All transaction history, portfolio holdings, and fundamental caches are stored locally in the `data/` directory.
- **Git-Ignored**: The source code is strictly decoupled from your private financial data. No personal investment information is ever pushed to GitHub.

## 🛠️ Setup & Installation

### Prerequisites
- Python 3.10+
- Trading 212 API Key and Secret (Base64 Basic Auth or Apikey)

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/0zbourne/portfolio-dashboard.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure your secrets in `.streamlit/secrets.toml` or set environment variables:
   ```toml
   T212_API_KEY = "your_key"
   T212_API_SECRET = "your_secret"
   ```

### Running Locally
```bash
streamlit run app.py
```

## 🏗️ Architecture
- **`app.py`**: The "High-Signal" Streamlit interface.
- **`jobs/`**: Core logic for `fundamentals` indexing, NAV `backfill`, and daily `snapshots`.
- **`utils/`**: Modular utilities for T212 API integration and currency/FX handling.
- **`pdperf/`**: Specialized TWR and cashflow performance calculation engine.
