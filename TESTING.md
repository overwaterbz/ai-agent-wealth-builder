# Testing Guide - AI Agent Wealth Builder

**Complete testing strategy for autonomous trading system**

---

## Overview

This system executes real trades when `DRY_RUN=false`. Comprehensive testing is **mandatory** before production.

**Testing Philosophy:**
1. Test in isolation (unit tests)
2. Test integrations (integration tests)
3. Test in simulation (dry-run with real data)
4. Monitor in production

---

## Table of Contents

1. [Unit Testing](#unit-testing)
2. [Integration Testing](#integration-testing)
3. [Dry-Run Validation](#dry-run-validation)
4. [Performance Testing](#performance-testing)
5. [Stress Testing](#stress-testing)
6. [Pre-Production Checklist](#pre-production-checklist)

---

## Unit Testing

### Run All Unit Tests

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-mock pytest-asyncio

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_agent.py -v

# Run specific test
pytest tests/test_trade_executor.py::test_kelly_criterion -v

# Run with verbose output and print statements
pytest -vvs

# Stop on first failure
pytest -x

# Run last failed
pytest --lf

# Run tests in parallel (faster)
pip install pytest-xdist
pytest -n auto
```

### Test Structure

```
tests/
├── test_agent.py              # Main agent logic
├── test_ai_analyzer.py        # OpenAI integration
├── test_market_fetcher.py     # Polymarket data
├── test_trade_executor.py     # Trade execution & Kelly Criterion
├── test_ml_trainer.py         # ML retraining logic
├── test_security.py           # Rate limiting, audit logging
├── test_models.py             # Database models
├── conftest.py                # Shared fixtures
└── __fixtures__/
    ├── mock_market_data.json
    ├── mock_openai_responses.json
    └── sample_trades.sql
```

### Example: Agent Logic Tests

```python
# tests/test_agent.py
import pytest
from src.agent import Agent
from src.models import Trade, Market

@pytest.fixture
def agent():
    """Create test agent with mock database"""
    return Agent(dry_run=True, test_mode=True)

@pytest.fixture
def mock_market(mocker):
    """Mock Polymarket data"""
    return {
        'id': 'test_market_123',
        'title': 'Will Bitcoin reach $100k in 2025?',
        'is_resolved': False,
        'yes_price': 0.65,
        'no_price': 0.35,
        'liquidity': 500000,
        'volume_24h': 150000,
    }

def test_agent_identifies_profitable_opportunities(agent, mock_market, mocker):
    """Test agent finds arbitrage opportunities"""
    mocker.patch('src.market_fetcher.fetch_markets', return_value=[mock_market])
    
    opportunities = agent.find_opportunities()
    
    assert len(opportunities) > 0
    assert opportunities[0]['market_id'] == 'test_market_123'

def test_agent_respects_max_drawdown(agent, mocker):
    """Test agent stops trading when drawdown exceeded"""
    # Setup: Agent already down 8% (max is 10%)
    mocker.patch('src.models.get_current_drawdown', return_value=8.0)
    
    can_trade = agent.can_trade()
    
    assert can_trade is False
    assert agent.last_alert == 'MAX_DRAWDOWN_EXCEEDED'

def test_agent_validates_market_liquidity(agent, mock_market, mocker):
    """Test agent filters illiquid markets"""
    illiquid_market = mock_market.copy()
    illiquid_market['liquidity'] = 5000  # Too small
    
    is_tradeable = agent.is_market_tradeable(illiquid_market)
    
    assert is_tradeable is False
```

### Example: Trade Executor Tests

```python
# tests/test_trade_executor.py
import pytest
from src.trade_executor import calculate_kelly_position, execute_trade

def test_kelly_criterion_calculation():
    """Test Kelly Fraction position sizing"""
    # Win rate: 60%, avg win: 1.5x, avg loss: 1x
    kelly_fraction = calculate_kelly_position(
        win_rate=0.60,
        avg_win=1.5,
        avg_loss=1.0,
        kelly_fraction=0.25  # Use 25% of Kelly for safety
    )
    
    # Expected: 0.25 * (0.60 * 1.5 - 0.40 * 1.0) / 1.5 = 0.1
    assert kelly_fraction == pytest.approx(0.10, abs=0.01)

def test_kelly_criterion_prevents_overleverage():
    """Test Kelly limits position size"""
    large_kelly = calculate_kelly_position(
        win_rate=0.50,
        avg_win=10.0,
        avg_loss=1.0,
        kelly_fraction=1.0  # Full Kelly
    )
    
    # Position size should be capped at 25% of capital
    assert large_kelly <= 0.25

def test_position_sizing_with_capital_limits(mocker):
    """Test trade executor respects max position size"""
    mocker.patch('src.models.get_current_capital', return_value=10000)
    
    position_usd = execute_trade(
        market_id='test',
        action='BUY',
        kelly_fraction=0.15,  # 15% of capital
        dry_run=True
    )
    
    assert position_usd <= 1500  # 15% of $10k

def test_trade_fails_on_insufficient_balance(mocker):
    """Test trading blocked when insufficient balance"""
    mocker.patch('src.models.get_current_balance', return_value=100)
    
    with pytest.raises(InsufficientBalanceError):
        execute_trade(
            market_id='test',
            action='BUY',
            amount_usd=1000,
            dry_run=True
        )
```

### Example: AI Analyzer Tests

```python
# tests/test_ai_analyzer.py
import pytest
from src.ai_analyzer import analyze_market

@pytest.fixture
def mock_openai(mocker):
    """Mock OpenAI API responses"""
    return mocker.patch('openai.ChatCompletion.create', return_value={
        'choices': [{'message': {'content': '0.65'}}]
    })

def test_ai_estimates_market_probability(mock_openai):
    """Test AI probability estimation"""
    market = {
        'title': 'Will BTC reach $100k by end of 2025?',
        'description': 'Bitcoin price prediction',
        'current_price': 0.65,
    }
    
    estimated_prob = analyze_market(market)
    
    assert 0.0 <= estimated_prob <= 1.0
    assert estimated_prob == pytest.approx(0.65, abs=0.05)

def test_ai_handles_api_errors(mocker):
    """Test graceful API failure handling"""
    mocker.patch('openai.ChatCompletion.create', side_effect=Exception('API Error'))
    
    with pytest.raises(OpenAIError):
        analyze_market({'title': 'Test'})

def test_ai_validation_prevents_invalid_estimates(mock_openai):
    """Test AI estimate validation"""
    # Mock invalid response
    mock_openai.return_value = {
        'choices': [{'message': {'content': '1.5'}}]  # Invalid: > 1.0
    }
    
    with pytest.raises(InvalidEstimateError):
        analyze_market({'title': 'Test'})
```

---

## Integration Testing

### Test Database Integration

```bash
# Start test database
docker run -d \
  --name test-postgres \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=wealth_builder_test \
  -p 5433:5432 \
  postgres:16

# Run integration tests
pytest tests/integration/ -v

# Cleanup
docker stop test-postgres
docker rm test-postgres
```

### Database Fixtures

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.models import Base, Market, Trade, Position

@pytest.fixture(scope='session')
def db_engine():
    """Create test database"""
    engine = create_engine('postgresql://postgres:testpass@localhost:5433/wealth_builder_test')
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture
def db_session(db_engine):
    """Create test database session"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()

@pytest.fixture
def sample_market(db_session):
    """Create sample market"""
    market = Market(
        id='test_123',
        title='Test Market',
        yes_price=0.65,
        no_price=0.35,
        liquidity=100000
    )
    db_session.add(market)
    db_session.commit()
    return market

@pytest.fixture
def sample_trade(db_session, sample_market):
    """Create sample trade"""
    trade = Trade(
        market_id=sample_market.id,
        action='BUY',
        amount_usd=500,
        entry_price=0.65,
        status='EXECUTED'
    )
    db_session.add(trade)
    db_session.commit()
    return trade
```

### API Integration Tests

```python
# tests/integration/test_polymarket_api.py
import pytest
from src.market_fetcher import fetch_markets, fetch_market

@pytest.mark.integration
def test_fetch_real_markets():
    """Test fetching real markets from Polymarket"""
    markets = fetch_markets(limit=5)
    
    assert len(markets) > 0
    assert 'title' in markets[0]
    assert 'yes_price' in markets[0]
    assert 0.0 <= markets[0]['yes_price'] <= 1.0

@pytest.mark.integration
def test_fetch_specific_market():
    """Test fetching specific market"""
    market = fetch_market('0x123abc...')
    
    assert market is not None
    assert 'id' in market
    assert 'is_resolved' in market

@pytest.mark.skip(reason="Requires real API, run manually")
def test_execute_real_trade():
    """Test executing real trade (manual only)"""
    from src.trade_executor import execute_trade
    
    result = execute_trade(
        market_id='real_market_123',
        action='BUY',
        amount_usd=50,
        dry_run=True  # Always dry-run for tests
    )
    
    assert result['status'] == 'EXECUTED'
    assert result['filled_price'] > 0
```

---

## Dry-Run Validation

### 1. Setup Dry-Run Environment

```bash
# Create .env.test
cat > .env.test <<EOF
DRY_RUN=true
DATABASE_URL=postgresql://trading_user:password@localhost:5432/wealth_builder_test
OPENAI_API_KEY=sk-test-key
POLYGON_NETWORK=mumbai  # Testnet
POLYGON_PRIVATE_KEY=0x...testnet_key...
CYCLE_INTERVAL_MINUTES=1
CONFIDENCE_THRESHOLD=0.50
MAX_POSITION_SIZE_USD=100
MAX_DRAWDOWN_PCT=50
KELLY_FRACTION=0.25
ML_MODEL_UPDATE_HOURS=24
EOF

# Run with test environment
docker-compose -f docker-compose.test.yml up -d
```

### 2. Create Test Database

```bash
# Initialize test database with sample data
docker-compose exec postgres psql -U trading_user wealth_builder_test <<EOF
INSERT INTO markets (id, title, yes_price, no_price, liquidity) VALUES
  ('market_1', 'Will BTC reach $100k?', 0.65, 0.35, 500000),
  ('market_2', 'Will ETH reach $5k?', 0.42, 0.58, 300000),
  ('market_3', 'Will Trump win 2024?', 0.55, 0.45, 1000000);
EOF
```

### 3. Run Full Trading Cycle in Dry-Run

```bash
# Monitor single cycle
docker-compose logs -f agent

# Expected output:
# agent_1 | 2025-02-17 10:00:00 INFO: Starting trading cycle
# agent_1 | 2025-02-17 10:00:05 INFO: Fetched 150 markets
# agent_1 | 2025-02-17 10:00:15 INFO: AI analysis complete: 8 opportunities found
# agent_1 | 2025-02-17 10:00:20 INFO: DRY RUN - Would execute: BUY 100 USD at 0.65
# agent_1 | 2025-02-17 10:00:25 INFO: DRY RUN - Would execute: SELL 75 USD at 0.58
# agent_1 | 2025-02-17 10:01:00 INFO: Cycle complete - 2 trades executed (DRY RUN)
# agent_1 | 2025-02-17 10:01:05 INFO: Portfolio: +2.3% (+$100)
```

### 4. Validate Dry-Run Results

```bash
# Check trades were recorded
docker-compose exec postgres psql -U trading_user wealth_builder <<EOF
SELECT executed_at, market_id, action, amount_usd, entry_price, status 
FROM trades 
WHERE status = 'DRY_RUN' 
ORDER BY executed_at DESC 
LIMIT 20;
EOF

# Expected:
# executed_at       | market_id | action | amount_usd | entry_price | status
# 2025-02-17 10:00:20 | market_1  | BUY    | 100.00     | 0.65        | DRY_RUN
# 2025-02-17 10:00:25 | market_2  | SELL   | 75.00      | 0.58        | DRY_RUN

# Check AI probability estimates
SELECT market_id, ai_probability, market_price, confidence 
FROM market_analysis 
ORDER BY analyzed_at DESC 
LIMIT 20;

# Check portfolio performance
SELECT 
  total_capital,
  current_value,
  pnl_realized,
  pnl_unrealized,
  drawdown_pct
FROM portfolio_metrics 
ORDER BY calculated_at DESC 
LIMIT 1;
```

### 5. Run Extended Dry-Run Test

```bash
# Run for 12 hours minimum
# Set CYCLE_INTERVAL_MINUTES=5 for faster iterations

# Monitor key metrics
watch -n 60 'docker-compose exec postgres psql -U trading_user wealth_builder -c "
SELECT 
  COUNT(*) as total_trades,
  SUM(CASE WHEN action = \"BUY\" THEN 1 ELSE 0 END) as buy_trades,
  SUM(CASE WHEN action = \"SELL\" THEN 1 ELSE 0 END) as sell_trades,
  ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
  ROUND(MAX(drawdown_pct), 2) as max_drawdown,
  DATE_TRUNC(\"hour\", executed_at) as hour
FROM trades 
WHERE status = \"DRY_RUN\" 
GROUP BY hour 
ORDER BY hour DESC;"'
```

### 6. Validate ML Retraining

```bash
# Check model is being updated
docker-compose exec postgres psql -U trading_user wealth_builder <<EOF
SELECT * FROM ml_model_versions 
ORDER BY updated_at DESC 
LIMIT 5;
EOF

# Verify model accuracy improves
SELECT 
  version,
  accuracy_score,
  precision_score,
  recall_score,
  f1_score,
  updated_at
FROM ml_model_versions 
ORDER BY updated_at DESC 
LIMIT 10;
```

---

## Performance Testing

### 1. Load Test API Endpoints

```bash
# Install load testing tool
pip install locust

# Create loads test script
cat > locustfile.py <<'EOF'
from locust import HttpUser, task, between

class DashboardUser(HttpUser):
    wait_time = between(1, 5)
    
    @task
    def get_dashboard(self):
        self.client.get("/api/dashboard")
    
    @task(2)
    def get_trades(self):
        self.client.get("/api/trades?limit=100")
    
    @task
    def get_portfolio(self):
        self.client.get("/api/portfolio")
EOF

# Run load test
locust -f locustfile.py --host=http://localhost:8000 --users=100 --spawn-rate=5 --run-time=5m
```

### 2. Database Query Performance

```bash
# Analyze slow queries
docker-compose exec postgres psql -U trading_user wealth_builder <<EOF
-- Enable query logging
ALTER SYSTEM SET log_stmts = 'all';
ALTER SYSTEM SET log_duration = on;
ALTER SYSTEM SET log_min_duration_statement = 100;  -- Log queries > 100ms
SELECT pg_reload_conf();

-- Wait 5 minutes for queries to log, then analyze
SELECT mean_time, calls, query 
FROM pg_stat_statements 
WHERE mean_time > 100 
ORDER BY mean_time DESC 
LIMIT 20;
EOF
```

### 3. Report Generation Performance

```bash
# Time report generation
time docker-compose exec agent python -c "
from src.dashboard import generate_report
import time
start = time.time()
report = generate_report(days=7)
duration = time.time() - start
print(f'Report generated in {duration:.2f}s')
print(f'Report size: {len(str(report))} bytes')
"
```

---

## Stress Testing

### 1. Rapid Market Changes

```bash
# Simulate 10x more markets
docker-compose exec postgres psql -U trading_user wealth_builder <<EOF
INSERT INTO markets (title, yes_price, no_price, liquidity)
SELECT 
  'Generated ' || generated_id || ': ' || title,
  RANDOM() * 0.5 + 0.25,
  RANDOM() * 0.5 + 0.25,
  RANDOM() * 1000000 + 100000
FROM markets, generate_series(1, 10) as generated_id
WHERE yes_price > 0;

SELECT COUNT(*) FROM markets;
EOF

# Run trading cycle - should handle increased volume
docker-compose logs -f agent
```

### 2. API Rate Limit Testing

```bash
# Send rapid requests to API
ab -n 1000 -c 100 http://localhost:8000/api/dashboard

# Expected:
# Without rate limiting: Some requests fail with 5xx
# With rate limiting: Some requests get 429 (Too Many Requests)
```

### 3. Database Connection Stress

```python
# Test connection pool exhaustion
import psycopg2
from concurrent.futures import ThreadPoolExecutor
import time

def stress_db():
    connections = []
    try:
        for i in range(20):
            conn = psycopg2.connect("postgresql://trading_user:password@localhost/wealth_builder")
            connections.append(conn)
            print(f"Connection {i+1} established")
            time.sleep(0.1)
    except psycopg2.OperationalError as e:
        print(f"Connection failed: {e}")
    finally:
        for conn in connections:
            conn.close()

# Run stress test
stress_db()

# Should handle gracefully without crashes
```

### 4. Long-Running Stability Test

```bash
# Run for 24 hours with monitoring
timeout 86400 docker-compose logs -f agent | tee stress_test_24h.log

# After 24 hours, analyze for stability
grep -i "error\|exception\|crashed" stress_test_24h.log | wc -l

# Check memory usage
docker stats --no-stream
```

---

## Pre-Production Checklist

### Code Quality

- [ ] All unit tests passing: `pytest --cov=src`
- [ ] No code warnings: `pylint src/`
- [ ] Code formatted: `black src/`
- [ ] Type hints present: `mypy src/`
- [ ] Security scan passed: `safety check`
- [ ] No hardcoded secrets: `git secret scan`

### Functionality

- [ ] Dry-run tested for 24+ hours
- [ ] All trading pairs validated
- [ ] Market data fetch working
- [ ] AI estimates reasonable
- [ ] Kelly Criterion calculations correct
- [ ] ML model retraining functional

### Performance

- [ ] API response time < 500ms (p95)
- [ ] Database queries < 100ms (p95)
- [ ] Memory usage stable (no leaks)
- [ ] CPU usage < 80% under normal load
- [ ] Database connections pooled

### Security

- [ ] All secrets in environment variables
- [ ] HTTPS/TLS enabled
- [ ] Rate limiting configured
- [ ] Input validation complete
- [ ] Error messages don't leak info
- [ ] Audit logging enabled

### Operations

- [ ] Health checks implemented
- [ ] Backups tested and restored
- [ ] Monitoring alerts configured
- [ ] Incident response plan documented
- [ ] Runbooks for common issues
- [ ] Team trained on operations

### Final Steps

- [ ] Peer code review completed
- [ ] Security review completed
- [ ] Dry-run P&L analyzed
- [ ] Risk committee approval obtained
- [ ] Insurance/liability verified
- [ ] Go-live approved

---

## Running Tests in CI/CD

### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: testpass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-cov pytest-mock
      
      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:testpass@localhost/wealth_builder_test
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: pytest --cov=src --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Test Execution Summary

```bash
# Quick test (5 minutes)
pytest -x -q

# Full test suite (30 minutes)
pytest --cov=src -v

# With live API calls (requires keys)
pytest -m integration

# Before production deployment
pytest -v && docker-compose -f docker-compose.test.yml up -d && sleep 3600 && docker-compose -f docker-compose.test.yml logs agent | grep -E "ERROR|exception"
```

---

**Next:** Follow [SECURITY.md](SECURITY.md) for production security hardening.
