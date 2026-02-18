# AI Agent Wealth Builder

## Overview
Autonomous trading agent for Polymarket prediction markets. Uses OpenAI GPT-4o to estimate fair probabilities for prediction market outcomes, detects mispricings (>8% edge), and executes trades using Kelly Criterion position sizing (capped at 6%). Includes ML-based probability adjustment, security safeguards, comprehensive testing, and a console dashboard.

## Current State
- **Status**: Running in LIVE mode (Cloudflare blocks trade execution from cloud IPs)
- **Date**: February 2026
- **Features**: Trading, ML pipeline, security safeguards, testing suite, dashboard

## Architecture
```
main.py                  - Entry point, scheduled loop, test runner
src/
  models.py              - SQLAlchemy models (6 tables)
  market_fetcher.py      - Polymarket Gamma API integration
  ai_analyzer.py         - OpenAI GPT-4o probability estimation
  trade_executor.py      - py-clob-client trade execution
  agent.py               - Core agent logic, Kelly Criterion, cycle management
  security.py            - Rate limiting, audit logging, drawdown safeguard, input validation
  ml_trainer.py          - RandomForestRegressor training, prediction, model persistence
  dashboard.py           - Console dashboard (balance, trading, ML, security)
tests/
  test_kelly.py          - Kelly Criterion unit tests (10 tests)
  test_security.py       - Trade validation tests (8 tests)
  test_trade_executor.py - Trade executor tests (4 tests)
  test_backtest.py       - Backtesting simulation tests (6 tests)
models/
  fair_prob_model.pkl    - Saved ML model (created after training)
```

## Key Environment Variables
- `DATABASE_URL` - PostgreSQL connection (auto-configured by Replit)
- `DRY_RUN` - "true" (default) for simulated trades, "false" for live
- `POLYGON_PRIVATE_KEY` - Required for live trading on Polygon chain
- `CYCLE_INTERVAL_MINUTES` - Trading cycle interval (default: 10)
- `DASHBOARD_INTERVAL_MINUTES` - Dashboard display interval (default: 30)
- `MAX_DRAWDOWN_PCT` - Max drawdown % before pausing (default: 10)
- `RUN_TESTS` - Set to "true" to run pytest instead of agent

## Dependencies
- openai, py-clob-client, web3, schedule, requests, sqlalchemy, psycopg2-binary, tenacity
- pytest, scikit-learn, joblib, ratelimit

## Database Tables
- `polymarket_trades` - Trade log with market_id, side, amount, price, status
- `agent_balances` - Balance snapshots with timestamps
- `audit_logs` - Security audit trail (action, details, severity)
- `trade_history` - ML training data (features, outcomes, profits)
- `ml_model_meta` - ML model training metadata (accuracy, MAE, samples)

## Security Features
- Rate limiting: 1 call/sec for OpenAI, 2 calls/sec for Polymarket
- Drawdown safeguard: Pauses trading if >10% drawdown in 24h
- Input validation: All trade parameters checked before execution
- Audit logging: Every action logged to DB with severity levels
- Private keys: Only accessed via os.environ, never exposed

## ML Pipeline
- Logs trade features (fair_prob, market_prob, edge, kelly_fraction, side) to TradeHistory
- Retrains RandomForestRegressor daily when 50+ resolved trades exist
- ML-adjusted probabilities blend with AI estimates for better predictions
- Model persisted with joblib to models/fair_prob_model.pkl

## Scheduled Tasks
- Trading cycle: Every 10 minutes
- Dashboard: Every 30 minutes
- ML retraining: Every 24 hours

## Testing
- 28 pytest tests across 4 test files
- Run with: `python -m pytest tests/ -v` or `RUN_TESTS=true python main.py`

## User Preferences
- Uses Replit AI Integrations for OpenAI (no separate API key needed)
- Charges billed to Replit credits

## Deployment
- Designed for Always On / Reserved VM deployment
- Runs as continuous console process with scheduled cycles

## Recent Changes
- 2026-02-10: Added ML pipeline, security layer, testing suite, and dashboard
- 2026-02-10: Fixed USDC balance conversion (raw units / 1,000,000)
- 2026-02-10: Added Cloudflare detection and early trade abort
