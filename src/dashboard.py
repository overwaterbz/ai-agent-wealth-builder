from datetime import datetime, timezone, timedelta

from src.models import get_session, PolymarketTrade, AgentBalance, TradeHistory
from src.security import get_security_summary, get_recent_audit_logs
from src.ml_trainer import get_model_stats


def print_dashboard():
    print("\n" + "=" * 70)
    print("  AI AGENT WEALTH BUILDER - DASHBOARD")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    _print_balance_section()
    _print_trading_section()
    _print_ml_section()
    _print_security_section()

    print("=" * 70)


def _print_balance_section():
    try:
        session = get_session()
        latest = (
            session.query(AgentBalance)
            .order_by(AgentBalance.id.desc())
            .first()
        )

        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        day_start = (
            session.query(AgentBalance)
            .filter(AgentBalance.timestamp >= day_ago)
            .order_by(AgentBalance.timestamp.asc())
            .first()
        )
        session.close()

        print("\n-- BALANCE --")
        if latest:
            print(f"  Current:  ${latest.usdc_balance:.2f} USDC")
            if day_start:
                change = latest.usdc_balance - day_start.usdc_balance
                pct = (change / day_start.usdc_balance * 100) if day_start.usdc_balance > 0 else 0
                direction = "+" if change >= 0 else ""
                print(f"  24h:      {direction}${change:.2f} ({direction}{pct:.1f}%)")
        else:
            print("  No balance data yet")
    except Exception as e:
        print(f"  Balance error: {e}")


def _print_trading_section():
    try:
        session = get_session()
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)

        total_trades = (
            session.query(PolymarketTrade)
            .filter(PolymarketTrade.timestamp >= day_ago)
            .count()
        )

        successful = (
            session.query(PolymarketTrade)
            .filter(
                PolymarketTrade.timestamp >= day_ago,
                PolymarketTrade.status.in_(["submitted", "dry_run"]),
            )
            .count()
        )

        errors = (
            session.query(PolymarketTrade)
            .filter(
                PolymarketTrade.timestamp >= day_ago,
                PolymarketTrade.status.like("error%"),
            )
            .count()
        )

        recent = (
            session.query(PolymarketTrade)
            .order_by(PolymarketTrade.id.desc())
            .limit(5)
            .all()
        )
        session.close()

        print("\n-- TRADING (24h) --")
        print(f"  Total:      {total_trades}")
        print(f"  Successful: {successful}")
        print(f"  Errors:     {errors}")

        if recent:
            print("  Recent:")
            for t in reversed(recent):
                status_short = t.status[:15]
                print(
                    f"    {t.timestamp.strftime('%H:%M')} | {t.side:8s} | "
                    f"${t.amount_usdc:7.2f} @ {t.price:.3f} | {status_short}"
                )
    except Exception as e:
        print(f"  Trading error: {e}")


def _print_ml_section():
    try:
        stats = get_model_stats()

        print("\n-- ML MODEL --")
        if stats.get("model_loaded") or stats.get("model_exists"):
            print(f"  Status:     {'Loaded' if stats.get('model_loaded') else 'Saved (not loaded)'}")
            if stats.get("last_accuracy"):
                print(f"  Accuracy:   {stats['last_accuracy']:.4f}")
            if stats.get("last_mae"):
                print(f"  MAE:        {stats['last_mae']:.4f}")
            if stats.get("last_trained"):
                print(f"  Trained:    {stats['last_trained']}")
            if stats.get("last_n_samples"):
                print(f"  Samples:    {stats['last_n_samples']}")
        else:
            print(f"  Status:     Not trained yet")
            print(f"  Resolved:   {stats.get('resolved_trades', 0)}/{stats.get('min_samples', 50)} needed")

        print(f"  Logged:     {stats.get('total_trades_logged', 0)} trades")
        print(f"  Unresolved: {stats.get('unresolved_trades', 0)}")
    except Exception as e:
        print(f"  ML error: {e}")


def _print_security_section():
    try:
        summary = get_security_summary()

        print("\n-- SECURITY --")
        print(f"  Drawdown:   {summary.get('drawdown_status', 'N/A')}")
        print(f"  Can trade:  {'Yes' if summary.get('can_trade') else 'NO - PAUSED'}")
        print(f"  Max DD:     {summary.get('max_drawdown_pct', 10)}%")
        print(f"  Events 24h: {summary.get('audit_events_24h', 0)} "
              f"(W:{summary.get('warnings_24h', 0)} C:{summary.get('criticals_24h', 0)})")

        logs = get_recent_audit_logs(3)
        if logs:
            print("  Recent:")
            for log in logs:
                sev = log.severity[0].upper()
                print(f"    [{sev}] {log.timestamp.strftime('%H:%M')} {log.action}: {(log.details or '')[:50]}")
    except Exception as e:
        print(f"  Security error: {e}")
