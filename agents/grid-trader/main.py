"""
BTC Sniper Agent — Hyperliquid Perpetuals
Directional momentum sniper modeled after high-WR BTC traders.
Uses EMA crossover + pullback on 1h candles for selective entries,
20× isolated leverage, and 3:1 R:R take-profit/stop-loss.
Position sizes scale with equity for automatic compounding.
"""
import os
import time
import json
import math
import logging
import requests
from datetime import datetime, timezone, timedelta

from shared.treasury import record_cycle_pnl, write_trade_history
from shared.notifier import send_whatsapp_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("btc-sniper")

IS_DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("1", "true", "yes")

# ── Sniper configuration ─────────────────────────────────────────────
SNIPER_COINS        = [c.strip() for c in os.getenv("SNIPER_COINS", "BTC,ETH").split(",")]  # Multi-coin
LEVERAGE            = int(os.getenv("SNIPER_LEVERAGE", "20"))       # 20× isolated — matches top-WR trader pattern
RISK_FRACTION       = float(os.getenv("SNIPER_RISK_FRACTION", "0.12"))  # 12% of equity as margin per trade (reduced from 25% to compensate for wider SL)
SL_PCT              = float(os.getenv("SNIPER_SL_PCT", "0.008"))   # 0.8% stop-loss on entry price (widened from 0.4% to reduce false stops)
TP_RATIO            = float(os.getenv("SNIPER_TP_RATIO", "2.5"))   # 2.5:1 reward:risk → TP at 2.0% from entry
MAX_HOLD_HOURS      = int(os.getenv("SNIPER_MAX_HOLD_HOURS", "4")) # Force-close after 4h to avoid overnight risk
MAX_MARGIN_USE_PCT  = float(os.getenv("MAX_MARGIN_USE_PCT", "0.70"))
CYCLE_SECONDS       = int(os.getenv("SNIPER_CYCLE_SECONDS", "30"))
MIN_NOTIONAL_USD    = 10.0  # HL minimum order value

# EMA signal parameters
EMA_SHORT           = int(os.getenv("SNIPER_EMA_SHORT", "5"))      # Fast EMA period (1h candles)
EMA_LONG            = int(os.getenv("SNIPER_EMA_LONG", "20"))      # Slow EMA period (1h candles)
CANDLE_INTERVAL     = "1h"
CANDLE_COUNT        = 30  # Fetch 30 candles (covers EMA_LONG + buffer)

# Peak trading hours (UTC) — European open through US close
PEAK_HOUR_START     = int(os.getenv("SNIPER_PEAK_HOUR_START", "8"))
PEAK_HOUR_END       = int(os.getenv("SNIPER_PEAK_HOUR_END", "21"))

# Entry order expiry — cancel unfilled limit entries after this many seconds
ENTRY_EXPIRY_SEC    = 300  # 5 minutes

# Maker order offset from mid price (0.02% for maker rebate)
MAKER_OFFSET        = 0.0002

# ATR-based adaptive SL: SL = max(SL_PCT, ATR_SL_MULTIPLIER * ATR / price)
ATR_PERIOD          = 14       # 14-period ATR on 1h candles
ATR_SL_MULTIPLIER   = 1.5     # SL = 1.5 × ATR (widens in volatile markets, tightens in calm)
USE_ATR_SL          = True     # Set False to use static SL_PCT only

# RSI filter to reduce false signals
RSI_PERIOD          = 14
RSI_OVERBOUGHT      = 65      # Only LONG when RSI < 65 (not overbought)
RSI_OVERSOLD        = 35      # Only SHORT when RSI > 35 (not oversold)

# Trailing stop ratchet: trail SL at (price - TRAIL_DISTANCE * entry_price) for longs
TRAIL_DISTANCE_PCT  = 0.006   # 0.6% trailing distance (tighter than initial SL to lock profits)

# HL API endpoint
HL_INFO_URL         = "https://api.hyperliquid.xyz/info"

# State directory for crash recovery (one file per coin)
STATE_DIR = os.getenv("SNIPER_STATE_DIR", "/app/models")

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


def _get_asset_meta(info, coin):
    """Get szDecimals and other metadata for a coin."""
    try:
        data = info.meta_and_asset_ctxs()
        universe = data[0]["universe"]
        for asset in universe:
            if asset["name"] == coin:
                return {
                    "szDecimals": asset.get("szDecimals", 5),
                }
        return {"szDecimals": 5}
    except Exception as e:
        logger.error(f"Asset meta fetch failed: {e}")
        return {"szDecimals": 5}


def _get_mid_price(info, coin):
    """Get current mid price for a coin on Hyperliquid."""
    try:
        mids = info.all_mids()
        return float(mids.get(coin, 0))
    except Exception as e:
        logger.error(f"Mid price fetch failed for {coin}: {e}")
        return 0.0


def _get_open_orders(info, address):
    """Get all open orders on Hyperliquid."""
    try:
        return info.open_orders(address)
    except Exception as e:
        logger.error(f"Open orders fetch failed: {e}")
        return []


