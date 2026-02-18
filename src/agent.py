import time
from datetime import datetime, timezone

from src.models import get_session, PolymarketTrade, AgentBalance
from src.market_fetcher import fetch_active_markets
from src.ai_analyzer import estimate_fair_probability, get_total_cost
from src.trade_executor import execute_trade, get_usdc_balance, DRY_RUN
from src.security import (
    audit_log, check_drawdown_safeguard, validate_trade_inputs
)
from src.ml_trainer import (
    log_trade_for_ml, predict_adjusted_prob, should_retrain, train_model
)

MISPRICING_THRESHOLD = 0.08
MAX_KELLY_FRACTION = 0.06
MIN_TRADE_AMOUNT = 1.0
MIN_BALANCE_THRESHOLD = 10.0
MAX_MARKETS_TO_ANALYZE = 50


def run_trading_cycle():
    print("\n" + "=" * 70)
    print(f"[Agent] Starting trading cycle at {datetime.now(timezone.utc).isoformat()}")
    print(f"[Agent] Mode: {'DRY RUN' if DRY_RUN else 'LIVE TRADING'}")
    print("=" * 70)

    audit_log("cycle_start", f"Mode: {'DRY_RUN' if DRY_RUN else 'LIVE'}")

    can_trade, drawdown_msg = check_drawdown_safeguard()
    if not can_trade:
        print(f"[Agent] {drawdown_msg}")
        audit_log("cycle_skipped", drawdown_msg, severity="warning")
        return

    balance = get_usdc_balance()
    log_balance(balance, "Cycle start")
    print(f"[Agent] Current USDC balance: ${balance:.2f}")

    if balance < MIN_BALANCE_THRESHOLD:
        print(f"[Agent] Agent pausing - low balance (${balance:.2f} < ${MIN_BALANCE_THRESHOLD})")
        log_balance(balance, "Agent pausing - low balance")
        audit_log("low_balance", f"${balance:.2f}", severity="warning")
        return

    markets = fetch_active_markets(limit=100, max_markets=500)
    if not markets:
        print("[Agent] No markets fetched, skipping cycle")
        audit_log("no_markets", "Market fetch returned empty")
        return

    markets_to_analyze = markets[:MAX_MARKETS_TO_ANALYZE]
    print(f"[Agent] Analyzing {len(markets_to_analyze)} markets with AI...")

    opportunities = []
    for i, market in enumerate(markets_to_analyze):
        try:
            fair_prob = estimate_fair_probability(market["question"])
            if fair_prob is None:
                continue

            ml_adjusted = predict_adjusted_prob(
                fair_prob=fair_prob,
                market_prob=market["yes_price"],
                edge=abs(fair_prob - market["yes_price"]),
                kelly_fraction=MAX_KELLY_FRACTION,
                side="buy_yes" if fair_prob > market["yes_price"] else "buy_no",
            )

            effective_prob = ml_adjusted if ml_adjusted is not None else fair_prob

            yes_price = market["yes_price"]
            mispricing = effective_prob - yes_price

            if abs(mispricing) > MISPRICING_THRESHOLD:
                if mispricing > 0:
                    side = "buy_yes"
                    edge = mispricing
                    kelly = calculate_kelly(effective_prob, yes_price, balance)
                else:
                    side = "buy_no"
                    edge = abs(mispricing)
                    kelly = calculate_kelly(1 - effective_prob, market["no_price"], balance)

                if kelly >= MIN_TRADE_AMOUNT:
                    opportunities.append({
                        "market": market,
                        "fair_prob": fair_prob,
                        "ml_adjusted_prob": ml_adjusted,
                        "effective_prob": effective_prob,
                        "side": side,
                        "edge": edge,
                        "kelly_amount": kelly,
                    })
                    ml_tag = " [ML]" if ml_adjusted else ""
                    print(
                        f"  [#{i+1}] OPPORTUNITY{ml_tag}: {side} | Edge: {edge:.3f} | "
                        f"Kelly: ${kelly:.2f} | {market['question'][:50]}..."
                    )

            time.sleep(0.3)

        except Exception as e:
            print(f"  [#{i+1}] Error analyzing market: {e}")
            continue

    print(f"\n[Agent] Found {len(opportunities)} trading opportunities")
    audit_log("opportunities_found", f"{len(opportunities)} opportunities from {len(markets_to_analyze)} markets")

    opportunities.sort(key=lambda x: x["edge"], reverse=True)

    trades_executed = 0
    cloudflare_blocked = False
    for opp in opportunities[:10]:
        if cloudflare_blocked:
            print("[Agent] Stopping trades - Cloudflare is blocking requests")
            break

        valid, errors = validate_trade_inputs(
            opp["side"], opp["kelly_amount"],
            opp["market"]["yes_price"] if opp["side"] == "buy_yes" else opp["market"]["no_price"],
            opp["fair_prob"],
        )
        if not valid:
            print(f"  [SKIP] Validation failed: {errors}")
            continue

        current_balance = get_usdc_balance()
        if current_balance < MIN_BALANCE_THRESHOLD:
            print("[Agent] Balance too low, stopping trades")
            break

        result = execute_trade(
            market=opp["market"],
            side=opp["side"],
            amount_usdc=opp["kelly_amount"],
            fair_prob=opp["fair_prob"],
        )

        if result.get("status") == "error: blocked_by_cloudflare":
            cloudflare_blocked = True

        log_trade(result)

        market_price = opp["market"]["yes_price"] if opp["side"] == "buy_yes" else opp["market"]["no_price"]
        log_trade_for_ml(
            market_id=opp["market"]["condition_id"],
            market_description=opp["market"]["question"][:200],
            fair_prob=opp["fair_prob"],
            market_prob=market_price,
            side=opp["side"],
            amount_usdc=opp["kelly_amount"],
            edge=opp["edge"],
            kelly_fraction=opp["kelly_amount"] / current_balance if current_balance > 0 else 0,
            ml_adjusted_prob=opp.get("ml_adjusted_prob"),
        )

        trades_executed += 1
        time.sleep(2)

    final_balance = get_usdc_balance()
    log_balance(final_balance, f"Cycle end - {trades_executed} trades executed")

    audit_log("cycle_end", f"{trades_executed} trades, balance: ${final_balance:.2f}")

    print(f"\n[Agent] Cycle complete: {trades_executed} trades | Balance: ${final_balance:.2f}")
    print(f"[Agent] Estimated AI cost this session: ${get_total_cost():.4f}")

    print_recent_summary()


