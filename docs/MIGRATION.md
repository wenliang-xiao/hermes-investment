# Architecture Migration v3.x → v4.0

## Summary

Refactored from a flat 25-file monolith to a plugin-oriented 5-layer architecture.
All existing functionality is preserved. All old entry points still work unchanged.

## New Directory Structure

```
hermes-investment/
├── core/               # Base classes, canonical data models, credentials
│   ├── __init__.py     # AssetSnapshot, MacroState, ResearchContext, AnalysisResult, ReportDocument
│   └── secrets.py      # Credentials (JQData, Tushare, Feishu) — reads env vars, falls back to defaults
├── data/               # Data source abstraction
│   └── __init__.py     # DataSource ABC (base class for all data sources)
├── analysis/           # Analysis module abstraction
│   └── __init__.py     # AnalysisModule ABC (base class for all analysis modules)
├── domain/             # Pure data: watchlists, chains, themes — NO business logic
│   └── __init__.py     # All data dicts from config.py (WATCHLIST, INDUSTRY_CHAINS, etc.)
├── output/             # Output abstraction
│   └── __init__.py     # get_feishu_writer(), create_report_doc()
├── scripts/
│   ├── run_daily.py    # Canonical daily brief (08:30 + 18:00 weekdays)
│   ├── run_weekly.py   # Canonical weekly deep research (Sun 18:00)
│   ├── run_research.py # On-demand stock research (delegates to deep_research.py)
│   ├── deep_research.py          # Deep research engine
│   ├── stock_analyzer.py         # Stock analysis library
│   ├── portfolio_monitor.py      # Portfolio tracking library
│   ├── verify_stock_codes.py     # Stock code integrity checker
│   └── physical_ai_search.py     # One-off baostock search tool
└── [all existing files unchanged]

> **v5.6**: Removed legacy scripts (run_brief, run_detail, run_report_v7, run_report_v8,
> run_weekly_fast, run_weekly_lite, morning_brief) — all superseded by run_daily.py / run_weekly.py.
```

## Entry Point Changes (v5.6 — cleanup)

Legacy wrappers (`run_brief.py`, `run_detail.py`) and deprecated scripts (`run_report_v7.py`,
`run_report_v8.py`, `run_weekly_fast.py`, `run_weekly_lite.py`, `morning_brief.py`) have
been removed. Use the canonical entry points directly:

| Use Case | Command |
|---|---|
| Daily report (08:30 + 18:00) | `python scripts/run_daily.py` |
| Weekly report (Sun 18:00) | `python scripts/run_weekly.py` |
| On-demand deep research | `python scripts/run_research.py --symbol <code>` |

## Hermes YAML Skill File Updates

Update your Hermes skill YAML files to use the canonical entry points:

```yaml
# Daily morning (weekdays 08:30)
command: python /home/admin/.hermes/investment_system/scripts/run_daily.py

# Daily evening (weekdays 18:00)
command: python /home/admin/.hermes/investment_system/scripts/run_daily.py

# Weekly (Sunday 18:00)
command: python /home/admin/.hermes/investment_system/scripts/run_weekly.py

# Deep research (on-demand)
command: python /home/admin/.hermes/investment_system/scripts/run_research.py --symbol {{symbol}}
```

Ensure only ONE set of YAML skill files exists on ECS — no duplicate cron entries.

## What's in domain/__init__.py

All pure data dictionaries from `config.py` are mirrored here:

| Variable | Description |
|---|---|
| `WATCHLIST` | 83 stocks across A/HK/US/ETF/bonds/gold |
| `INDUSTRY_CHAINS` | 12 chains with full LDS/Perez/Nick analysis |
| `OPPORTUNITY_THEMES` | 11 opportunity themes with bottleneck logic |
| `MACRO_SECTOR_ROTATION` | Sector rotation by macro regime |
| `DOMESTIC_SUB_THEMES` | 7 national substitution themes |
| `FX_PAIRS`, `BOND_MARKETS`, `GLOBAL_INDICES` | Market coverage config |
| `HK_WATCHLIST`, `US_WATCHLIST`, `A_SHARE_ETF_WATCHLIST` | Asset universe |
| `REAL_ESTATE_WATCHLIST`, `COMMODITIES` | Full asset coverage |
| `MACRO_THRESHOLDS`, `FACTOR_WEIGHTS`, `CPI_STRATEGY_MAP`, `TREND_TEMP` | Strategy params |
| `RISK_PARAMS`, `LDS_STOCK_FILTERS` | Risk and screening params |
| `NEWS_SOURCES`, `NORTHBOUND_CONFIG`, `CACHE_TTL` | System config |

These remain in `config.py` as well. New code should import from `domain/`; old code continues to work via `config`.

## What's in core/secrets.py

Credentials that were previously hardcoded in `config.py` are now also accessible via `core/secrets.py`, which respects environment variables first:

```bash
export JQDATA_USER="18813017039"
export JQDATA_PASS="your_password"
export TUSHARE_TOKEN="your_token"
export FEISHU_FOLDER_TOKEN="your_folder_token"
```

The `config.py` inline definitions remain unchanged for backward compatibility.

## Preserved Files (nothing deleted, nothing modified)

Every existing file is untouched:
`config.py`, `report_v6.py`, `deep_research.py`, `macro_engine.py`, `factor_scanner.py`,
`full_asset_scanner.py`, `data_layer.py`, `tushare_layer.py`, `jqdata_layer.py`,
`data_source_layer.py`, `multi_asset_engine.py`, `news_engine.py`, `fund_tracker.py`,
`universe_builder.py`, `yf_data_layer.py`, `morning_brief.py`, `shadow_account.py`,
`portfolio_monitor.py`, `stock_analyzer.py`, `stock_universe.py`, `global_universe.py`,
`concept_engine.py`, `etf_data.py`, `global_data.py`, `news_fetcher.py`

## Design Rationale

The 5-layer design follows Oracle's recommendation for a plugin-oriented monolith:

1. **core/** — Stable contracts. Canonical data models that don't change often.
2. **data/** — Data source plugins. Each source is a module implementing `DataSource`.
3. **analysis/** — Analysis plugins. Each module implements `AnalysisModule`.
4. **domain/** — Pure data. No imports, no business logic. Just dictionaries.
5. **output/** — Output abstraction. Decouples report generation from Feishu API details.

The existing files (report_v6, macro_engine, etc.) are the concrete implementations of layers 2-5. The new `core/`, `data/`, `analysis/`, `domain/`, `output/` packages provide the stable base classes and extracted data they can evolve toward without breaking anything today.