def _get_account_state(info, address):
    """Get positions and margin info (unified: perps + spot USDC)."""
    try:
        state = info.user_state(address)
        positions = {}
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            coin = p.get("coin", "")
            szi = float(p.get("szi", "0"))
            if szi != 0:
                positions[coin] = {
                    "size": szi,
                    "entry": float(p.get("entryPx", "0")),
                    "upnl": float(p.get("unrealizedPnl", "0")),
                    "margin": float(p.get("marginUsed", "0")),
                }
        ms = state.get("marginSummary", {})
        account_value = float(ms.get("accountValue", "0"))
        total_margin = float(ms.get("totalMarginUsed", "0"))
        # Unified account: spot USDC is also available as perps margin
        # In unified/EVM mode, marginSummary.accountValue can be near-zero
        # even when real equity sits on the spot side
        if account_value < 1.0:
            try:
                spot = info.spot_user_state(address)
                for b in spot.get("balances", []):
                    if b["coin"] == "USDC":
                        account_value += float(b.get("total", "0"))
            except Exception:
                pass
        return positions, account_value, total_margin
    except Exception as e:
        logger.error(f"Account state fetch failed: {e}")
        return {}, 0.0, 0.0


def _round_price(price, sig_figs=5):
    """Round price to Hyperliquid's max significant figures."""
    if price == 0:
        return 0.0
    import math
    magnitude = math.floor(math.log10(abs(price)))
    factor = 10 ** (sig_figs - 1 - magnitude)
    return round(price * factor) / factor


def _round_size(size, sz_decimals):
    """Round size to asset's szDecimals."""
    return round(size, sz_decimals)


def _cancel_all_orders(exchange, info, address, coin):
    """Cancel all open orders for a coin."""
    orders = _get_open_orders(info, address)
    coin_orders = [o for o in orders if o.get("coin") == coin]
    if not coin_orders:
        return 0
    try:
        cancels = [{"coin": coin, "oid": o["oid"]} for o in coin_orders]
        result = exchange.bulk_cancel(cancels)
        logger.info(f"Cancelled {len(cancels)} orders: {result}")
        return len(cancels)
    except Exception as e:
        logger.error(f"Bulk cancel failed: {e}")
        cancelled = 0
        for o in coin_orders:
            try:
                exchange.cancel(coin, o["oid"])
                cancelled += 1
            except Exception:
                pass
        return cancelled


def _check_margin_available(info, address):
    """Check if we have enough margin headroom."""
    _, account_value, total_margin = _get_account_state(info, address)
    if account_value <= 0:
        return False, 0.0
    margin_used_pct = total_margin / account_value if account_value > 0 else 1.0
    available = account_value * MAX_MARGIN_USE_PCT - total_margin
    return margin_used_pct < MAX_MARGIN_USE_PCT, available


# ── Candle fetching and EMA signal engine ─────────────────────────────

