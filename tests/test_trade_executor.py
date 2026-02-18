import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.trade_executor as executor_module
from src.trade_executor import execute_trade


class TestTradeExecutor:
    def setup_method(self):
        self.sample_market = {
            "condition_id": "test_condition_123",
            "question": "Will it rain tomorrow?",
            "description": "Will it rain tomorrow?",
            "yes_price": 0.5,
            "no_price": 0.5,
            "yes_token_id": "token_yes_123",
            "no_token_id": "token_no_123",
        }

    @patch.object(executor_module, 'DRY_RUN', True)
    def test_dry_run_buy_yes(self):
        result = execute_trade(
            market=self.sample_market,
            side="buy_yes",
            amount_usdc=10.0,
            fair_prob=0.7,
        )
        assert result["status"] == "dry_run"
        assert result["side"] == "buy_yes"
        assert result["amount_usdc"] == 10.0
        assert result["price"] == 0.5
        assert result["fair_prob"] == 0.7
        assert "DRY_RUN" in result["tx_hash"]

    @patch.object(executor_module, 'DRY_RUN', True)
    def test_dry_run_buy_no(self):
        result = execute_trade(
            market=self.sample_market,
            side="buy_no",
            amount_usdc=25.0,
            fair_prob=0.3,
        )
        assert result["status"] == "dry_run"
        assert result["side"] == "buy_no"
        assert result["price"] == 0.5

    def test_trade_info_fields(self):
        result = execute_trade(
            market=self.sample_market,
            side="buy_yes",
            amount_usdc=5.0,
            fair_prob=0.6,
        )
        required_fields = [
            "market_id", "market_description", "side",
            "amount_usdc", "price", "fair_prob", "tx_hash", "status", "timestamp"
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_market_id_set(self):
        result = execute_trade(
            market=self.sample_market,
            side="buy_yes",
            amount_usdc=5.0,
            fair_prob=0.6,
        )
        assert result["market_id"] == "test_condition_123"
