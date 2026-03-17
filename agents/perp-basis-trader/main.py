import time
import schedule
import random
from datetime import datetime, timezone

from shared.treasury import record_cycle_pnl, write_trade_history
from shared.sizing import get_dynamic_trade_size, get_agent_overrides

CYCLE_MINUTES = 30

"""
Perp Basis Trader Agent
Fetches BTC/ETH spot prices from Binance and funding/mark prices from Binance
Futures (all public endpoints). Trades the basis when it exceeds 0.1%.
"""
import os
import logging
import requests
from datetime import datetime, timezone

from shared.notifier import send_whatsapp_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("perp-basis-trader")

IS_DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")

CYCLE_MINUTES = int(os.getenv("PERP_BASIS_CYCLE_MINUTES", "30"))
MIN_BASIS_PCT = 0.20          # 0.20% min basis — must exceed ~0.15% round-trip fees to be profitable
TRADE_SIZE_USD = 50.0         # $50 per basis trade — at $10 even profitable captures are dust
MIN_PROFIT_USD = 0.01         # minimum expected profit after fees
HL_ROUND_TRIP_FEE_PCT = 0.00075  # 0.075% round-trip (maker 2.5bps + taker 5bps)

PAIRS = [
    {"symbol": "BTCUSDT", "name": "BTC"},
    {"symbol": "ETHUSDT", "name": "ETH"},
    {"symbol": "BNBUSDT", "name": "BNB"},
]

# ── Funding Rate Capture Strategy ────────────────────────────────────
FUNDING_COINS       = ["BTC", "ETH", "SOL", "DOGE"]  # High-volume coins with volatile funding
MIN_FUNDING_RATE    = 0.00003            # 0.003%/hr minimum (~26% APR) — lowered to catch more opportunities
MAX_FUNDING_POS_USD = 15.0              # Cap notional per coin — conservative for small account
FUNDING_CYCLE_MIN   = 15                # Check every 15 minutes
MAX_MARGIN_USE_PCT  = 0.80              # Don't use more than 80% of account margin


def _spot_price(symbol: str) -> float:
    """Binance spot best bid/ask mid."""
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": symbol},
            timeout=8,
        )
        r.raise_for_status()
        return float(r.json().get("price", 0))
    except Exception as e:
        logger.warning(f"Spot price fetch failed {symbol}: {e}")
        return 0.0


def _mark_price(symbol: str) -> float:
    """Binance Futures mark price (perp)."""
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=8,
        )
        r.raise_for_status()
        return float(r.json().get("markPrice", 0))
    except Exception as e:
        logger.warning(f"Mark price fetch failed {symbol}: {e}")
        return 0.0


# ── Hyperliquid helpers ──────────────────────────────────────────────

def _get_hl_clients():
    """Return (Info, Exchange, address) or (None, None, None)."""
    hl_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
    if not hl_key:
        return None, None, None
    try:
        from hyperliquid.info import Info
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants as hl_constants
        from eth_account import Account

        info = Info(hl_constants.MAINNET_API_URL, skip_ws=True)
        wallet = Account.from_key(hl_key)
        exchange = Exchange(wallet, hl_constants.MAINNET_API_URL)
        address = wallet.address
        return info, exchange, address
    except Exception as e:
        logger.error(f"Failed to init HL clients: {e}")
        return None, None, None


def _fetch_funding_rates(info):
    """Current per-hour funding rates for FUNDING_COINS."""
    try:
        data = info.meta_and_asset_ctxs()
        universe, ctxs = data[0]["universe"], data[1]
        rates = {}
        for asset, ctx in zip(universe, ctxs):
            coin = asset["name"]
            if coin in FUNDING_COINS:
                rates[coin] = {
                    "rate": float(ctx.get("funding", ctx.get("fundingRate", "0"))),
                    "mark": float(ctx.get("markPx", "0")),
                    "sz_dec": asset.get("szDecimals", 5),
                }
        return rates
    except Exception as e:
        logger.error(f"Funding rate fetch failed: {e}")
        return {}


def _fetch_positions(info, address):
    """Open positions and available account value (unified: perps + spot USDC)."""
    try:
        state = info.user_state(address)
        positions = {}
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            coin, szi = p.get("coin", ""), float(p.get("szi", "0"))
            if szi != 0:
                positions[coin] = {
                    "size": szi,
                    "entry": float(p.get("entryPx", "0")),
                    "upnl": float(p.get("unrealizedPnl", "0")),
                    "value": abs(szi * float(p.get("entryPx", "0"))),
                    "margin": float(p.get("marginUsed", "0")),
                }
        ms = state.get("marginSummary", {})
        acct_value = float(ms.get("accountValue", "0"))
        # Unified account: spot USDC is also available as perps margin
        # In unified/EVM mode, marginSummary.accountValue can be near-zero
        # even when real equity sits on the spot side
        if acct_value < 1.0:
            try:
                spot = info.spot_user_state(address)
                for b in spot.get("balances", []):
                    if b["coin"] == "USDC":
                        acct_value += float(b.get("total", "0"))
            except Exception:
                pass
        return positions, acct_value
    except Exception as e:
        logger.error(f"Position fetch failed: {e}")
        return {}, 0.0


