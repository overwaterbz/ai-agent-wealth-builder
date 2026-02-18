import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.security import validate_trade_inputs


class TestTradeValidation:
    def test_valid_inputs(self):
        valid, errors = validate_trade_inputs("buy_yes", 50.0, 0.5, 0.6)
        assert valid is True
        assert len(errors) == 0

    def test_invalid_side(self):
        valid, errors = validate_trade_inputs("sell_yes", 50.0, 0.5, 0.6)
        assert valid is False
        assert any("side" in e.lower() for e in errors)

    def test_amount_too_low(self):
        valid, errors = validate_trade_inputs("buy_yes", 0.001, 0.5, 0.6)
        assert valid is False

    def test_amount_too_high(self):
        valid, errors = validate_trade_inputs("buy_yes", 50000.0, 0.5, 0.6)
        assert valid is False

    def test_price_out_of_range(self):
        valid, errors = validate_trade_inputs("buy_yes", 50.0, 1.5, 0.6)
        assert valid is False

    def test_fair_prob_out_of_range(self):
        valid, errors = validate_trade_inputs("buy_yes", 50.0, 0.5, 1.5)
        assert valid is False

    def test_boundary_values(self):
        valid, errors = validate_trade_inputs("buy_no", 0.01, 0.001, 0.01)
        assert valid is True

    def test_multiple_errors(self):
        valid, errors = validate_trade_inputs("invalid", 0.0, 2.0, -1.0)
        assert valid is False
        assert len(errors) >= 3
