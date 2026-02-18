"""
AI Agent Wealth Builder
=======================
Autonomous trading agent for Polymarket prediction markets.
Uses OpenAI to estimate fair probabilities and Kelly Criterion for position sizing.
Includes ML-based probability adjustment, security safeguards, and comprehensive testing.

Configuration via environment variables:
  - DATABASE_URL: PostgreSQL connection string
  - DRY_RUN: "true" (default) to simulate trades, "false" for live trading
  - POLYGON_PRIVATE_KEY: Private key for Polygon chain (required for live trading)
  - MAX_DRAWDOWN_PCT: Max drawdown percentage before pausing (default: 10)

Extensible: swap AI provider (e.g., Claude), add multi-agent strategies,
or connect additional prediction market APIs.
"""

import os
import time
import schedule

from src.models import init_db
from src.agent import run_trading_cycle
from src.trade_executor import DRY_RUN
from src.ml_trainer import should_retrain, train_model, load_model
from src.dashboard import print_dashboard
from src.security import audit_log

CYCLE_INTERVAL_MINUTES = int(os.environ.get("CYCLE_INTERVAL_MINUTES", "10"))
DASHBOARD_INTERVAL_MINUTES = int(os.environ.get("DASHBOARD_INTERVAL_MINUTES", "30"))


def main():
    print("=" * 70)
    print("  AI AGENT WEALTH BUILDER")
    print("  Autonomous Polymarket Trading Agent")
    print("=" * 70)
    print(f"  Mode:     {'DRY RUN (simulated)' if DRY_RUN else 'LIVE TRADING'}")
    print(f"  Interval: Every {CYCLE_INTERVAL_MINUTES} minutes")
    print(f"  Database: Connected via DATABASE_URL")
    print(f"  ML:       Enabled (retrain daily when 50+ samples)")
    print(f"  Security: Drawdown limit, rate limiting, audit logging")
    print("=" * 70)
    print()

    print("[Setup] Initializing database tables...")
    init_db()
    print("[Setup] Database ready")

    load_model()
    audit_log("agent_start", f"Mode: {'DRY_RUN' if DRY_RUN else 'LIVE'}, Interval: {CYCLE_INTERVAL_MINUTES}m")

    print("[Agent] Running initial trading cycle...")
    try:
        run_trading_cycle()
    except Exception as e:
        print(f"[Agent] Error in initial cycle: {e}")
        audit_log("cycle_error", str(e), severity="warning")

    schedule.every(CYCLE_INTERVAL_MINUTES).minutes.do(safe_run_cycle)
    schedule.every(24).hours.do(safe_retrain)
    schedule.every(DASHBOARD_INTERVAL_MINUTES).minutes.do(safe_dashboard)

    print(f"\n[Agent] Scheduled: trading every {CYCLE_INTERVAL_MINUTES}m, "
          f"dashboard every {DASHBOARD_INTERVAL_MINUTES}m, ML retrain every 24h")
    print("[Agent] Waiting...")

    while True:
        schedule.run_pending()
        time.sleep(30)


def safe_run_cycle():
    try:
        run_trading_cycle()
    except Exception as e:
        print(f"[Agent] Error in trading cycle: {e}")
        audit_log("cycle_error", str(e), severity="warning")
        print("[Agent] Will retry next scheduled cycle")


def safe_retrain():
    try:
        if should_retrain():
            print("\n[ML] Starting scheduled model retraining...")
            audit_log("ml_retrain_start", "Scheduled daily retrain")
            model = train_model()
            if model:
                audit_log("ml_retrain_success", "Model retrained successfully")
            else:
                audit_log("ml_retrain_skip", "Not enough data to retrain")
        else:
            print("[ML] Not enough resolved trades to retrain")
    except Exception as e:
        print(f"[ML] Error in retraining: {e}")
        audit_log("ml_retrain_error", str(e), severity="warning")


def safe_dashboard():
    try:
        print_dashboard()
    except Exception as e:
        print(f"[Dashboard] Error: {e}")


def run_tests():
    import subprocess
    print("\n[Testing] Running pytest suite...")
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    return result.returncode == 0


if __name__ == "__main__":
    if os.environ.get("RUN_TESTS") == "true":
        success = run_tests()
        exit(0 if success else 1)
    else:
        main()