def run_cycle() -> None:
    global TRADE_SIZE_USD
    TRADE_SIZE_USD = get_dynamic_trade_size("perp-basis-trader", TRADE_SIZE_USD)
    _overrides = get_agent_overrides("perp-basis-trader")
    for _k, _v in _overrides.items():
        if _k in globals() and isinstance(globals()[_k], (int, float, str, bool)):
            globals()[_k] = type(globals()[_k])(_v)
    traded = 0
    total_profit = 0.0

    for pair in PAIRS:
        spot = _spot_price(pair["symbol"])
        mark = _mark_price(pair["symbol"])

        if spot <= 0 or mark <= 0:
            logger.debug(f"{pair['name']}: missing prices (spot={spot} mark={mark})")
            continue

        basis_pct = (mark - spot) / spot * 100    # positive = perp premium
        logger.info(f"{pair['name']}: spot={spot:.2f} mark={mark:.2f} basis={basis_pct:+.4f}%")

        if abs(basis_pct) < MIN_BASIS_PCT:
            continue

        # Trade: short the premium leg, long the discount leg
        side = "SHORT_PERP" if basis_pct > 0 else "LONG_PERP"
        # Expect basis to revert to 0 — capture half the basis, minus round-trip fees
        capture = abs(basis_pct) / 100 * 0.5
        fees = TRADE_SIZE_USD * HL_ROUND_TRIP_FEE_PCT
        net_profit = round(TRADE_SIZE_USD * capture - fees, 4)

        if net_profit < MIN_PROFIT_USD:
            logger.info(f"{pair['name']}: basis {basis_pct:+.4f}% but net_profit ${net_profit:.4f} < ${MIN_PROFIT_USD} after fees — skip")
            continue

        logger.info(
            f"{'[PAPER]' if IS_DRY_RUN else '[LIVE]'} TRADE | {pair['name']} {side} "
            f"| basis={basis_pct:+.4f}% | P&L=+${net_profit:.4f}"
        )

        order_filled = False
        if not IS_DRY_RUN:
            # Real execution: short the premium leg on HyperLiquid perpetuals
            hl_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
            if hl_key:
                try:
                    from hyperliquid.exchange import Exchange
                    from hyperliquid.utils import constants as hl_constants
                    from eth_account import Account as _Acct
                    _w = _Acct.from_key(hl_key)
                    exchange = Exchange(_w, hl_constants.MAINNET_API_URL)
                    size = round(TRADE_SIZE_USD / spot, 6)
                    order = exchange.market_open(
                        pair["name"],
                        is_buy=(side == "LONG_PERP"),
                        sz=size,
                        reduce_only=False,
                    )
                    logger.info(f"HyperLiquid order: {order}")
                    if order and order.get("status") == "ok":
                        order_filled = True
                    else:
                        logger.warning(f"HyperLiquid order not confirmed: {order}")
                except ImportError:
                    logger.warning(
                        "hyperliquid-python-sdk not installed — "
                        "run: pip install hyperliquid-python-sdk"
                    )
                except Exception as e:
                    logger.error(f"HyperLiquid execution error: {e}")
            else:
                logger.warning("No HYPERLIQUID_PRIVATE_KEY — perp execution skipped")

        # Only record P&L and alert on confirmed HyperLiquid fills (not paper, not rejected orders)
        if order_filled:
            record_cycle_pnl(net_profit, f"perp-basis-trader-{pair['name'].lower()}")
            write_trade_history(
                "perp-basis-trader", side, TRADE_SIZE_USD, net_profit,
                market_id=pair["name"], category="perp",
            )
            send_whatsapp_alert(
                f"\U0001f501 Perp Basis TRADE EXECUTED | {pair['name']} {side}\n"
                f"Basis {basis_pct:+.4f}% | P&L: +${net_profit:.4f}"
            )
        traded += 1
        total_profit += net_profit

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    logger.info(f"[{ts}] Cycle done | trades={traded} | total=+${total_profit:.4f}")


