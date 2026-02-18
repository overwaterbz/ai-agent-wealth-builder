# AI Agent Wealth Builder 🤖💰

**Autonomous Trading Agent for Polymarket Prediction Markets**

An intelligent, self-improving AI trading system that autonomously analyzes Polymarket prediction markets, estimates fair probabilities using OpenAI, applies Kelly Criterion for position sizing, and executes trades with comprehensive security safeguards.

---

## 🎯 Features

- **AI-Powered Analysis** - Uses OpenAI to estimate fair market probabilities
- **Autonomous Trading** - Continuous cycle operation every 10 minutes (configurable)
- **ML-Enhanced Prediction** - Scikit-learn model with daily retraining on resolved outcomes
- **Smart Position Sizing** - Kelly Criterion calculations for optimal bet sizing
- **Security First** - Rate limiting, drawdown limits, audit logging, dry-run mode by default
- **Web3 Integration** - Direct blockchain transactions on Polygon
- **Comprehensive Logging** - Full audit trail of all decisions and trades
- **Monitoring Dashboard** - Real-time performance metrics
- **PostgreSQL Backend** - Persistent storage for trades, outcomes, ML model state

---

## 📋 Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | OpenAI GPT-4 | Market analysis & probability estimation |
| **ML** | Scikit-learn | Probability adjustment & pattern recognition |
| **Database** | PostgreSQL | Trade history, outcomes, model state |
| **Blockchain** | Web3.py + Polygon | Direct market interactions |
| **Scheduling** | Schedule library | Autonomous cycle management |
| **API** | FastAPI (optional) | REST endpoints for monitoring/control |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database
- OpenAI API key
- Polygon private key (for live trading)

### Local Development

```bash
# Clone the repository
git clone https://github.com/yourusername/ai-agent-wealth-builder.git
cd ai-agent-wealth-builder

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Set up environment variables (copy template and edit)
cp .env.example .env
# Edit .env with your keys

# Run in dry-run mode (default, simulated trades)
python main.py

# Run in live trading mode (CAREFUL!)
DRY_RUN=false python main.py
```

---

## 🐳 Docker Deployment

### Quick Start with Docker Compose

```bash
# Start PostgreSQL + Agent
docker-compose up -d

# View logs
docker-compose logs -f agent

# Stop everything
docker-compose down
```

### Production Docker Deployment

```bash
# Build image
docker build -t ai-agent-wealth-builder:latest .

# Run with environment variables
docker run -d \
  --name wealth-agent \
  -e DATABASE_URL="postgresql://user:pass@db:5432/trading_db" \
  -e OPENAI_API_KEY="sk-..." \
  -e POLYGON_PRIVATE_KEY="0x..." \
  -e DRY_RUN="false" \
  ai-agent-wealth-builder:latest
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file (or use `.env.example` as template):

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/wealth_builder

# OpenAI
OPENAI_API_KEY=sk-your-openai-key-here

# Web3 / Polymarket
POLYGON_PRIVATE_KEY=0xyour_private_key_here
POLYGON_RPC_URL=https://polygon-rpc.com

# Trading Config
DRY_RUN=true                    # true = simulated, false = live trading
CYCLE_INTERVAL_MINUTES=10       # How often to run trading cycle
DASHBOARD_INTERVAL_MINUTES=30   # How often to update dashboard
MAX_DRAWDOWN_PCT=10             # Pause trading if drawdown exceeds this
KELLY_FRACTION=0.25             # Kelly criterion fraction (0-1)

# API (if using monitoring endpoint)
API_PORT=8000
API_HOST=0.0.0.0

# Logging
LOG_LEVEL=INFO
AUDIT_LOG_FILE=logs/audit.log
```

### Example Configurations

**Development (Dry Run):**
```bash
DRY_RUN=true
CYCLE_INTERVAL_MINUTES=5
LOG_LEVEL=DEBUG
```

**Staging (Live with Limits):**
```bash
DRY_RUN=false
CYCLE_INTERVAL_MINUTES=30
MAX_DRAWDOWN_PCT=5
KELLY_FRACTION=0.1
```