def _fetch_candles(coin, interval=CANDLE_INTERVAL, count=CANDLE_COUNT):
    """Fetch recent candles from Hyperliquid's candleSnapshot API."""
    try:
        end_ms = int(time.time() * 1000)
        # 1h candles: each candle = 3600s
        interval_ms = 3600 * 1000 if interval == "1h" else 300 * 1000
        start_ms = end_ms - count * interval_ms

        resp = requests.post(
            HL_INFO_URL,
            json={
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
        if not raw or not isinstance(raw, list):
            logger.warning(f"Empty candle response for {coin}")
            return []

        candles = [{"t": c["t"], "c": float(c["c"]), "h": float(c["h"]),
                     "l": float(c["l"]), "o": float(c["o"]), "v": float(c["v"])}
                    for c in raw]
        logger.info(f"Fetched {len(candles)} candles for {coin} ({interval})")
        return candles
    except Exception as e:
        logger.error(f"Candle fetch failed for {coin}: {e}")
        return []


def _compute_ema(prices, period):
    """Compute EMA for a list of prices. Returns the final EMA value."""
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period  # SMA seed
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _get_signal(candles):
    """Determine LONG, SHORT, or FLAT based on EMA crossover + pullback + RSI filter.

    LONG:  EMA5 > EMA20 (uptrend) AND current price <= EMA5 (pullback dip) AND RSI < 65
    SHORT: EMA5 < EMA20 (downtrend) AND current price >= EMA5 (bounce) AND RSI > 35
    """
    if len(candles) < EMA_LONG + 1:
        logger.warning(f"Insufficient candles ({len(candles)}) for EMA-{EMA_LONG}")
        return "FLAT", 0.0, 0.0

    closes = [c["c"] for c in candles]
    current_price = closes[-1]

    ema_short = _compute_ema(closes, EMA_SHORT)
    ema_long = _compute_ema(closes, EMA_LONG)

    if ema_short is None or ema_long is None:
        return "FLAT", 0.0, 0.0

    # RSI filter
    rsi = _compute_rsi(closes)
    rsi_str = f"RSI={rsi:.1f}" if rsi is not None else "RSI=N/A"

    logger.info(
        f"EMA signal | EMA{EMA_SHORT}={ema_short:.2f} EMA{EMA_LONG}={ema_long:.2f} "
        f"price={current_price:.2f} spread={(ema_short-ema_long)/ema_long*100:.3f}% {rsi_str}"
    )

    # Require meaningful EMA separation (0.02% minimum) to avoid chop
    ema_spread = abs(ema_short - ema_long) / ema_long
    if ema_spread < 0.0002:
        return "FLAT", ema_short, ema_long

    if ema_short > ema_long and current_price <= ema_short:
        # RSI filter: don't go long if overbought
        if rsi is not None and rsi >= RSI_OVERBOUGHT:
            logger.info(f"LONG signal rejected — RSI {rsi:.1f} >= {RSI_OVERBOUGHT} (overbought)")
            return "FLAT", ema_short, ema_long
        return "LONG", ema_short, ema_long
    elif ema_short < ema_long and current_price >= ema_short:
        # RSI filter: don't go short if oversold
        if rsi is not None and rsi <= RSI_OVERSOLD:
            logger.info(f"SHORT signal rejected — RSI {rsi:.1f} <= {RSI_OVERSOLD} (oversold)")
            return "FLAT", ema_short, ema_long
        return "SHORT", ema_short, ema_long

    return "FLAT", ema_short, ema_long


def _is_peak_hours():
    """Check if current UTC hour is within the peak trading window."""
    hour = datetime.now(timezone.utc).hour
    if PEAK_HOUR_START <= PEAK_HOUR_END:
        return PEAK_HOUR_START <= hour < PEAK_HOUR_END
    # Handle wrap-around (e.g., 22-6)
    return hour >= PEAK_HOUR_START or hour < PEAK_HOUR_END


# ── Sniper state management ──────────────────────────────────────────

class SniperState:
    """Tracks a single active sniper position per coin for crash recovery."""

    def __init__(self, coin):
        self.coin = coin
        self._state_file = os.path.join(STATE_DIR, f"sniper_state_{coin}.json")
        self.status = "idle"         # "idle", "entry_pending", "positioned"
        self.side = ""               # "long" or "short"
        self.entry_price = 0.0
        self.entry_size = 0.0
        self.entry_time = ""         # ISO timestamp
        self.entry_oid = ""          # Order ID for pending entry
        self.tp_price = 0.0
        self.sl_price = 0.0
        self.tp_oid = ""             # Order ID for take-profit limit
        self.sl_oid = ""             # Order ID for exchange-side stop-loss limit
        self.trailing_active = False # True once SL moved to breakeven
        # Cumulative stats
        self.total_pnl = 0.0
        self.total_trades = 0
        self.wins = 0
        self.losses = 0

    def save(self):
        try:
            data = {
                "coin": self.coin,
                "status": self.status,
                "side": self.side,
                "entry_price": self.entry_price,
                "entry_size": self.entry_size,
                "entry_time": self.entry_time,
                "entry_oid": self.entry_oid,
                "tp_price": self.tp_price,
                "sl_price": self.sl_price,
                "tp_oid": self.tp_oid,
                "sl_oid": self.sl_oid,
                "trailing_active": self.trailing_active,
                "total_pnl": self.total_pnl,
                "total_trades": self.total_trades,
                "wins": self.wins,
                "losses": self.losses,
            }
            os.makedirs(STATE_DIR, exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump(data, f, default=str)
        except Exception as e:
            logger.warning(f"Failed to save sniper state for {self.coin}: {e}")

    def load(self):
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, "r") as f:
                    data = json.load(f)
                self.status = data.get("status", "idle")
                self.side = data.get("side", "")
                self.entry_price = data.get("entry_price", 0.0)
                self.entry_size = data.get("entry_size", 0.0)
                self.entry_time = data.get("entry_time", "")
                self.entry_oid = data.get("entry_oid", "")
                self.tp_price = data.get("tp_price", 0.0)
                self.sl_price = data.get("sl_price", 0.0)
                self.tp_oid = data.get("tp_oid", "")
                self.sl_oid = data.get("sl_oid", "")
                self.trailing_active = data.get("trailing_active", False)
                self.total_pnl = data.get("total_pnl", 0.0)
                self.total_trades = data.get("total_trades", 0)
                self.wins = data.get("wins", 0)
                self.losses = data.get("losses", 0)
                if self.status != "idle":
                    logger.info(
                        f"Loaded {self.coin} state: {self.status} {self.side} "
                        f"entry={self.entry_price:.2f} size={self.entry_size} "
                        f"TP={self.tp_price:.2f} SL={self.sl_price:.2f} "
                        f"trailing={self.trailing_active}"
                    )
        except Exception as e:
            logger.warning(f"Failed to load sniper state for {self.coin}: {e}")

    def reset_position(self):
        """Clear position data back to idle."""
        self.status = "idle"
        self.side = ""
        self.entry_price = 0.0
        self.entry_size = 0.0
        self.entry_time = ""
        self.entry_oid = ""
        self.tp_price = 0.0
        self.sl_price = 0.0
        self.tp_oid = ""
        self.sl_oid = ""
        self.trailing_active = False
        self.save()

    @property
    def win_rate(self):
        if self.total_trades == 0:
            return 0.0
        return self.wins / self.total_trades


# ── Core sniper logic ─────────────────────────────────────────────────

def _set_leverage(exchange, coin):
    """Set isolated leverage for the sniper coin."""
    try:
        result = exchange.update_leverage(LEVERAGE, coin, is_cross=False)
        logger.info(f"Set {coin} leverage to {LEVERAGE}x isolated: {result}")
        return True
    except Exception as e:
        logger.error(f"Failed to set leverage: {e}")
        return False


def _place_entry_order(exchange, coin, is_buy, entry_price, size, sz_decimals):
    """Place a maker limit entry order with slight offset from mid for maker rebate."""
    if IS_DRY_RUN:
        logger.info(f"[PAPER] Would enter {'LONG' if is_buy else 'SHORT'} "
                     f"{coin} at {entry_price:.2f} × {size}")
        return None

    try:
        order = exchange.order(
            coin,
            is_buy=is_buy,
            limit_px=entry_price,
            sz=size,
            order_type={"limit": {"tif": "Gtc"}},
        )
        logger.info(f"Entry order response: {order}")
        if order and order.get("status") == "ok":
            statuses = order.get("response", {}).get("data", {}).get("statuses", [])
            for s in statuses:
                if "resting" in s:
                    oid = str(s["resting"]["oid"])
                    logger.info(f"ENTRY ORDER placed | {'LONG' if is_buy else 'SHORT'} "
                                f"{coin} at {entry_price:.2f} × {size} (oid={oid})")
                    return oid
                elif "filled" in s:
                    oid = str(s["filled"]["oid"])
                    logger.info(f"ENTRY FILLED immediately | {'LONG' if is_buy else 'SHORT'} "
                                f"{coin} at {entry_price:.2f} × {size} (oid={oid})")
                    return f"filled:{oid}"
                elif "error" in s:
                    logger.warning(f"Entry order rejected: {s['error']}")
        return None
    except Exception as e:
        logger.error(f"Entry order failed: {e}")
        return None


def _place_tp_order(exchange, coin, is_buy_to_close, tp_price, size):
    """Place the take-profit limit order (opposite side to close position)."""
    if IS_DRY_RUN:
        return None
    try:
        order = exchange.order(
            coin,
            is_buy=is_buy_to_close,
            limit_px=tp_price,
            sz=size,
            order_type={"limit": {"tif": "Gtc"}},
            reduce_only=True,
        )
        if order and order.get("status") == "ok":
            statuses = order.get("response", {}).get("data", {}).get("statuses", [])
            for s in statuses:
                if "resting" in s:
                    oid = str(s["resting"]["oid"])
                    logger.info(f"TP ORDER placed at {tp_price:.2f} (oid={oid})")
                    return oid
                elif "error" in s:
                    logger.warning(f"TP order rejected: {s['error']}")
        return None
    except Exception as e:
        logger.error(f"TP order failed: {e}")
        return None


def _place_sl_order(exchange, coin, is_buy_to_close, sl_price, size):
    """Place an exchange-side stop-loss limit order (reduce-only).

    This provides a safety net on the exchange itself, so even if our software
    cycle is delayed or the process crashes, the SL lives on the exchange.
    """
    if IS_DRY_RUN:
        return None
    try:
        order = exchange.order(
            coin,
            is_buy=is_buy_to_close,
            limit_px=sl_price,
            sz=size,
            order_type={"limit": {"tif": "Gtc"}},
            reduce_only=True,
        )
        if order and order.get("status") == "ok":
            statuses = order.get("response", {}).get("data", {}).get("statuses", [])
            for s in statuses:
                if "resting" in s:
                    oid = str(s["resting"]["oid"])
                    logger.info(f"SL ORDER placed at {sl_price:.2f} (oid={oid})")
                    return oid
                elif "error" in s:
                    logger.warning(f"SL order rejected: {s['error']}")
        return None
    except Exception as e:
        logger.error(f"SL order failed: {e}")
        return None


def _place_or_replace_sl(exchange, info, address, coin, state, new_sl_price, size):
    """Cancel existing exchange SL and place a new one at the updated price."""
    # Cancel old SL order if it exists
    if state.sl_oid:
        try:
            exchange.cancel(coin, int(state.sl_oid))
            logger.info(f"Cancelled old SL order (oid={state.sl_oid})")
        except Exception as e:
            logger.warning(f"Failed to cancel old SL (oid={state.sl_oid}): {e}")
        state.sl_oid = ""

    # Place new SL
    is_buy_to_close = (state.side == "short")
    sl_oid = _place_sl_order(exchange, coin, is_buy_to_close, new_sl_price, size)
    state.sl_oid = sl_oid or ""
    state.sl_price = new_sl_price
    return sl_oid


def _place_tp_with_retry(exchange, info, address, coin, state, is_buy_to_close, tp_price, size, max_retries=3):
    """Place TP order with retry logic. If all retries fail, market-close immediately."""
    for attempt in range(max_retries):
        tp_oid = _place_tp_order(exchange, coin, is_buy_to_close, tp_price, size)
        if tp_oid:
            return tp_oid
        logger.warning(f"TP placement attempt {attempt+1}/{max_retries} failed for {coin}")
        if attempt < max_retries - 1:
            time.sleep(2)

    # All retries exhausted — market-close to avoid naked position
    logger.error(f"TP placement FAILED after {max_retries} retries — emergency market-close {coin}")
    _close_position(exchange, info, address, coin, state, "TP_PLACEMENT_FAILED")
    return None


# ── ATR and RSI computation helpers ──────────────────────────────────

def _compute_atr(candles, period=ATR_PERIOD):
    """Compute Average True Range from candles. Returns ATR value or None."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["h"]
        low = candles[i]["l"]
        prev_close = candles[i - 1]["c"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    # Simple moving average of last `period` true ranges
    atr = sum(trs[-period:]) / period
    return atr


def _compute_rsi(closes, period=RSI_PERIOD):
    """Compute RSI from closing prices. Returns RSI value (0-100) or None."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    if len(gains) < period:
        return None
    # Wilder's smoothing: initial SMA, then exponential
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_adaptive_sl(candles, mid_price):
    """Compute ATR-based adaptive SL percentage. Returns SL as a fraction (e.g. 0.008)."""
    if not USE_ATR_SL:
        return SL_PCT
    atr = _compute_atr(candles)
    if atr is None or mid_price <= 0:
        return SL_PCT
    atr_sl = ATR_SL_MULTIPLIER * atr / mid_price
    # Floor at SL_PCT (never tighter than configured minimum), cap at 2% to avoid huge losses
    adaptive = max(SL_PCT, min(atr_sl, 0.02))
    logger.info(f"ATR={atr:.2f} | ATR_SL={atr_sl*100:.3f}% | adaptive_SL={adaptive*100:.3f}%")
    return adaptive


def _close_position(exchange, info, address, coin, state, reason):
    """Market-close the current position and record PnL."""
    positions, account_value, _ = _get_account_state(info, address)
    pos = positions.get(coin)
    pnl = pos["upnl"] if pos else 0.0

    # Cancel any open orders for this coin first
    _cancel_all_orders(exchange, info, address, coin)

    if pos and not IS_DRY_RUN:
        try:
            result = exchange.market_close(coin)
            logger.info(f"{reason} close result: {result}")
        except Exception as e:
            logger.error(f"{reason} close failed: {e}")
            return 0.0

    # Record stats
    state.total_trades += 1
    state.total_pnl += pnl
    if pnl > 0:
        state.wins += 1
    else:
        state.losses += 1

    record_cycle_pnl(pnl, "grid-trader")
    write_trade_history(
        "grid-trader",
        f"SNIPER_{reason}_{state.side.upper()}",
        state.entry_size * state.entry_price,
        pnl,
        market_id=coin,
        category="perp",
    )

    emoji = "\U0001f3af" if pnl > 0 else "\U0001f6d1"
    send_whatsapp_alert(
        f"{emoji} Sniper {reason} | {coin} {state.side.upper()}\n"
        f"Entry: ${state.entry_price:.2f} → Close: ${_get_mid_price(info, coin):.2f}\n"
        f"PnL: ${pnl:+.2f} | WR: {state.win_rate*100:.0f}% ({state.wins}W/{state.losses}L)\n"
        f"Career PnL: ${state.total_pnl:+.2f}"
    )

    logger.info(
        f"{reason} | {coin} {state.side} | PnL=${pnl:+.2f} | "
        f"Career: {state.wins}W/{state.losses}L ${state.total_pnl:+.2f}"
    )

    state.reset_position()
    return pnl


def _manage_position(exchange, info, address, coin, state):
    """Check TP fill, SL fill, software SL backup, trailing ratchet, and time stop."""
    mid = _get_mid_price(info, coin)
    if mid <= 0:
        return

    # ── Check if TP order filled ──────────────────────────────────
    if state.tp_oid:
        current_orders = _get_open_orders(info, address)
        tp_still_open = any(
            str(o["oid"]) == state.tp_oid and o.get("coin") == coin
            for o in current_orders
        )
        if not tp_still_open:
            # TP filled — position closed at profit
            pnl = state.entry_size * state.tp_price - state.entry_size * state.entry_price
            if state.side == "short":
                pnl = state.entry_size * state.entry_price - state.entry_size * state.tp_price

            positions, _, _ = _get_account_state(info, address)
            if coin not in positions:
                # Cancel remaining SL order since TP closed the position
                if state.sl_oid:
                    try:
                        exchange.cancel(coin, int(state.sl_oid))
                    except Exception:
                        pass

                state.total_trades += 1
                state.total_pnl += pnl
                state.wins += 1

                record_cycle_pnl(pnl, "grid-trader")
                write_trade_history(
                    "grid-trader", f"SNIPER_TP_{state.side.upper()}",
                    state.entry_size * state.entry_price, pnl,
                    market_id=coin, category="perp",
                )

                send_whatsapp_alert(
                    f"\U0001f3af Sniper TP HIT | {coin} {state.side.upper()}\n"
                    f"Entry: ${state.entry_price:.2f} \u2192 TP: ${state.tp_price:.2f}\n"
                    f"PnL: ${pnl:+.2f} | WR: {state.win_rate*100:.0f}%\n"
                    f"Career: ${state.total_pnl:+.2f}"
                )

                logger.info(
                    f"TP HIT | {coin} {state.side} | entry={state.entry_price:.2f} "
                    f"tp={state.tp_price:.2f} | PnL=${pnl:+.2f}"
                )

                state.reset_position()
                return

    # ── Check if exchange SL order filled ─────────────────────────
    if state.sl_oid:
        current_orders = _get_open_orders(info, address)
        sl_still_open = any(
            str(o["oid"]) == state.sl_oid and o.get("coin") == coin
            for o in current_orders
        )
        if not sl_still_open:
            positions, _, _ = _get_account_state(info, address)
            if coin not in positions:
                # Exchange SL fired and closed the position
                pnl = state.entry_size * state.sl_price - state.entry_size * state.entry_price
                if state.side == "short":
                    pnl = state.entry_size * state.entry_price - state.entry_size * state.sl_price

                # Cancel remaining TP order
                if state.tp_oid:
                    try:
                        exchange.cancel(coin, int(state.tp_oid))
                    except Exception:
                        pass

                state.total_trades += 1
                state.total_pnl += pnl
                if pnl > 0:
                    state.wins += 1
                else:
                    state.losses += 1

                record_cycle_pnl(pnl, "grid-trader")
                write_trade_history(
                    "grid-trader", f"SNIPER_SL_EXCHANGE_{state.side.upper()}",
                    state.entry_size * state.entry_price, pnl,
                    market_id=coin, category="perp",
                )

                send_whatsapp_alert(
                    f"\U0001f6d1 Sniper SL (exchange) | {coin} {state.side.upper()}\n"
                    f"Entry: ${state.entry_price:.2f} \u2192 SL: ${state.sl_price:.2f}\n"
                    f"PnL: ${pnl:+.2f} | WR: {state.win_rate*100:.0f}%\n"
                    f"Career: ${state.total_pnl:+.2f}"
                )

                logger.info(
                    f"SL HIT (exchange) | {coin} {state.side} | PnL=${pnl:+.2f}"
                )

                state.reset_position()
                return

    # ── Software SL backup (in case exchange SL didn't fire) ──────
    if state.side == "long" and mid <= state.sl_price:
        logger.warning(f"SOFTWARE SL triggered | {coin} LONG at {mid:.2f} <= SL {state.sl_price:.2f}")
        _close_position(exchange, info, address, coin, state, "STOP_LOSS_SW")
        return
    elif state.side == "short" and mid >= state.sl_price:
        logger.warning(f"SOFTWARE SL triggered | {coin} SHORT at {mid:.2f} >= SL {state.sl_price:.2f}")
        _close_position(exchange, info, address, coin, state, "STOP_LOSS_SW")
        return

    # ── Time stop check ───────────────────────────────────────────
    if state.entry_time:
        entry_dt = datetime.fromisoformat(state.entry_time)
        held_hours = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
        if held_hours >= MAX_HOLD_HOURS:
            logger.info(f"TIME STOP | {coin} held {held_hours:.1f}h >= {MAX_HOLD_HOURS}h limit")
            _close_position(exchange, info, address, coin, state, "TIME_STOP")
            return

    # ── Trailing stop logic (breakeven then ratchet) ──────────────
    if state.entry_price > 0:
        sl_updated = False

        if state.side == "long":
            if not state.trailing_active:
                # Activate trailing at 1:1 R — move SL to breakeven
                target_1r = state.entry_price * (1 + SL_PCT)
                if mid >= target_1r:
                    old_sl = state.sl_price
                    new_sl = _round_price(state.entry_price)  # Breakeven
                    state.trailing_active = True
                    sl_updated = True
                    logger.info(
                        f"TRAILING ACTIVE | {coin} LONG 1:1R reached (mid={mid:.2f} >= {target_1r:.2f}) "
                        f"SL moved {old_sl:.2f} \u2192 {new_sl:.2f} (breakeven)"
                    )
            else:
                # Ratchet SL upward: trail at TRAIL_DISTANCE_PCT below current price
                trail_sl = _round_price(mid * (1 - TRAIL_DISTANCE_PCT))
                if trail_sl > state.sl_price:
                    old_sl = state.sl_price
                    new_sl = trail_sl
                    sl_updated = True
                    logger.info(
                        f"TRAILING RATCHET | {coin} LONG SL {old_sl:.2f} \u2192 {new_sl:.2f} "
                        f"(mid={mid:.2f}, trail={TRAIL_DISTANCE_PCT*100:.1f}%)"
                    )

        else:  # short
            if not state.trailing_active:
                target_1r = state.entry_price * (1 - SL_PCT)
                if mid <= target_1r:
                    old_sl = state.sl_price
                    new_sl = _round_price(state.entry_price)  # Breakeven
                    state.trailing_active = True
                    sl_updated = True
                    logger.info(
                        f"TRAILING ACTIVE | {coin} SHORT 1:1R reached (mid={mid:.2f} <= {target_1r:.2f}) "
                        f"SL moved {old_sl:.2f} \u2192 {new_sl:.2f} (breakeven)"
                    )
            else:
                trail_sl = _round_price(mid * (1 + TRAIL_DISTANCE_PCT))
                if trail_sl < state.sl_price:
                    old_sl = state.sl_price
                    new_sl = trail_sl
                    sl_updated = True
                    logger.info(
                        f"TRAILING RATCHET | {coin} SHORT SL {old_sl:.2f} \u2192 {new_sl:.2f} "
                        f"(mid={mid:.2f}, trail={TRAIL_DISTANCE_PCT*100:.1f}%)"
                    )

        if sl_updated:
            # Update exchange-side SL order to match new SL price
            _place_or_replace_sl(exchange, info, address, coin, state, new_sl, state.entry_size)
            state.save()

    # ── Log position status ───────────────────────────────────────
    positions, account_value, _ = _get_account_state(info, address)
    pos = positions.get(coin, {})
    upnl = pos.get("upnl", 0.0)
    if state.entry_time:
        held = (datetime.now(timezone.utc) - datetime.fromisoformat(state.entry_time)).total_seconds() / 60
    else:
        held = 0
    trail_tag = " [TRAILING]" if state.trailing_active else ""
    logger.info(
        f"POSITION | {coin} {state.side.upper()} | entry={state.entry_price:.2f} "
        f"mid={mid:.2f} | uPnL=${upnl:+.2f} | SL={state.sl_price:.2f} TP={state.tp_price:.2f} "
        f"| held={held:.0f}m | equity=${account_value:.2f}{trail_tag}"
    )


def _manage_pending_entry(exchange, info, address, coin, state):
    """Check if a pending entry order has filled or should be cancelled."""
    if not state.entry_oid:
        state.reset_position()
        return

    current_orders = _get_open_orders(info, address)
    entry_still_open = any(
        str(o["oid"]) == state.entry_oid and o.get("coin") == coin
        for o in current_orders
    )

    if entry_still_open:
        # Check if entry has expired
        if state.entry_time:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state.entry_time)).total_seconds()
            if elapsed > ENTRY_EXPIRY_SEC:
                logger.info(f"Entry order expired after {elapsed:.0f}s — cancelling")
                _cancel_all_orders(exchange, info, address, coin)
                state.reset_position()
                return
        logger.info(f"Entry order still pending (oid={state.entry_oid})")
        return

    # Entry order is gone from open orders — check if we have a position
    positions, _, _ = _get_account_state(info, address)
    if coin in positions:
        pos = positions[coin]
        actual_entry = pos["entry"]
        actual_size = abs(pos["size"])

        # Entry filled — transition to positioned state
        state.status = "positioned"
        state.entry_price = actual_entry
        state.entry_size = actual_size
        state.entry_oid = ""

        # Compute TP and SL from actual entry price
        if state.side == "long":
            state.tp_price = _round_price(actual_entry * (1 + SL_PCT * TP_RATIO))
            state.sl_price = _round_price(actual_entry * (1 - SL_PCT))
        else:
            state.tp_price = _round_price(actual_entry * (1 - SL_PCT * TP_RATIO))
            state.sl_price = _round_price(actual_entry * (1 + SL_PCT))

        # Place TP limit order (with retry — emergency market-close if all fail)
        is_buy_to_close = (state.side == "short")
        tp_oid = _place_tp_with_retry(exchange, info, address, coin, state, is_buy_to_close, state.tp_price, actual_size)
        if tp_oid is None:
            # _place_tp_with_retry already market-closed; state was reset
            return
        state.tp_oid = tp_oid

        # Place exchange-side SL order (safety net for crashes/gaps)
        sl_oid = _place_sl_order(exchange, coin, is_buy_to_close, state.sl_price, actual_size)
        state.sl_oid = sl_oid or ""

        state.save()

        logger.info(
            f"ENTRY FILLED | {coin} {state.side.upper()} at {actual_entry:.2f} × {actual_size}\n"
            f"  TP={state.tp_price:.2f} SL={state.sl_price:.2f}"
        )

        send_whatsapp_alert(
            f"\U0001f3af Sniper ENTRY | {coin} {state.side.upper()}\n"
            f"Price: ${actual_entry:.2f} × {actual_size}\n"
            f"TP: ${state.tp_price:.2f} ({SL_PCT*TP_RATIO*100:.1f}%)\n"
            f"SL: ${state.sl_price:.2f} ({SL_PCT*100:.1f}%)\n"
            f"R:R = 1:{TP_RATIO:.0f}"
        )
    else:
        # Entry order gone but no position — was cancelled or rejected
        logger.info("Entry order gone with no position — resetting to idle")
        state.reset_position()


