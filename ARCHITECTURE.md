# Architecture Guide - AI Agent Wealth Builder

**System design, components, and data flow**

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI Agent Wealth Builder                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Trading Agent (Main Loop)             │  │
│  │  - Runs on 10-minute intervals (configurable)           │  │
│  │  - Orchestrates entire trading cycle                    │  │
│  │  - Manages error handling & retry logic                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│           │                    │                    │           │
│           ↓                    ↓                    ↓           │
│  ┌─────────────────┐  ┌────────────────┐  ┌──────────────┐    │
│  │ Market Fetcher  │  │ AI Analyzer    │  │ ML Trainer   │    │
│  │ (Polymarket API)│  │ (GPT-4)        │  │ (Scikit-learn)    │
│  └─────────────────┘  └────────────────┘  └──────────────┘    │
│           │                    │                    │           │
│           │ Market Data        │ Probability       │ Model     │
│           │ (200+ markets)     │ Estimates         │ Updates   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │        Trade Execution (Kelly Criterion)               │  │
│  │  - Validates market conditions                         │  │
│  │  - Calculates optimal position sizing                  │  │
│  │  - Executes via Polymarket protocol                    │  │
│  │  - Records in database                                 │  │
│  └─────────────────────────────────────────────────────────┘  │
│           │                                                   │
│           ↓                                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │            PostgreSQL Database                          │  │
│  │  - Trades table (executed trades & outcomes)           │  │
│  │  - Positions table (open positions)                    │  │
│  │  - Markets table (market data snapshot)                │  │
│  │  - ML models table (trained models & accuracy)         │  │
│  │  - Audit log (all system changes)                      │  │
│  └─────────────────────────────────────────────────────────┘  │
│           │                                                   │
│           ↓                                                   │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │         API Dashboard & Monitoring                      │  │
│  │  - Port 8000 (REST endpoints)                          │  │
│  │  - Health check (/health)                              │  │
│  │  - Portfolio metrics (/api/portfolio)                  │  │
│  │  - Recent trades (/api/trades)                         │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

External Services:
  [Polymarket Protocol] ← API for market data & trade execution
  [OpenAI] ← GPT-4 for probability estimation
  [Polygon Network] ← Web3 blockchain interactions (if applicable)
```

---

## Component Architecture

### 1. Entry Point: `main.py`

**Responsibilities:**
- Initialize application
- Setup database connection
- Start event scheduler
- Run infinite trading loop

**Code Flow:**
```python
main()
  ├─ init_database()              # Create tables if needed
  ├─ setup_logging()              # Configure JSON logging
  ├─ create_agent()               # Initialize Agent instance
  └─ start_scheduler()            # Begin trading cycles
      └─ schedule_task(run_trading_cycle, interval=10m)
          └─ Loop: Every 10 minutes, call run_trading_cycle()