**Production (Live):**
```bash
DRY_RUN=false
CYCLE_INTERVAL_MINUTES=10
MAX_DRAWDOWN_PCT=10
KELLY_FRACTION=0.25
LOG_LEVEL=INFO
```

---

## 📂 Project Structure

```
ai-agent-wealth-builder/
├── main.py                    # Entry point / scheduler
├── pyproject.toml             # Project metadata & dependencies
├── Dockerfile                 # Container image
├── docker-compose.yml         # Local dev environment
├── .env.example               # Environment template
├── README.md                  # This file
├── src/
│   ├── agent.py              # Main trading logic
│   ├── ai_analyzer.py        # OpenAI integration
│   ├── market_fetcher.py     # Polymarket data fetching
│   ├── trade_executor.py     # Trade execution & Kelly Criterion
│   ├── ml_trainer.py         # ML model training/prediction
│   ├── models.py             # Database models (SQLAlchemy)
│   ├── security.py           # Rate limiting, audit logging
│   ├── dashboard.py          # Monitoring dashboard
│   └── __init__.py
├── tests/
│   ├── test_agent.py         # Agent logic tests
│   ├── test_ml_trainer.py    # ML training tests
│   └── test_trade_executor.py
├── logs/                      # Audit logs & execution logs
└── models/
    └── trained/              # ML model artifacts
```

---

## 🔄 Trading Cycle

The agent follows this autonomous cycle every `CYCLE_INTERVAL_MINUTES`:

```
1. Fetch Market Data
   └─ Get latest Polymarket prediction markets
   
2. Estimate Probabilities
   └─ Use OpenAI to analyze market and estimate fair probability
   
3. Adjust with ML
   └─ If model exists, apply ML probability adjustment
   
4. Calculate Position Size
   └─ Use Kelly Criterion for optimal bet sizing
   
5. Check Security
   └─ Verify drawdown limits, rate limits, confidence
   
6. Execute Trade
   └─ BUY if expected value > threshold
   └─ SELL if position exists and EV < threshold
   
7. Log & Audit
   └─ Record decision, execution, outcome to database
```

---

## 🔒 Security Features

✅ **Dry-Run Mode (Default)** - Simulates trades without real money
✅ **Rate Limiting** - Prevents API abuse and excessive trading
✅ **Drawdown Protection** - Pauses trading if losses exceed MAX_DRAWDOWN_PCT
✅ **Confidence Threshold** - Only trades high-confidence predictions
✅ **Audit Logging** - Full trail of all decisions with timestamps
✅ **Error Handling** - Graceful failure recovery with automatic retry
✅ **Private Key Rotation** - Can be used with secure key management

---

## 📊 Monitoring & Logs

### Dashboard

View real-time metrics every 30 minutes (configurable):

```bash
# Terminal output shows:
- Total balance and P&L
- Open positions with entry prices
- Recent trades and outcomes
- Model performance metrics
- Trading statistics
```

### Audit Logs

Complete decision audit trail in `logs/audit.log`:

```
[2025-02-17 14:32:15] cycle_start | cycle_id: cycle_12345
[2025-02-17 14:32:16] fetch_markets | markets_found: 5, timestamp: 1708177935
[2025-02-17 14:32:22] ai_analysis | market: "Will BTC hit $100k?", fair_prob: 0.68, confidence: 0.92
[2025-02-17 14:32:23] ml_adjust | adjusted_prob: 0.71 (base: 0.68)
[2025-02-17 14:32:24] trade_executed | market_id: m123, action: BUY, amount: $50, expected_value: +$8.50
```

### Database Queries

Check trade history and outcomes:

```sql
-- Recent trades
SELECT id, market_id, action, amount_usd, 
       fair_probability, market_probability, 
       executed_at FROM trades ORDER BY executed_at DESC LIMIT 20;

-- Open positions
SELECT market_id, action, amount_usd, 
       entry_price, current_price, pnl_usd 
FROM positions WHERE closed_at IS NULL;

-- Model performance over time
SELECT DATE(created_at), AVG(accuracy), MIN(loss), MAX(accuracy)
FROM ml_runs GROUP BY DATE(created_at) ORDER BY DATE(created_at) DESC;
```

