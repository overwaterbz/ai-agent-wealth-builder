import requests
import time


GAMMA_API_URL = "https://gamma-api.polymarket.com"


def fetch_active_markets(limit=500, max_markets=1000):
    """Fetch active markets from Polymarket's Gamma API.
    
    Returns a list of market dicts with keys:
      condition_id, question, tokens (list with token_id, outcome, price)
    """
    markets = []
    offset = 0

    while len(markets) < max_markets:
        try:
            params = {
                "limit": min(limit, max_markets - len(markets)),
                "offset": offset,
                "active": True,
                "closed": False,
            }
            resp = requests.get(
                f"{GAMMA_API_URL}/markets",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            for market in data:
                parsed = parse_market(market)
                if parsed:
                    markets.append(parsed)

            if len(data) < limit:
                break

            offset += limit
            time.sleep(0.5)

        except requests.RequestException as e:
            print(f"[MarketFetcher] Error fetching markets: {e}")
            break

    print(f"[MarketFetcher] Fetched {len(markets)} active markets")
    return markets


def parse_market(raw):
    """Parse a raw Gamma API market into a clean dict."""
    try:
        condition_id = raw.get("conditionId") or raw.get("condition_id", "")
        question = raw.get("question", "")
        description = raw.get("description", question)

        tokens = raw.get("tokens", [])
        if not tokens or len(tokens) < 2:
            clob_token_ids = raw.get("clobTokenIds", "")
            outcome_prices = raw.get("outcomePrices", "")
            outcomes = raw.get("outcomes", "")

            if clob_token_ids and outcome_prices:
                if isinstance(clob_token_ids, str):
                    clob_token_ids = clob_token_ids.strip("[]").replace('"', '').split(",")
                if isinstance(outcome_prices, str):
                    outcome_prices = outcome_prices.strip("[]").replace('"', '').split(",")
                if isinstance(outcomes, str):
                    outcomes = outcomes.strip("[]").replace('"', '').split(",")

                tokens = []
                for i, tid in enumerate(clob_token_ids):
                    tid = tid.strip()
                    price = float(outcome_prices[i].strip()) if i < len(outcome_prices) else 0.0
                    outcome = outcomes[i].strip() if i < len(outcomes) else ("Yes" if i == 0 else "No")
                    tokens.append({
                        "token_id": tid,
                        "outcome": outcome,
                        "price": price,
                    })
            else:
                return None

        else:
            parsed_tokens = []
            for t in tokens:
                parsed_tokens.append({
                    "token_id": t.get("token_id", ""),
                    "outcome": t.get("outcome", ""),
                    "price": float(t.get("price", 0)),
                })
            tokens = parsed_tokens

        yes_price = None
        no_price = None
        yes_token_id = None
        no_token_id = None

        for t in tokens:
            outcome_lower = t["outcome"].lower()
            if outcome_lower == "yes":
                yes_price = t["price"]
                yes_token_id = t["token_id"]
            elif outcome_lower == "no":
                no_price = t["price"]
                no_token_id = t["token_id"]

        if yes_price is None or no_price is None:
            return None

        return {
            "condition_id": condition_id,
            "question": question,
            "description": description,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
        }
    except Exception as e:
        return None