def calculate_kelly(fair_prob, market_price, bankroll):
    if market_price <= 0 or market_price >= 1:
        return 0.0

    edge = fair_prob - market_price
    if edge <= 0:
        return 0.0

    kelly_fraction = edge / (1 - market_price)
    kelly_fraction = min(kelly_fraction, MAX_KELLY_FRACTION)
    kelly_fraction = max(kelly_fraction, 0.0)

    amount = bankroll * kelly_fraction
    return round(amount, 2)


def log_trade(trade_info):
    try:
        session = get_session()
        trade = PolymarketTrade(
            timestamp=trade_info.get("timestamp", datetime.now(timezone.utc)),
            market_id=trade_info.get("market_id", ""),
            market_description=trade_info.get("market_description", ""),
            side=trade_info.get("side", ""),
            amount_usdc=trade_info.get("amount_usdc", 0),
            price=trade_info.get("price", 0),
            fair_prob=trade_info.get("fair_prob"),
            tx_hash=trade_info.get("tx_hash", ""),
            status=trade_info.get("status", "unknown"),
        )
        session.add(trade)
        session.commit()
        session.close()
    except Exception as e:
        print(f"[DB] Error logging trade: {e}")


def log_balance(balance, note=""):
    try:
        session = get_session()
        entry = AgentBalance(
            timestamp=datetime.now(timezone.utc),
            usdc_balance=balance,
            note=note,
        )
        session.add(entry)
        session.commit()
        session.close()
    except Exception as e:
        print(f"[DB] Error logging balance: {e}")


def print_recent_summary():
    try:
        session = get_session()

        recent_trades = (
            session.query(PolymarketTrade)
            .order_by(PolymarketTrade.id.desc())
            .limit(5)
            .all()
        )

        latest_balance = (
            session.query(AgentBalance)
            .order_by(AgentBalance.id.desc())
            .first()
        )

        print("\n" + "-" * 50)
        print("RECENT TRADES:")
        print("-" * 50)
        if recent_trades:
            for t in reversed(recent_trades):
                print(
                    f"  {t.timestamp.strftime('%H:%M:%S')} | {t.side:8s} | "
                    f"${t.amount_usdc:7.2f} @ {t.price:.3f} | "
                    f"{t.status:10s} | {(t.market_description or '')[:40]}..."
                )
        else:
            print("  No trades yet")

        if latest_balance:
            print(f"\nCurrent Balance: ${latest_balance.usdc_balance:.2f} ({latest_balance.note})")

        print("-" * 50)
        session.close()

    except Exception as e:
        print(f"[DB] Error printing summary: {e}")