---

## 🚀 Deployment Options

### Option 1: GitHub + Self-Hosted VPS

```bash
# On your VPS:
git clone <your-repo>
cd ai-agent-wealth-builder

# Using Docker Compose:
docker-compose up -d

# Logs:
docker-compose logs -f agent
```

### Option 2: Vercel + External Worker

Vercel can run API endpoints for monitoring, but not long-running processes. For the agent daemon:

**Solution:** Use Vercel for monitoring dashboard/API + AWS Lambda/Cloud Run for agent execution

```typescript
// vercel/api/dashboard.ts - REST endpoint for metrics
export default async function handler(req, res) {
  const trades = await db.query('SELECT * FROM trades ORDER BY executed_at DESC LIMIT 20');
  const positions = await db.query('SELECT * FROM positions WHERE closed_at IS NULL');
  res.json({ trades, positions });
}
```

### Option 3: AWS / GCP / Azure

Use managed services:
- **Database:** AWS RDS / Cloud SQL (PostgreSQL)
- **Agent:** EC2 / Compute Engine / VM with Docker
- **Monitoring:** CloudWatch / Cloud Monitoring
- **Secrets:** AWS Secrets Manager / Cloud Secret Manager

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run specific test file
pytest tests/test_agent.py -v

# Run with coverage
pytest --cov=src --cov-report=html

# Test in dry-run mode (no real trades)
DRY_RUN=true pytest tests/
```

---

## 📈 Performance Metrics

Track these KPIs over time:

| Metric | Target | Current |
|--------|--------|---------|
| Win Rate | >55% | — |
| Avg Odds | 2.0+ | — |
| ROI (monthly) | 10%+ | — |
| Sharpe Ratio | 1.0+ | — |
| Max Drawdown | <10% | — |
| Trades/Day | 5-20 | — |

---

## 🐛 Troubleshooting

### Agent not starting

```bash
# Check logs
docker-compose logs agent

# Verify database connection
python -c "from src.models import init_db; init_db()"

# Check environment variables
env | grep -E "DATABASE_URL|OPENAI_API_KEY|POLYGON"
```

### Trades not executing

```bash
# Enable debug logging
LOG_LEVEL=DEBUG python main.py

# Check OpenAI API
openai.Model.list()

# Check Polymarket API
curl https://api.polymarket.com/markets | jq

# Verify POLYGON_PRIVATE_KEY format
python -c "from web3 import Web3; print(Web3.isAddress('0x...'))"
```

### Database connection errors

```bash
# Check PostgreSQL is running
docker-compose ps

# Connect directly
psql postgresql://user:pass@localhost:5432/wealth_builder

# Run migrations
python -c "from src.models import init_db; init_db()"
```

---

## 📚 API Reference (Optional)

If you deploy monitoring endpoints:

### GET /api/dashboard
Returns current trading dashboard data.

```bash
curl http://localhost:8000/api/dashboard
# Returns: { trades, positions, balance, pnl, win_rate, ... }
```

### GET /api/audits
Returns recent audit log entries.

```bash
curl http://localhost:8000/api/audits?limit=50
```

### POST /api/cycle
Manually trigger a trading cycle.

```bash
curl -X POST http://localhost:8000/api/cycle
```

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make changes and test (`pytest`)
4. Commit (`git commit -m "Add feature"`)
5. Push and create Pull Request

---

## ⚖️ License

MIT License - see LICENSE file

---

## ⚠️ Risk Disclaimer

**This is an autonomous trading system using real money (if DRY_RUN=false).** Past performance is not indicative of future results. Use at your own risk. Always test in dry-run mode first. Start with small amounts. Monitor regularly.

---

## 📞 Support

- **Issues:** Create an issue on GitHub
- **Docs:** See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed deployment guide
- **Security:** See [SECURITY.md](./SECURITY.md) for security best practices

---

**Happy Trading! 🚀📈**