# ── Main cycle ────────────────────────────────────────────────────────

def _run_coin_cycle(info, exchange, address, coin, state):
    """Run one sniper cycle for a single coin."""
    mid = _get_mid_price(info, coin)
    if mid <= 0:
        logger.warning(f"No mid price for {coin}")
        return

    # ── Manage existing position ──────────────────────────────────
    if state.status == "positioned":
        _manage_position(exchange, info, address, coin, state)
        return

    if state.status == "entry_pending":
        _manage_pending_entry(exchange, info, address, coin, state)
        return

    # ── Idle: look for new entry ──────────────────────────────────

    # Check margin availability
    has_margin, available = _check_margin_available(info, address)
    if not has_margin:
        logger.info(f"[{coin}] Margin limit reached — paused (available: ${available:.2f})")
        return

    # Check if already holding a position (leftover from crash)
    positions, account_value, _ = _get_account_state(info, address)
    if coin in positions:
        # We have a position but state is idle — recover it
        pos = positions[coin]
        state.status = "positioned"
        state.side = "long" if pos["size"] > 0 else "short"
        state.entry_price = pos["entry"]
        state.entry_size = abs(pos["size"])
        state.entry_time = datetime.now(timezone.utc).isoformat()
        if state.side == "long":
            state.tp_price = _round_price(pos["entry"] * (1 + SL_PCT * TP_RATIO))
            state.sl_price = _round_price(pos["entry"] * (1 - SL_PCT))
        else:
            state.tp_price = _round_price(pos["entry"] * (1 - SL_PCT * TP_RATIO))
            state.sl_price = _round_price(pos["entry"] * (1 + SL_PCT))
        state.save()
        logger.info(f"Recovered orphaned {coin} position: {state.side} @ {state.entry_price:.2f}")
        _manage_position(exchange, info, address, coin, state)
        return

    # Check peak hours
    if not _is_peak_hours():
        hour = datetime.now(timezone.utc).hour
        logger.info(f"[{coin}] Outside peak hours ({PEAK_HOUR_START}-{PEAK_HOUR_END} UTC, now={hour}h) — idle")
        return

    # Fetch candles and compute signal
    candles = _fetch_candles(coin)
    if not candles:
        logger.warning(f"[{coin}] No candle data — skipping")
        return

    signal, ema_short, ema_long = _get_signal(candles)
    if signal == "FLAT":
        logger.info(f"[{coin}] Signal: FLAT — no trade | EMA{EMA_SHORT}={ema_short:.2f} EMA{EMA_LONG}={ema_long:.2f}")
        return

    # Compute position size (auto-compounds with equity)
    # Split risk across coins: each coin gets RISK_FRACTION / num_coins
    num_coins = len(SNIPER_COINS)
    per_coin_fraction = RISK_FRACTION / num_coins
    meta = _get_asset_meta(info, coin)
    sz_decimals = meta["szDecimals"]

    margin = account_value * per_coin_fraction
    notional = margin * LEVERAGE
    if notional < MIN_NOTIONAL_USD:
        logger.info(f"[{coin}] Notional ${notional:.2f} below minimum — skipping")
        return
    size = _round_size(notional / mid, sz_decimals)
    actual_notional = size * mid
    if actual_notional < MIN_NOTIONAL_USD:
        return

    # Atomic margin re-check: verify the new position won't exceed limit
    _, _, total_margin = _get_account_state(info, address)
    new_margin_needed = actual_notional / LEVERAGE
    projected_margin_pct = (total_margin + new_margin_needed) / account_value if account_value > 0 else 1.0
    if projected_margin_pct >= MAX_MARGIN_USE_PCT:
        logger.info(
            f"[{coin}] Post-sizing margin check FAILED | projected {projected_margin_pct*100:.1f}% "
            f">= {MAX_MARGIN_USE_PCT*100:.0f}% (current={total_margin:.2f} + new={new_margin_needed:.2f})"
        )
        return

    # Compute ATR-based adaptive SL
    adaptive_sl = _compute_adaptive_sl(candles, mid)

    logger.info(
        f"[{coin}] Position sizing | equity=${account_value:.2f} margin=${margin:.2f} "
        f"notional=${actual_notional:.2f} size={size} leverage={LEVERAGE}x SL={adaptive_sl*100:.2f}%"
    )

    # Set leverage (idempotent — call every time to ensure correct setting)
    if not IS_DRY_RUN:
        _set_leverage(exchange, coin)

    # Compute entry price with maker offset
    is_buy = (signal == "LONG")
    if is_buy:
        entry_price = _round_price(mid * (1 - MAKER_OFFSET))  # Slightly below mid
    else:
        entry_price = _round_price(mid * (1 + MAKER_OFFSET))  # Slightly above mid

    # Place entry order
    oid_result = _place_entry_order(exchange, coin, is_buy, entry_price, size, sz_decimals)

    if oid_result:
        now_iso = datetime.now(timezone.utc).isoformat()

        if oid_result.startswith("filled:"):
            # Immediately filled — go straight to positioned
            state.status = "positioned"
            state.side = "long" if is_buy else "short"
            state.entry_price = entry_price
            state.entry_size = size
            state.entry_time = now_iso
            state.entry_oid = ""

            # Set TP/SL using adaptive SL
            if is_buy:
                state.tp_price = _round_price(entry_price * (1 + adaptive_sl * TP_RATIO))
                state.sl_price = _round_price(entry_price * (1 - adaptive_sl))
            else:
                state.tp_price = _round_price(entry_price * (1 - adaptive_sl * TP_RATIO))
                state.sl_price = _round_price(entry_price * (1 + adaptive_sl))

            # Place TP order (with retry)
            is_buy_to_close = not is_buy
            tp_oid = _place_tp_with_retry(exchange, info, address, coin, state, is_buy_to_close, state.tp_price, size)
            if tp_oid is None:
                return  # Emergency market-closed by retry handler
            state.tp_oid = tp_oid

            # Place exchange-side SL order
            sl_oid = _place_sl_order(exchange, coin, is_buy_to_close, state.sl_price, size)
            state.sl_oid = sl_oid or ""

            state.save()

            send_whatsapp_alert(
                f"\U0001f3af Sniper ENTRY | {coin} {'LONG' if is_buy else 'SHORT'}\n"
                f"Price: ${entry_price:.2f} × {size}\n"
                f"TP: ${state.tp_price:.2f} ({SL_PCT*TP_RATIO*100:.1f}%)\n"
                f"SL: ${state.sl_price:.2f} ({SL_PCT*100:.1f}%)\n"
                f"R:R = 1:{TP_RATIO:.0f} | Equity: ${account_value:.2f}"
            )
        else:
            # Resting entry — wait for fill
            state.status = "entry_pending"
            state.side = "long" if is_buy else "short"
            state.entry_price = entry_price
            state.entry_size = size
            state.entry_time = now_iso
            state.entry_oid = oid_result
            state.save()

        logger.info(
            f"ENTRY {'FILLED' if oid_result.startswith('filled:') else 'PLACED'} | "
            f"{coin} {'LONG' if is_buy else 'SHORT'} at {entry_price:.2f} × {size} | "
            f"notional=${actual_notional:.2f} margin=${margin:.2f} | "
            f"TP={state.tp_price:.2f} SL={state.sl_price:.2f}"
        )
    else:
        logger.warning(f"Failed to place entry order for {coin} {signal}")


