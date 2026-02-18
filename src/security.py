import os
import time
from datetime import datetime, timezone, timedelta

from ratelimit import limits, sleep_and_retry
from src.models import get_session, AuditLog, AgentBalance

MAX_DRAWDOWN_PCT = float(os.environ.get("MAX_DRAWDOWN_PCT", "10.0"))
DAILY_LOSS_PAUSE_HOURS = 1

_trading_paused_until = None


def audit_log(action, details="", severity="info"):
    try:
        session = get_session()
        entry = AuditLog(
            timestamp=datetime.now(timezone.utc),
            action=action,
            details=str(details)[:1000],
            severity=severity,
        )
        session.add(entry)
        session.commit()
        session.close()
        if severity in ("warning", "critical"):
            print(f"[AUDIT-{severity.upper()}] {action}: {details}")
    except Exception as e:
        print(f"[Security] Error writing audit log: {e}")


@sleep_and_retry
@limits(calls=1, period=1)
def rate_limited_openai_call(func, *args, **kwargs):
    return func(*args, **kwargs)


@sleep_and_retry
@limits(calls=2, period=1)
def rate_limited_polymarket_call(func, *args, **kwargs):
    return func(*args, **kwargs)


def check_drawdown_safeguard():
    global _trading_paused_until

    if _trading_paused_until and datetime.now(timezone.utc) < _trading_paused_until:
        remaining = (_trading_paused_until - datetime.now(timezone.utc)).seconds // 60
        return False, f"Trading paused for {remaining} more minutes due to drawdown"

    _trading_paused_until = None

    try:
        session = get_session()
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        balances = (
            session.query(AgentBalance)
            .filter(AgentBalance.timestamp >= day_ago)
            .order_by(AgentBalance.timestamp.asc())
            .all()
        )
        session.close()

        if len(balances) < 2:
            return True, "Not enough balance data for drawdown check"

        peak_balance = max(b.usdc_balance for b in balances)
        current_balance = balances[-1].usdc_balance

        if peak_balance <= 0:
            return True, "No peak balance recorded"

        drawdown_pct = ((peak_balance - current_balance) / peak_balance) * 100

        if drawdown_pct >= MAX_DRAWDOWN_PCT:
            _trading_paused_until = now + timedelta(hours=DAILY_LOSS_PAUSE_HOURS)
            audit_log(
                "drawdown_limit_hit",
                f"Drawdown: {drawdown_pct:.1f}% (peak: ${peak_balance:.2f}, current: ${current_balance:.2f}). "
                f"Trading paused for {DAILY_LOSS_PAUSE_HOURS}h.",
                severity="critical",
            )
            return False, f"Drawdown {drawdown_pct:.1f}% exceeds {MAX_DRAWDOWN_PCT}% limit"

        return True, f"Drawdown OK: {drawdown_pct:.1f}%"

    except Exception as e:
        audit_log("drawdown_check_error", str(e), severity="warning")
        return True, f"Drawdown check error: {e}"


def validate_trade_inputs(side, amount_usdc, price, fair_prob):
    errors = []

    if side not in ("buy_yes", "buy_no"):
        errors.append(f"Invalid side: {side}")

    if not (0.01 <= amount_usdc <= 10000):
        errors.append(f"Amount out of range: ${amount_usdc}")

    if not (0.001 <= price <= 0.999):
        errors.append(f"Price out of range: {price}")

    if not (0.01 <= fair_prob <= 0.99):
        errors.append(f"Fair prob out of range: {fair_prob}")

    if errors:
        audit_log("trade_validation_failed", "; ".join(errors), severity="warning")
        return False, errors

    return True, []


def get_recent_audit_logs(limit=20):
    try:
        session = get_session()
        logs = (
            session.query(AuditLog)
            .order_by(AuditLog.id.desc())
            .limit(limit)
            .all()
        )
        session.close()
        return logs
    except Exception:
        return []


def get_security_summary():
    try:
        session = get_session()
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        total_logs = session.query(AuditLog).filter(AuditLog.timestamp >= day_ago).count()
        warnings = (
            session.query(AuditLog)
            .filter(AuditLog.timestamp >= day_ago, AuditLog.severity == "warning")
            .count()
        )
        criticals = (
            session.query(AuditLog)
            .filter(AuditLog.timestamp >= day_ago, AuditLog.severity == "critical")
            .count()
        )
        session.close()

        can_trade, drawdown_msg = check_drawdown_safeguard()

        return {
            "audit_events_24h": total_logs,
            "warnings_24h": warnings,
            "criticals_24h": criticals,
            "can_trade": can_trade,
            "drawdown_status": drawdown_msg,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }
    except Exception as e:
        return {"error": str(e)}