```

**Configuration:**
- `CYCLE_INTERVAL_MINUTES` - How often to trade (default: 10)
- `DRY_RUN` - Simulate only, don't execute (default: true)
- `LOG_LEVEL` - Logging verbosity (default: INFO)

---

### 2. Market Fetcher: `src/market_fetcher.py`

**Purpose:** Fetch current market data from Polymarket

**Input:**
- Polymarket API endpoint
- Market filters (liquidity minimum, volume threshold)

**Output:**
```python
{
    'id': 'market_unique_id',
    'title': 'Will BTC reach $100k by end of 2025?',
    'description': 'Long-form market description',
    'yes_price': 0.65,          # Probability market assigns to YES
    'no_price': 0.35,           # Probability market assigns to NO
    'liquidity': 500000,        # Total liquidity in USD
    'volume_24h': 150000,       # Volume in last 24h
    'is_resolved': False,       # Market closure status
    'closing_date': '2025-12-31T23:59:59Z'
}
```

**Key Functions:**
- `fetch_markets()` - Get top 200 markets by liquidity
- `fetch_market(market_id)` - Get specific market details

**Rate Limiting:**
- Max 60 requests/minute to Polymarket API
- Automatic backoff on 429 (Too Many Requests)

---

### 3. AI Analyzer: `src/ai_analyzer.py`

**Purpose:** Use GPT-4 to estimate true market probability

**Input:**
```python
market = {
    'title': 'Will ETH reach $5000 by mid-2025?',
    'description': 'Ethereum price prediction',
    'yes_price': 0.42
}
```

**Processing:**
1. Extract market question and context
2. Send to GPT-4 with prompt including:
   - Historical ETH prices
   - Current market conditions
   - Base rate / reference class
3. Parse probability from response
4. Validate (must be 0.0-1.0)

**Output:**
```python
{
    'market_id': 'market_123',
    'ai_estimated_probability': 0.65,  # What GPT-4 thinks
    'market_implied_probability': 0.42, # What market thinks
    'confidence_score': 0.72,           # How confident is AI
    'analyzed_at': '2025-02-17T10:00:00Z'
}
```

**Edge Cases:**
- Handles ambiguous questions
- Falls back to market price if AI response invalid
- Includes hedging language in prompts for uncertainty

**Cost:**
- ~$0.005 per market analysis
- 100 markets = ~$0.50 per cycle
- ~3 cycles/hour = ~$36/day

---

### 4. Trade Executor: `src/trade_executor.py`

**Purpose:** Execute trades using Kelly Criterion position sizing

**Input:**
```python
opportunity = {
    'market_id': 'market_123',
    'market_price': 0.42,           # Current market price
    'ai_estimate': 0.65,            # AI probability
    'action': 'BUY',                # BUY YES if AI > market, else SELL
    'confidence': 0.72,             # AI confidence
    'historical_accuracy': 0.58     # Win rate on similar markets
}
```

**Processing:**

1. **Edge Case Validation:**
   - Is market liquid enough? (min $100k liquidity)
   - Is confidence above threshold? (default 55%)
   - Is position within max size? (default $500)
   - Are we below max drawdown? (default -10%)

2. **Kelly Criterion Calculation:**
   ```
   Kelly% = (Win Rate × Avg Win - Loss Rate × Avg Loss) / Avg Win
   Position Size = Kelly% × Account × Kelly Fraction
   
   Example:
   - Win rate: 60%, Avg win: 1.5x, Avg loss: 1.0x
   - Kelly = (0.60 × 1.5 - 0.40 × 1.0) / 1.5 = 0.40
   - With Kelly Fraction 0.25: Position = 0.40 × 0.25 × $10,000 = $1,000
   - Capped at max position size ($500 default)
   ```

3. **Execute Trade:**
   - If DRY_RUN: Log what would happen
   - If Live: Execute on Polymarket via Web3.py
   - Record trade in database

**Output:**
```python
{
    'trade_id': 'trade_456',
    'market_id': 'market_123',
    'action': 'BUY',
    'amount_usd': 500,
    'entry_price': 0.42,
    'kelly_fraction': 0.22,
    'status': 'EXECUTED' or 'DRY_RUN',
    'timestamp': '2025-02-17T10:00:15Z'
}
```

**Risk Controls:**
- Max drawdown protection: Stop trading if down > 10%
- Min confidence filter: Only trade if AI confidence > 55%
- Position size cap: Max $500 per trade (config)
- Max daily loss: Stop if any position loses > 50%

---

### 5. ML Trainer: `src/ml_trainer.py`

**Purpose:** Continuously improve AI probability estimates with ML

**Input:**
- Resolved trades (markets that closed)
- Historical market data
- Previous ML model

**Processing:**

1. **Data Collection:**
   ```python
   Collect from database:
   - 50+ resolved trades minimum
   - Features: market_liquidity, volume, time_to_close, etc.
   - Labels: Was AI correct? (1 = correct, 0 = incorrect)
   ```

2. **Feature Engineering:**
   ```python
   Features = [
       market_liquidity,          # Bigger is more liquid
       volume_24h,                # More volume = easier to trade
       time_to_close_days,        # How long until market closes
       market_implied_prob,       # Current probability
       ai_confidence,             # Model's own confidence
       base_rate,                 # Historical accuracy on similar markets
       recency_bias               # Recent trends vs long-term
   ]
   ```

3. **Model Training:**
   ```python
   from sklearn.ensemble import RandomForestClassifier
   
   model = RandomForestClassifier(
       n_estimators=100,
       max_depth=10,
       min_samples_split=5
   )
   
   model.fit(X_train, y_train)
   accuracy = model.score(X_test, y_test)
   ```

4. **Model Evaluation:**
   ```python
   Metrics tracked:
   - Accuracy: How often AI predicted correctly
   - Precision: When AI says "high prob", is it right?
   - Recall: Does AI catch all high-probability events?
   - F1: Balanced accuracy metric
   ```

**Output:**
```python
{
    'model_version': 'ml_model_v2.joblib',
    'trained_at': '2025-02-17T18:00:00Z',
    'samples_used': 125,
    'accuracy_score': 0.68,
    'precision_score': 0.71,
    'recall_score': 0.64,
    'f1_score': 0.67,
    'improvement_vs_previous': '+3%'
}
```

**Retraining Schedule:**
- **Daily:** If 50+ new resolved trades available
- **Manual:** Can be triggered immediately
- **Auto-archive:** Keep last 10 models for rollback

---

### 6. Models (Database Schema): `src/models.py`

**PostgreSQL Tables:**

#### `markets` Table
```sql
CREATE TABLE markets (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    yes_price DECIMAL(5,4),
    no_price DECIMAL(5,4),
    liquidity INTEGER,
    volume_24h INTEGER,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    correct_outcome TEXT,  -- 'YES', 'NO', or 'INVALID'
    fetched_at TIMESTAMP DEFAULT NOW()
);
```

#### `trades` Table
```sql
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    market_id TEXT REFERENCES markets(id),
    action TEXT,  -- 'BUY' or 'SELL'
    amount_usd DECIMAL(10,2),
    entry_price DECIMAL(5,4),
    exit_price DECIMAL(5,4),
    pnl_pct DECIMAL(6,2),
    ai_estimated_probability DECIMAL(5,4),
    market_implied_probability DECIMAL(5,4),
    kelly_fraction DECIMAL(5,4),
    status TEXT,  -- 'DRY_RUN', 'EXECUTED', 'CLOSED'
    executed_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP,
    resolved_at TIMESTAMP
);
```

#### `positions` Table
```sql
CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    trade_id TEXT REFERENCES trades(id),
    market_id TEXT REFERENCES markets(id),
    amount_usd DECIMAL(10,2),
    entry_price DECIMAL(5,4),
    current_price DECIMAL(5,4),
    unrealized_pnl DECIMAL(10,2),
    opened_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP
);
```

#### `ml_models` Table
```sql
CREATE TABLE ml_models (
    id TEXT PRIMARY KEY,
    version TEXT,
    samples_used INTEGER,
    accuracy_score DECIMAL(5,3),
    precision_score DECIMAL(5,3),
    recall_score DECIMAL(5,3),
    f1_score DECIMAL(5,3),
    trained_at TIMESTAMP,
    deployed_at TIMESTAMP,
    archived_at TIMESTAMP
);
```

#### `audit_log` Table
```sql
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    action TEXT,
    table_name TEXT,
    record_id TEXT,
    old_values JSONB,
    new_values JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by TEXT
);
```

---

## Data Flow Diagram

### Single Trading Cycle (10 minutes)

```
START CYCLE
   ↓