def run_sniper_cycle():
    """Main sniper cycle — iterates over all configured coins."""
    info, exchange, address = _get_hl_clients()
    if not info:
        logger.warning("HL clients unavailable — sniper cycle skipped")
        return

    for coin in SNIPER_COINS:
        state = SniperState(coin)
        state.load()
        try:
            _run_coin_cycle(info, exchange, address, coin, state)
        except Exception as e:
            logger.error(f"[{coin}] Cycle error: {e}")
        time.sleep(0.5)  # Brief pause between coins to avoid rate limiting


def main():
    import schedule

    coins_str = ",".join(SNIPER_COINS)
    logger.info(
        f"Multi-Coin Sniper starting | coins={coins_str} leverage={LEVERAGE}x "
        f"risk={RISK_FRACTION*100:.0f}% SL={SL_PCT*100:.1f}% TP_ratio={TP_RATIO:.1f}:1 "
        f"peak={PEAK_HOUR_START}-{PEAK_HOUR_END}UTC EMA={EMA_SHORT}/{EMA_LONG} "
        f"RSI={RSI_PERIOD}({RSI_OVERSOLD}/{RSI_OVERBOUGHT}) ATR_SL={USE_ATR_SL} "
        f"trailing=ratchet@{TRAIL_DISTANCE_PCT*100:.1f}% exchange_SL=on dry_run={IS_DRY_RUN}"
    )

    # Cancel any stale orders left from previous runs
    info, exchange, address = _get_hl_clients()
    if info and exchange:
        for coin in SNIPER_COINS:
            cancelled = _cancel_all_orders(exchange, info, address, coin)
            if cancelled:
                logger.info(f"Startup: cancelled {cancelled} stale {coin} orders")

    # Initial run
    run_sniper_cycle()

    # Schedule: check every CYCLE_SECONDS
    schedule.every(CYCLE_SECONDS).seconds.do(run_sniper_cycle)

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
