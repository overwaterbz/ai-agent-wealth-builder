# Quick Start - AI Agent Wealth Builder

**Get up and running in 5 minutes**

---

## Prerequisites

- Docker & Docker Compose installed
- API keys:
  - OpenAI (GPT-4)
  - Polygon / Polymarket account
  - (Optional) Vercel account for deployment

---

## 1. Clone & Setup

```bash
# Clone repository
git clone https://github.com/yourusername/ai-agent-wealth-builder.git
cd ai-agent-wealth-builder

# Copy environment template
cp .env.example .env

# Edit with your API keys
nano .env
# Add:
# - OPENAI_API_KEY=sk-your-key
# - POLYGON_PRIVATE_KEY=0x-your-key
# - DRY_RUN=true (start safe!)
```

---

## 2. Start Locally

```bash
# Start database and agent
docker-compose up -d

# Watch logs
docker-compose logs -f agent

# Wait for startup (30 seconds)
# Should see: "Starting trading cycle"
```

---

## 3. Verify It's Working

```bash
# Check health
curl http://localhost:8000/health

# Check trades
docker-compose exec postgres psql -U trading_user wealth_builder -c "
SELECT executed_at, action, amount_usd, entry_price 
FROM trades LIMIT 5;"

# Monitor dashboard
docker-compose logs -f agent | grep "Cycle complete"
```

---

## 4. Expected Output

```
agent_1 | 2025-02-17 10:00:00 INFO: Starting trading cycle #1
agent_1 | 2025-02-17 10:00:05 INFO: Fetched 200 markets
agent_1 | 2025-02-17 10:00:15 INFO: AI analysis complete: 5 opportunities
agent_1 | 2025-02-17 10:00:20 INFO: DRY RUN - Would BUY 100 USD at 0.65
agent_1 | 2025-02-17 10:01:00 INFO: Cycle complete - P&L: +0.5%
agent_1 | 2025-02-17 10:10:00 INFO: Starting trading cycle #2
```

If you see this, it's working! ✅

---

## 5. Test Configuration

| Parameter | Default | Adjust For... |
|-----------|---------|--------------|
| `DRY_RUN` | `true` | Set to `false` only after 24h testing |
| `CYCLE_INTERVAL_MINUTES` | `10` | Faster cycles = `5`, Slower = `60` |
| `CONFIDENCE_THRESHOLD` | `0.55` | More selective = `0.70`, Less = `0.50` |
| `MAX_POSITION_SIZE_USD` | `500` | Increase after confidence builds |
| `MAX_DRAWDOWN_PCT` | `10` | Safety limit if you want tighter risk |

---

## 6. Common Next Steps

### Test Longer (Recommended)
```bash
# Leave running for 24 hours in DRY_RUN=true
# Check: docker-compose logs -f agent
```

### Scale to Production
1. Stop containers: `docker-compose down`
2. Update `.env`: `DRY_RUN=false`
3. Deploy to VPS/AWS (see [DEPLOYMENT.md](DEPLOYMENT.md))
4. Enable monitoring ([MONITORING.md](MONITORING.md))

### Deploy to Vercel
See [DEPLOYMENT.md](DEPLOYMENT.md#vercel-deployment) section

---

## 7. Troubleshooting

**Agent not starting?**
```bash
docker-compose logs agent
# Check for errors, usually API keys
```

**Database connection error?**
```bash
# Rebuild
docker-compose down -v
docker-compose up -d
# Wait 10 seconds for PostgreSQL to be ready
```

**No trades executing?**
```bash
# Check markets are available
docker-compose exec agent python -c "
from src.market_fetcher import fetch_markets
markets = fetch_markets(limit=1)
print(f'Available markets: {len(markets)}')"
```

---

## 8. Next Documentation

- 📖 [README.md](README.md) - Full project documentation
- 🔒 [SECURITY.md](SECURITY.md) - Security hardening
- 🧪 [TESTING.md](TESTING.md) - Testing procedures
- 📊 [MONITORING.md](MONITORING.md) - Monitoring setup
- 🚀 [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
- 📋 [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) - Full documentation map

---

## 9. Support & Issues

For issues:
1. Check [Troubleshooting](README.md#troubleshooting-guide)
2. Review [MONITORING.md](MONITORING.md) for health checks
3. Check logs: `docker-compose logs -f agent`
4. Open GitHub issue with error output

---

## What's Next?

✅ **First 5 minutes:** Files extracted and running  
⏳ **Next 24 hours:** Leave in DRY_RUN testing mode  
⏳ **Day 2:** Review results and paper trading P&L  
⏳ **Day 3+:** Deploy to production with real capital (after proper review)

---

**Estimated time for full setup: 5 minutes**  
**Estimated time before production-ready: 48 hours**

Ready? → `docker-compose up -d` 🚀
