import os
import time
import httpx
from datetime import datetime, timezone

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() in ("true", "1", "yes")
CHAIN_ID = 137
POLYGON_PRIVATE_KEY = os.environ.get("POLYGON_PRIVATE_KEY", "")

_clob_client = None
_proxy_configured = False


def _get_proxy_url():
    api_key = os.environ.get("BRIGHTDATA_API_KEY", "")
    if not api_key:
        return None

    try:
        import requests as req
        headers = {"Authorization": f"Bearer {api_key}"}

        status_resp = req.get("https://api.brightdata.com/status", headers=headers, timeout=10)
        if status_resp.status_code != 200:
            print("[Proxy] Failed to get account status")
            return None
        customer_id = status_resp.json().get("customer", "")

        zones_resp = req.get("https://api.brightdata.com/zone/get_active_zones", headers=headers, timeout=10)
        if zones_resp.status_code != 200:
            print("[Proxy] Failed to get zones")
            return None
        zones = zones_resp.json()
        zone_name = None
        for z in zones:
            if z.get("type") in ("res_rotating", "res_static"):
                zone_name = z["name"]
                break
        if not zone_name:
            print("[Proxy] No residential proxy zone found")
            return None

        pw_resp = req.get(f"https://api.brightdata.com/zone/passwords?zone={zone_name}", headers=headers, timeout=10)
        if pw_resp.status_code != 200:
            print("[Proxy] Failed to get zone password")
            return None
        passwords = pw_resp.json().get("passwords", [])
        if not passwords:
            print("[Proxy] No password found for zone")
            return None

        username = f"brd-customer-{customer_id}-zone-{zone_name}"
        password = passwords[0]
        proxy_url = f"http://{username}:{password}@brd.superproxy.io:33335"
        print(f"[Proxy] Configured residential proxy via Bright Data (zone: {zone_name})")
        return proxy_url

    except Exception as e:
        print(f"[Proxy] Error setting up proxy: {e}")
        return None


def configure_proxy():
    global _proxy_configured
    if _proxy_configured:
        return

    proxy_url = _get_proxy_url()
    if not proxy_url:
        _proxy_configured = True
        return

    try:
        import py_clob_client.http_helpers.helpers as clob_helpers
        proxied_client = httpx.Client(
            http2=True,
            proxy=proxy_url,
            timeout=30.0,
            verify=False,
        )
        clob_helpers._http_client = proxied_client
        _proxy_configured = True
        print("[Proxy] httpx client patched with residential proxy")
    except Exception as e:
        print(f"[Proxy] Failed to patch httpx client: {e}")
        _proxy_configured = True


def get_clob_client():
    global _clob_client
    if DRY_RUN:
        return None

    if _clob_client is not None:
        return _clob_client

    configure_proxy()

    try:
        from py_clob_client.client import ClobClient

        host = "https://clob.polymarket.com"
        client = ClobClient(
            host,
            key=POLYGON_PRIVATE_KEY,
            chain_id=CHAIN_ID,
        )
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        _clob_client = client
        print("[Executor] CLOB client initialized with API credentials")
        return client
    except Exception as e:
        print(f"[Executor] Failed to init CLOB client: {e}")
        return None


def execute_trade(market, side, amount_usdc, fair_prob):
    token_id = market["yes_token_id"] if side == "buy_yes" else market["no_token_id"]
    price = market["yes_price"] if side == "buy_yes" else market["no_price"]

    trade_info = {
        "market_id": market["condition_id"],
        "market_description": market["question"][:200],
        "side": side,
        "amount_usdc": round(amount_usdc, 2),
        "price": price,
        "fair_prob": fair_prob,
        "token_id": token_id,
        "tx_hash": None,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc),
    }

    if DRY_RUN:
        trade_info["status"] = "dry_run"
        trade_info["tx_hash"] = f"DRY_RUN_{int(time.time())}"
        print(
            f"  [DRY RUN] {side.upper()} | ${amount_usdc:.2f} @ {price:.3f} | "
            f"Fair: {fair_prob:.3f} | {market['question'][:60]}..."
        )
        return trade_info

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType

        client = get_clob_client()
        if not client:
            trade_info["status"] = "error_no_client"
            return trade_info

        order_args = OrderArgs(
            price=price,
            size=amount_usdc / price if price > 0 else 0,
            side="BUY",
            token_id=token_id,
        )

        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.GTC)

        trade_info["tx_hash"] = str(resp.get("orderID", "unknown"))
        trade_info["status"] = "submitted"
        print(
            f"  [LIVE] {side.upper()} | ${amount_usdc:.2f} @ {price:.3f} | "
            f"Order: {trade_info['tx_hash'][:16]}..."
        )

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "blocked" in error_msg.lower() or "Cloudflare" in error_msg:
            trade_info["status"] = "error: blocked_by_cloudflare"
            print(f"  [ERROR] Trade blocked by Cloudflare protection")
        else:
            trade_info["status"] = f"error: {error_msg[:200]}"
            print(f"  [ERROR] Trade failed: {e}")

    return trade_info


def get_usdc_balance():
    if DRY_RUN:
        return 1000.0

    try:
        client = get_clob_client()
        if client:
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            bal_allowance = client.get_balance_allowance(params)
            raw_balance = bal_allowance.get("balance", "0")
            balance = float(raw_balance) / 1_000_000
            return round(balance, 2)
    except Exception as e:
        print(f"[Executor] Error fetching balance: {e}")

    return 0.0