def run_funding_cycle() -> None:
    """Capture funding payments by taking the receiving side."""
    info, exchange, address = _get_hl_clients()
    if not info:
        logger.warning("HL clients unavailable \u2014 funding cycle skipped")
        return

    rates = _fetch_funding_rates(info)
    if not rates:
        return

    positions, account_value = _fetch_positions(info, address)

    for coin in FUNDING_COINS:
        ri = rates.get(coin)
        if not ri:
            continue
        rate, mark, sz_dec = ri["rate"], ri["mark"], ri["sz_dec"]
        pos = positions.get(coin)

        logger.info(
            f"FUNDING | {coin}: rate={rate:+.6f} ({rate*100:+.4f}%/hr) mark={mark:.2f}"
            + (f" | pos={pos['size']:+.{sz_dec}f}" if pos else "")
        )

        # ── Manage existing position ────────────────────────────
        if pos:
            is_long = pos["size"] > 0
            should_close, reason = False, ""

            if abs(rate) < MIN_FUNDING_RATE * 0.3:
                should_close, reason = True, "rate too low"
            elif rate > 0 and is_long:
                should_close, reason = True, "longs now paying"
            elif rate < 0 and not is_long:
                should_close, reason = True, "shorts now paying"

            if should_close:
                logger.info(f"{'[PAPER]' if IS_DRY_RUN else '[LIVE]'} CLOSE {coin} ({reason})")
                if not IS_DRY_RUN:
                    try:
                        result = exchange.market_close(coin)
                        logger.info(f"Close result: {result}")
                        if result and result.get("status") == "ok":
                            pnl = pos["upnl"]
                            record_cycle_pnl(pnl, f"perp-funding-{coin.lower()}")
                            write_trade_history(
                                "perp-basis-trader",
                                f"CLOSE_{'LONG' if is_long else 'SHORT'}",
                                pos["value"], pnl,
                                market_id=coin, category="funding",
                            )
                            send_whatsapp_alert(
                                f"\U0001f4b0 Funding CLOSE {coin} | PnL ${pnl:+.4f} | {reason}"
                            )
                    except Exception as e:
                        logger.error(f"Close {coin} failed: {e}")
            else:
                hourly = pos["value"] * abs(rate)
                logger.info(f"HOLD {coin} \u2014 earning ~${hourly:.4f}/hr")
            continue

        # ── Open new position ───────────────────────────────────
        if abs(rate) < MIN_FUNDING_RATE:
            continue

        # Re-query actual margin from exchange (don't rely on stale loop variable)
        positions_now, account_value_now = _fetch_positions(info, address)
        total_margin_now = sum(p["margin"] for p in positions_now.values())
        free_margin_now = account_value_now - total_margin_now

        margin_used_pct = total_margin_now / account_value_now if account_value_now > 0 else 1.0
        if margin_used_pct >= MAX_MARGIN_USE_PCT:
            logger.info(f"Skip {coin} \u2014 margin limit {margin_used_pct*100:.1f}% >= {MAX_MARGIN_USE_PCT*100:.0f}%")
            continue

        if free_margin_now < account_value_now * 0.20:
            logger.info(f"Skip {coin} \u2014 margin low (free ${free_margin_now:.2f})")
            continue

        # Positive rate \u2192 longs pay shorts \u2192 go SHORT to collect
        # Negative rate \u2192 shorts pay longs \u2192 go LONG to collect
        is_buy = rate < 0
        side = "LONG" if is_buy else "SHORT"

        dynamic_sz = get_dynamic_trade_size("perp-basis-trader", TRADE_SIZE_USD)
        notional = min(dynamic_sz, MAX_FUNDING_POS_USD, free_margin_now * 0.5)
        size = round(notional / mark, sz_dec)

        hourly = notional * abs(rate)
        daily = hourly * 24

        logger.info(
            f"{'[PAPER]' if IS_DRY_RUN else '[LIVE]'} OPEN {side} {coin} "
            f"${notional:.2f} | rate={rate:+.6f} | est ${hourly:.4f}/hr (${daily:.2f}/day)"
        )

        if not IS_DRY_RUN:
            try:
                order = exchange.market_open(coin, is_buy=is_buy, sz=size)
                logger.info(f"HL order: {order}")
                if order and order.get("status") == "ok":
                    write_trade_history(
                        "perp-basis-trader", f"OPEN_{side}",
                        notional, 0.0,
                        market_id=coin, category="funding",
                    )
                    send_whatsapp_alert(
                        f"\U0001f4ca Funding OPEN {coin} {side} ${notional:.2f}\n"
                        f"Rate {rate:+.6f} | Est ${daily:.2f}/day"
                    )
            except Exception as e:
                logger.error(f"HL funding open error: {e}")

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    logger.info(f"[{ts}] Funding cycle done | positions={len(positions)}")


def main() -> None:
    import time
    import schedule
    logger.info("Perp Basis Trader agent starting (basis + funding capture)...")
    logger.info("Perp Basis Trader agent started")
    run_cycle()
    run_funding_cycle()
    schedule.every(CYCLE_MINUTES).minutes.do(run_cycle)
    schedule.every(FUNDING_CYCLE_MIN).minutes.do(run_funding_cycle)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