[1] Fetch Markets
   ├─ Call Polymarket API
   ├─ Get 200+ active markets
   │   (liquidity >= $100k, volume >= $10k)
   └─ Store in memory
   ↓
[2] Analyze Markets (Parallel)
   ├─ For each market:
   │  ├─ Call GPT-4 API
   │  ├─ Get AI probability estimate
   │  ├─ Compare vs market price
   │  └─ Identify opportunities (diff > 10%)
   └─ Collect opportunities list
   ↓
[3] Filter Opportunities
   ├─ Min confidence: 55%
   ├─ Min liquidity: $100k
   ├─ Not already holding
   └─ Sorted by confidence
   ↓
[4] Execute Trades
   └─ For each opportunity (top 5-10):
      ├─ Calculate Kelly position size
      ├─ Check risk limits
      ├─ Execute on Polymarket
      ├─ Record in database
      └─ Log event
   ↓
[5] Update Portfolio
   ├─ Calculate current P&L
   ├─ Check open positions
   ├─ Update portfolio metrics
   └─ Generate dashboard update
   ↓
[6] Check for Model Retraining
   ├─ Count resolved trades since last train
   ├─ If >= 50: Trigger ML retraining
   └─ Update model version
   ↓
END CYCLE (wait 10 minutes)
```

### Continuous Processes

**Running in background between cycles:**
- Market price updates (real-time)
- Position P&L updates (every minute)
- Log aggregation
- Monitoring/health checks

---

## Deployment Architecture

### Local Development
```
Your Machine
├─ Docker Engine
│  ├─ PostgreSQL 16 (Port 5432)
│  ├─ Agent Container (Port 8000)
│  │  ├─ Python 3.11 process
│  │  ├─ Trading logic
│  │  └─ API endpoints
│  └─ Shared network
└─ logs/ & models/ directories (mounted volumes)
```

### Self-Hosted VPS
```
Ubuntu Server (VPS)
├─ Docker + Docker Compose
├─ PostgreSQL 16 (persistent volume)
├─ Agent container
├─ Systemd service (auto-restart)
├─ Nginx reverse proxy (optional)
└─ Monitoring agent (Prometheus, Grafana)
```

### AWS Deployment
```
AWS VPC
├─ ECS Cluster
│  └─ Task Definition
│     ├─ Agent container
│     └─ CloudWatch logging
├─ RDS PostgreSQL (managed database)
├─ Secrets Manager (API keys)
├─ CloudWatch (monitoring & alerts)
└─ ECR repository (container images)
```

---

## Key Design Decisions

### 1. Why PostgreSQL?
- **ACID compliance:** Reliable transaction consistency
- **JSON support:** Flexible schema for market data
- **Full-text search:** Search market descriptions
- **Row-level security:** Fine-grained access control
- **Managed versions:** Available as AWS RDS, Heroku Postgres, etc.

### 2. Why GPT-4 (not GPT-3.5)?
- **Reasoning:** GPT-4 better at complex probability estimation
- **Accuracy:** ~15% better on market prediction tasks
- **Cost trade-off:** GPT-4 = $0.005/query vs GPT-3.5 = $0.0005/query
- **Justification:** Small cost for better accuracy on real money decisions

### 3. Why Kelly Criterion?
- **Theoretical optimal:** Maximizes long-term growth rate
- **Risk-aware:** Reduces position size when uncertain
- **Adaptive:** Scales based on historical performance
- **Conservative:** We use 25% Kelly (not full Kelly) for safety

### 4. Why scikit-learn ML (not neural networks)?
- **Interpretability:** Can understand why model makes predictions
- **Data efficiency:** Works with <200 samples; NNs need thousands
- **Stability:** No training instability like neural nets
- **Deployability:** Can run in resource-constrained environments
- **Explainability:** Audit trail for regulatory compliance

### 5. Why dry-run mode?
- **Testing:** Can run with real API data without real capital
- **Debugging:** See what trades would execute without risk
- **Validation:** Verify system works before going live
- **Confidence building:** Track paper trading P&L first

---

## Failure Modes & Resilience

### Handled Failures

| Failure | Detection | Recovery |
|---------|-----------|----------|
| API timeout | No response within 5s | Retry with exponential backoff (max 3x) |
| Market unavailable | 404 response | Skip market, continue with others |
| Database connection lost | psycopg2 exception | Reconnect with retry logic |
| Insufficient balance | Pre-trade validation | Skip trade, log warning |
| ML model corruption | Model load failure | Fallback to previous version |
| Memory leak | RSS > 500MB | Restart container via health check |
| High drawdown | Portfolio down > 10% | Stop all new trades, log alert |

### Unhandled (System Shutdown)

| Failure | Impact | Prevention |
|---------|--------|-----------|
| Hardware failure | Agent stops | Running on VPS with auto-restart |
| Severe database corruption | Data loss | Automated backups (hourly) |
| API key compromised | Unauthorized trading | Key rotation, audit logs |
| Network partition | Agent isolated | Health check detects, alerts team |

---

## Performance Characteristics

**Single Trading Cycle (10 minutes):**
- Fetch ~200 markets: 2-3 seconds
- Analyze with GPT-4: 60 seconds (200 calls × 300ms)
- Execute trades: 2-5 seconds per trade
- Database operations: <500ms
- **Total:** 1-2 minutes, 8 min idle time

**Database Operations:**
- Average query: <50ms
- Peak (during analysis): <200ms
- Connection pool: 10 connections
- Max concurrent: 2 (main loop + API)

**API Response Times:**
- Health check: <10ms
- Portfolio metrics: <100ms
- Recent trades: <200ms (without pagination)
- Dashboard: <500ms (if many trades)

**Resource Usage (steady state):**
- CPU: 5-15% (mostly idle)
- Memory: 150-200 MB
- Disk: 1-2 GB (database grows ~10MB/month)
- Network: <1 Mbps (bursting to 5 Mbps during API calls)

---

## Scalability Limits

### Current Architecture (Single Container)

| Metric | Limit | When Hit |
|--------|-------|----------|
| Markets analyzed/cycle | 500 | API rate limit (60 req/min) |
| Trades/cycle | 10 | Time limit (can't analyze >500 markets in 10 min) |
| Open positions | 100 | Database index performance |
| Daily cycles | 144 | Single container CPU (10m interval) |
| Historical trades | 10 million | Database storage (SSD recommended) |

### Scaling Strategies

1. **Horizontal Scaling:**
   - Multiple agent instances sharing database
   - Market pool coordination (each handles subset)
   - Requires distributed locking

2. **Vertical Scaling:**
   - More CPU cores → Faster GPT-4 batch requests
   - More memory → Larger in-memory caches
   - NVMe SSD → Faster database queries

3. **Async Processing:**
   - Queue trades asynchronously
   - Separate market fetch from analysis
   - Background ML retraining

---

## Security Architecture

```
External ← API Key Auth ← Application ← Secret Management
           ↓
    Rate Limiting
           ↓
    Input Validation
           ↓
