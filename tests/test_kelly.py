import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import calculate_kelly


class TestKellyCriterion:
    def test_positive_edge(self):
        result = calculate_kelly(fair_prob=0.6, market_price=0.4, bankroll=1000)
        assert result > 0
        assert result <= 1000 * 0.06

    def test_no_edge(self):
        result = calculate_kelly(fair_prob=0.5, market_price=0.5, bankroll=1000)
        assert result == 0.0

    def test_negative_edge(self):
        result = calculate_kelly(fair_prob=0.3, market_price=0.5, bankroll=1000)
        assert result == 0.0

    def test_max_fraction_cap(self):
        result = calculate_kelly(fair_prob=0.99, market_price=0.01, bankroll=1000)
        assert result <= 1000 * 0.06

    def test_zero_bankroll(self):
        result = calculate_kelly(fair_prob=0.6, market_price=0.4, bankroll=0)
        assert result == 0.0

    def test_invalid_price_zero(self):
        result = calculate_kelly(fair_prob=0.5, market_price=0.0, bankroll=1000)
        assert result == 0.0

    def test_invalid_price_one(self):
        result = calculate_kelly(fair_prob=0.5, market_price=1.0, bankroll=1000)
        assert result == 0.0

    def test_small_edge(self):
        result = calculate_kelly(fair_prob=0.51, market_price=0.50, bankroll=1000)
        assert result >= 0

    def test_large_bankroll(self):
        result = calculate_kelly(fair_prob=0.7, market_price=0.5, bankroll=100000)
        assert result <= 100000 * 0.06

    def test_result_is_rounded(self):
        result = calculate_kelly(fair_prob=0.6, market_price=0.4, bankroll=1000)
        assert result == round(result, 2)
