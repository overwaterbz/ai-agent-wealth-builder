import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import calculate_kelly

MISPRICING_THRESHOLD = 0.08


def simulate_backtest(markets, ai_estimates, outcomes):
    bankroll = 1000.0
    trades = []
    max_kelly_fraction = 0.06

    for i, market in enumerate(markets):
        fair_prob = ai_estimates[i]
        yes_price = market["yes_price"]
        mispricing = fair_prob - yes_price

        if abs(mispricing) < MISPRICING_THRESHOLD:
            continue

        if mispricing > 0:
            side = "buy_yes"
            kelly = calculate_kelly(fair_prob, yes_price, bankroll)
            price = yes_price
        else:
            side = "buy_no"
            no_price = market["no_price"]
            kelly = calculate_kelly(1 - fair_prob, no_price, bankroll)
            price = no_price

        if kelly < 1.0:
            continue

        outcome = outcomes[i]
        won = (side == "buy_yes" and outcome == "yes") or (side == "buy_no" and outcome == "no")

        if won:
            profit = kelly * (1.0 / price - 1.0)
        else:
            profit = -kelly

        bankroll += profit

        trades.append({
            "market": market["question"],
            "side": side,
            "amount": kelly,
            "price": price,
            "fair_prob": fair_prob,
            "outcome": outcome,
            "won": won,
            "profit": profit,
            "bankroll": bankroll,
        })

    return trades, bankroll


class TestBacktest:
    def setup_method(self):
        self.markets = [
            {"question": "Will BTC hit $100k?", "yes_price": 0.3, "no_price": 0.7,
             "condition_id": "1", "yes_token_id": "t1", "no_token_id": "t2"},
            {"question": "Will ETH hit $10k?", "yes_price": 0.1, "no_price": 0.9,
             "condition_id": "2", "yes_token_id": "t3", "no_token_id": "t4"},
            {"question": "Rain tomorrow?", "yes_price": 0.5, "no_price": 0.5,
             "condition_id": "3", "yes_token_id": "t5", "no_token_id": "t6"},
            {"question": "AI passes bar exam?", "yes_price": 0.8, "no_price": 0.2,
             "condition_id": "4", "yes_token_id": "t7", "no_token_id": "t8"},
            {"question": "GDP positive Q1?", "yes_price": 0.6, "no_price": 0.4,
             "condition_id": "5", "yes_token_id": "t9", "no_token_id": "t10"},
        ]
        self.ai_estimates = [0.5, 0.3, 0.55, 0.6, 0.75]
        self.outcomes = ["yes", "no", "yes", "yes", "yes"]

    def test_backtest_runs(self):
        trades, final = simulate_backtest(self.markets, self.ai_estimates, self.outcomes)
        assert isinstance(trades, list)
        assert isinstance(final, float)

    def test_backtest_trade_count(self):
        trades, _ = simulate_backtest(self.markets, self.ai_estimates, self.outcomes)
        assert len(trades) >= 1

    def test_backtest_tracks_bankroll(self):
        trades, final = simulate_backtest(self.markets, self.ai_estimates, self.outcomes)
        if trades:
            assert trades[-1]["bankroll"] == final

    def test_all_losses_reduce_bankroll(self):
        bad_outcomes = ["no", "yes", "no", "no", "no"]
        trades, final = simulate_backtest(self.markets, self.ai_estimates, bad_outcomes)
        losing_trades = [t for t in trades if not t["won"]]
        for t in losing_trades:
            assert t["profit"] < 0

    def test_perfect_predictions(self):
        perfect_estimates = [0.99, 0.01, 0.99, 0.99, 0.99]
        trades, final = simulate_backtest(self.markets, perfect_estimates, self.outcomes)
        winning = sum(1 for t in trades if t["won"])
        assert winning == len(trades)
        assert final > 1000.0

    def test_no_trades_below_threshold(self):
        mild_estimates = [0.35, 0.15, 0.52, 0.78, 0.62]
        trades, final = simulate_backtest(self.markets, mild_estimates, self.outcomes)
        for t in trades:
            edge = abs(t["fair_prob"] - t["price"])
            assert edge >= MISPRICING_THRESHOLD