Database (Encrypted at rest)
           ↓
Audit Logs (Append-only)
```

**Key Security Controls:**
- All secrets in environment variables
- Database connections use strongest ciphers
- Audit trail tracks all trades
- Rate limiting prevents abuse
- Input validation on all APIs

---

## Monitoring & Observability

```
Application Logs
    ↓ JSON format
    ↓
Log Aggregation (ELK, Datadog, etc.)
    ↓
Dashboard (Grafana)
    ↓
Alerts (Slack, Email)

Metrics
    ↓
Prometheus
    ↓
Grafana
    ↓
Dashboards & Alerts
```

**Key metrics tracked:**
- Trading cycle health (execute every 10m)
- P&L (daily, weekly, monthly)
- AI accuracy (trending)
- System resource usage
- API error rates

---

## Evolution & Future

**Phase 1 (Current):**
- Single agent
- Manual configuration
- Basic ML model

**Phase 2 (Next):**
- Multi-agent with communication
- Automated parameter tuning
- Advanced ML (ensemble models)
- Live trading dashboard

**Phase 3 (Future):**
- Cross-market arbitrage
- Sentiment analysis integration
- Ensemble of multiple AIs
- Self-improving system

---

**Related:** [README.md - Architecture](README.md), [DEPLOYMENT.md](DEPLOYMENT.md), [MONITORING.md](MONITORING.md)
