# Monitoring & Operations Guide - AI Agent Wealth Builder

**Production monitoring and operational excellence**

---

## Overview

This guide covers:
- Real-time monitoring dashboards
- Health checks and alerting
- Performance tracking
- Incident response procedures
- Maintenance schedules

---

## Table of Contents

1. [Health Checks](#health-checks)
2. [Metrics & Dashboards](#metrics--dashboards)
3. [Alerting](#alerting)
4. [Logs & Observability](#logs--observability)
5. [Performance Analysis](#performance-analysis)
6. [Maintenance](#maintenance)

---

## Health Checks

### 1. Application Health Endpoint

```python
# src/health.py
from datetime import datetime, timedelta
from flask import jsonify
import psycopg2
import os

def health_check():
    """Comprehensive health status"""
    checks = {
        'timestamp': datetime.utcnow().isoformat(),
        'status': 'healthy',
        'version': os.getenv('APP_VERSION', '1.0.0'),
        'checks': {}
    }
    
    # Database connectivity
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.close()
        conn.close()
        checks['checks']['database'] = {'status': 'ok', 'latency_ms': 0}
    except Exception as e:
        checks['checks']['database'] = {'status': 'error', 'message': str(e)}
        checks['status'] = 'degraded'
    
    # OpenAI connectivity
    try:
        import openai
        models = openai.Model.list()
        checks['checks']['openai'] = {'status': 'ok', 'models': len(models.data)}
    except Exception as e:
        checks['checks']['openai'] = {'status': 'error', 'message': str(e)}
        checks['status'] = 'degraded'
    
    # Polymarket API
    try:
        import requests
        r = requests.get('https://clob.polymarket.com/markets', timeout=5)
        checks['checks']['polymarket'] = {'status': 'ok', 'response_ms': r.elapsed.total_seconds() * 1000}
    except Exception as e:
        checks['checks']['polymarket'] = {'status': 'error', 'message': str(e)}
        checks['status'] = 'degraded'
    
    # Trading cycle status
    try:
        from src.models import get_last_cycle_status
        last_cycle = get_last_cycle_status()
        time_since_cycle = (datetime.utcnow() - last_cycle['executed_at']).total_seconds() / 60
        
        max_interval = int(os.getenv('CYCLE_INTERVAL_MINUTES', 10)) + 5
        if time_since_cycle > max_interval:
            checks['checks']['trading_cycle'] = {
                'status': 'error',
                'message': f'No cycle executed in {time_since_cycle:.0f} minutes'
            }
            checks['status'] = 'unhealthy'
        else:
            checks['checks']['trading_cycle'] = {
                'status': 'ok',
                'last_cycle': last_cycle['executed_at'].isoformat(),
                'minutes_ago': round(time_since_cycle, 1)
            }
    except Exception as e:
        checks['checks']['trading_cycle'] = {'status': 'unknown', 'message': str(e)}
    
    status_code = 200 if checks['status'] == 'healthy' else (503 if checks['status'] == 'unhealthy' else 200)
    return jsonify(checks), status_code

# Register health endpoint
@app.route('/health', methods=['GET'])
def app_health():
    return health_check()

@app.route('/healthz', methods=['GET'])  # Kubernetes compatibility
def kube_health():
    checks, code = health_check()
    return jsonify(checks.get_json()[0]), code
```

### 2. Docker Health Check

```dockerfile
# In Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

### 3. Monitor Health Status

```bash
# Docker health status
docker-compose ps
# Shows health status: starting, healthy, unhealthy

# Check specific container
docker inspect --format='{{.State.Health.Status}}' wealth_builder_agent_1

# Monitor in real-time
watch -n 5 'docker ps --format "table {{.Names}}\t{{.Status}}"'
```

---

## Metrics & Dashboards

### 1. Key Performance Indicators

```python
# src/metrics.py
from datetime import datetime, timedelta
from src.models import db

class TradingMetrics:
    """Calculate all trading metrics"""
    
    @staticmethod
    def get_daily_summary(days_back=1):
        """Daily P&L and statistics"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        trades = db.session.query(Trade).filter(
            Trade.executed_at >= cutoff_date
        ).all()
        
        if not trades:
            return {'trades': 0, 'pnl': 0, 'win_rate': 0}
        
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.pnl_pct > 0])
        total_pnl = sum(t.pnl_pct for t in trades)
        
        return {
            'date': cutoff_date.date().isoformat(),
            'trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate_pct': round((winning_trades / total_trades * 100), 1),
            'total_pnl_pct': round(total_pnl, 2),
            'avg_pnl_pct': round(total_pnl / total_trades, 2),
            'max_win_pct': round(max(t.pnl_pct for t in trades), 2),
            'max_loss_pct': round(min(t.pnl_pct for t in trades), 2),
        }
    
    @staticmethod
    def get_portfolio_metrics():
        """Current portfolio status"""
        from src.models import Position
        
        positions = db.session.query(Position).filter(
            Position.closed_at.is_(None)
        ).all()
        
        total_capital = 10000  # From config
        open_positions_value = sum(p.current_value for p in positions)
        closed_pnl = db.session.query(func.sum(Trade.pnl)).scalar() or 0
        
        return {
            'total_capital': total_capital,
            'open_positions': len(positions),
            'open_positions_value': round(open_positions_value, 2),
            'closed_pnl': round(closed_pnl, 2),
            'current_drawdown_pct': round(
                (open_positions_value - total_capital) / total_capital * 100, 2
            ),
            'portfolio_value': round(total_capital + closed_pnl, 2),
        }
    
    @staticmethod
    def get_ai_accuracy():
        """AI probability estimation accuracy"""
        resolved_trades = db.session.query(Trade).filter(
            Trade.resolved_at.isnot(None)
        ).all()
        
        if not resolved_trades:
            return {'resolved_trades': 0}
        
        correct_predictions = 0
        for trade in resolved_trades:
            ai_prob = trade.ai_estimated_probability
            actual = 1 if trade.was_correct else 0
            
            # Consider prediction correct if within 20% confidence
            if abs(ai_prob - actual) <= 0.2:
                correct_predictions += 1
        
        return {
            'resolved_trades': len(resolved_trades),
            'correct_predictions': correct_predictions,
            'ai_accuracy_pct': round(
                (correct_predictions / len(resolved_trades) * 100), 1
            ),
        }
```

### 2. Prometheus Metrics

```python
# src/prometheus_metrics.py
from prometheus_client import Counter, Gauge, Histogram

# Counters
trades_executed = Counter('trades_executed_total', 'Total trades executed')
trades_won = Counter('trades_won_total', 'Total winning trades')
trades_lost = Counter('trades_lost_total', 'Total losing trades')

# Gauges
current_drawdown = Gauge('current_drawdown_pct', 'Current portfolio drawdown %')
portfolio_value = Gauge('portfolio_value_usd', 'Current portfolio value')
open_positions = Gauge('open_positions_count', 'Number of open positions')

# Histograms
trade_pnl = Histogram('trade_pnl_pct', 'Trade P&L in percent')
cycle_duration = Histogram('cycle_duration_seconds', 'Trading cycle execution time')
ai_confidence = Histogram('ai_confidence_score', 'AI confidence on trades')
```

### 3. Grafana Dashboard Setup

```json
{
  "dashboard": {
    "title": "Wealth Builder Trading Bot",
    "panels": [
      {
        "title": "Daily P&L",
        "targets": [{
          "expr": "sum(increase(trades_won_total[1d])) - sum(increase(trades_lost_total[1d]))"
        }]
      },
      {
        "title": "Portfolio Value",
        "targets": [{
          "expr": "portfolio_value_usd"  
        }]
      },
      {
        "title": "Win Rate",
        "targets": [{
          "expr": "sum(increase(trades_won_total[1d])) / sum(increase(trades_executed_total[1d])) * 100"
        }]
      },
      {
        "title": "Current Drawdown",
        "targets": [{
          "expr": "current_drawdown_pct"
        }]
      },
      {
        "title": "Open Positions",
        "targets": [{
          "expr": "open_positions_count"
        }]
      },
      {
        "title": "AI Accuracy (7d)",
        "targets": [{
          "expr": "ai_accuracy_pct"
        }]
      }
    ]
  }
}
```

### 4. Deploy Prometheus + Grafana

```bash
# Add to docker-compose.yml
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    depends_on:
      - agent

  grafana:
    image: grafana/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3000:3000"
    volumes:
      - grafana_storage:/var/lib/grafana
    depends_on:
      - prometheus

volumes:
  grafana_storage:
```

```bash
# Start monitoring stack
docker-compose up -d prometheus grafana

# Access dashboards
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000 (admin/admin)
```

---

## Alerting

### 1. Alert Rules

```yaml
# prometheus_rules.yml
groups:
  - name: trading_alerts
    rules:
      # Cycle not executing
      - alert: TradingCycleStalled
        expr: time() - max(timestamp(trading_cycle_executed_at)) > 900  # 15 min
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Trading cycle not executing"
          description: "No trading cycle in 15 minutes"
      
      # High drawdown
      - alert: HighDrawdown
        expr: current_drawdown_pct > -20
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "High portfolio drawdown"
          description: "Portfolio down {{ $value }}%"
      
      # Excessive drawdown (emergency)
      - alert: MaxDrawdownExceeded
        expr: current_drawdown_pct < -50
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Maximum drawdown exceeded!"
          description: "Emergency stop - drawdown {{ $value }}%"
      
      # Database errors
      - alert: DatabaseError
        expr: increase(database_errors_total[5m]) > 10
        labels:
          severity: critical
        annotations:
          summary: "Database errors"
          description: "{{ $value }} errors in 5 minutes"
      
      # API errors
      - alert: HighAPIErrorRate
        expr: (increase(api_errors_total[5m]) / increase(api_requests_total[5m])) > 0.05
        labels:
          severity: warning
        annotations:
          summary: "High API error rate"
          description: "{{ humanize $value }}% error rate"
      
      # Low AI confidence
      - alert: LowAIConfidence
        expr: avg(ai_confidence_score) < 0.55
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "AI confidence below 55%"
          description: "Average confidence: {{ humanize $value }}"
```

### 2. Slack Alerts

```python
# src/alerting.py
import requests
import os

def send_slack_alert(title, message, severity='info'):
    """Send alert to Slack"""
    webhook_url = os.getenv('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return
    
    color_map = {
        'info': '#36a64f',
        'warning': '#ff9900',
        'critical': '#ff0000'
    }
    
    payload = {
        'attachments': [{
            'color': color_map.get(severity, '#36a64f'),
            'title': title,
            'text': message,
            'ts': int(datetime.utcnow().timestamp()),
        }]
    }
    
    requests.post(webhook_url, json=payload)

# Usage
def monitor_drawdown():
    current_dd = get_current_drawdown()
    max_dd = get_max_drawdown_limit()
    
    if current_dd < max_dd:
        send_slack_alert(
            'Critical: Max Drawdown Exceeded',
            f'Portfolio at {current_dd}% (max: {max_dd}%)',
            severity='critical'
        )
```

### 3. Email Alerts

```python
import smtplib
from email.mime.text import MIMEText

def send_email_alert(to_email, subject, message):
    """Send alert via email"""
    msg = MIMEText(message)
    msg['Subject'] = subject
    msg['From'] = os.getenv('ALERT_EMAIL_FROM')
    msg['To'] = to_email
    
    smtp = smtplib.SMTP_SSL(
        os.getenv('SMTP_SERVER'),
        int(os.getenv('SMTP_PORT', 465))
    )
    smtp.login(
        os.getenv('SMTP_USER'),
        os.getenv('SMTP_PASSWORD')
    )
    smtp.send_message(msg)
    smtp.quit()

# Setup alerting
CRITICAL_ALERTS = [
    'TradingCycleStalled',
    'MaxDrawdownExceeded',
    'DatabaseError'
]

def configure_alerts():
    for alert in CRITICAL_ALERTS:
        # Send to email and Slack
        send_email_alert(
            os.getenv('ALERT_EMAIL'),
            f'Critical: {alert}',
            f'Your trading bot needs attention: {alert}'
        )
```

---

## Logs & Observability

### 1. Structured Logging

```python
# src/logging_config.py
import logging
import json
from pythonjsonlogger import jsonlogger

def setup_logging():
    """Configure JSON structured logging"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # File handler with JSON
    file_handler = logging.FileHandler('logs/app.json')
    formatter = jsonlogger.JsonFormatter()
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    return logger

# Usage
logger = setup_logging()

# Log trades with context
logger.info('trade_executed', extra={
    'trade_id': trade_id,
    'market_id': market_id,
    'action': 'BUY',
    'amount_usd': 500,
    'entry_price': 0.65,
    'ai_confidence': 0.72,
    'timestamp': datetime.utcnow().isoformat(),
})

# Query logs
# docker-compose exec agent tail -f logs/app.json | jq '.trade_executed'
```

### 2. Log Aggregation (ELK Stack)

```yaml
# docker-compose.yml additions
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.0.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
    ports:
      - "9200:9200"
    volumes:
      - elasticsearch_data:/usr/share/elasticsearch/data

  logstash:
    image: docker.elastic.co/logstash/logstash:8.0.0
    volumes:
      - ./logstash.conf:/usr/share/logstash/pipeline/logstash.conf
    ports:
      - "5000:5000"
    depends_on:
      - elasticsearch

  kibana:
    image: docker.elastic.co/kibana/kibana:8.0.0
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch

volumes:
  elasticsearch_data:
```

```bash
# Access Kibana
# http://localhost:5601

# Query example: Find all failed trades
GET /logs-*/_search
{
  "query": {
    "bool": {
      "must": [
        {"match": {"status": "FAILED"}},
        {"range": {"@timestamp": {"gte": "now-7d"}}}
      ]
    }
  },
  "aggs": {
    "failures_by_market": {
      "terms": {"field": "market_id"}
    }
  }
}
```

### 3. Log Queries

```bash
# Find all errors
docker-compose exec agent grep -i "error\|exception" logs/app.json | jq .

# Get last 100 trades
docker-compose exec agent tail -100 logs/app.json | jq 'select(.trade_executed)'

# Calculate win rate from logs
docker-compose exec agent cat logs/app.json | \
  jq 'select(.trade_executed) | .pnl_pct' | \
  awk '{if ($1 > 0) wins++; total++} END {print "Win rate: " wins/total * 100 "%"}'

# Monitor in real-time
docker-compose logs -f agent | grep "trade_executed"
```

---

## Performance Analysis

### 1. Daily Report

```python
# scripts/daily_report.py
from datetime import datetime, timedelta
from src.metrics import TradingMetrics
from src.alerting import send_slack_alert
import json

def generate_daily_report():
    """Generate comprehensive daily report"""
    
    yesterday = datetime.utcnow() - timedelta(days=1)
    metrics = TradingMetrics.get_daily_summary(days_back=1)
    portfolio = TradingMetrics.get_portfolio_metrics()
    ai_accuracy = TradingMetrics.get_ai_accuracy()
    
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'date': yesterday.date().isoformat(),
        'trading_metrics': metrics,
        'portfolio_metrics': portfolio,
        'ai_analytics': ai_accuracy,
    }
    
    # Save report
    with open(f"reports/{yesterday.date()}.json", 'w') as f:
        json.dump(report, f, indent=2)
    
    # Send summary to Slack
    message = f"""
Daily Trading Report - {yesterday.date()}

**Trading:**
- Trades: {metrics['trades']}
- Win Rate: {metrics['win_rate_pct']}%
- Daily P&L: {metrics['total_pnl_pct']}%
- Best Trade: +{metrics['max_win_pct']}%
- Worst Trade: {metrics['max_loss_pct']}%

**Portfolio:**
- Value: ${portfolio['portfolio_value']}
- Open Positions: {portfolio['open_positions']}
- Drawdown: {portfolio['current_drawdown_pct']}%

**AI Performance:**
- Resolved Trades: {ai_accuracy['resolved_trades']}
- Accuracy: {ai_accuracy['ai_accuracy_pct']}%
    """
    
    send_slack_alert('📊 Daily Report', message)
    
    return report

# Schedule daily at 8 AM
# Add to crontab:
# 0 8 * * * cd /opt/ai-agent && python scripts/daily_report.py
```

### 2. Weekly Analysis

```python
def generate_weekly_analysis():
    """Identify trends and patterns"""
    
    trades = db.session.query(Trade).filter(
        Trade.executed_at >= datetime.utcnow() - timedelta(days=7)
    ).all()
    
    # Group by market
    markets_stats = {}
    for trade in trades:
        if trade.market_id not in  markets_stats:
            markets_stats[trade.market_id] = {'count': 0, 'pnl': 0}
        markets_stats[trade.market_id]['count'] += 1
        markets_stats[trade.market_id]['pnl'] += trade.pnl_pct
    
    # Best and worst performing markets
    best_market = max(markets_stats.items(), key=lambda x: x[1]['pnl'])
    worst_market = min(markets_stats.items(), key=lambda x: x[1]['pnl'])
    
    # Time of day analysis
    hourly_stats = {}
    for trade in trades:
        hour = trade.executed_at.hour
        if hour not in hourly_stats:
            hourly_stats[hour] = {'count': 0, 'pnl': 0}
        hourly_stats[hour]['count'] += 1
        hourly_stats[hour]['pnl'] += trade.pnl_pct
    
    best_hour = max(hourly_stats.items(), key=lambda x: x[1]['pnl'])
    
    return {
        'best_market': best_market,
        'worst_market': worst_market,
        'best_hour': best_hour,
        'total_trades': len(trades)
    }
```

---

## Maintenance

### 1. Daily Tasks

```bash
#!/bin/bash
# scripts/daily_maintenance.sh

echo "[$(date)] Running daily maintenance..."

# Check health
docker-compose exec agent curl -s http://localhost:8000/health | jq .

# Backup database
docker-compose exec postgres pg_dump -U trading_user wealth_builder | \
  gzip > backups/daily_$(date +%Y%m%d).sql.gz

# Clean old logs (keep 30 days)
find logs/ -name "*.log" -mtime +30 -delete

# Generate daily report
python scripts/daily_report.py

# Check disk space
df -h | grep -E "/$|/var|/home"

# Restart containers (optional, if memory leak suspected)
# docker-compose restart agent

echo "[$(date)] Daily maintenance complete"
```

### 2. Weekly Tasks

```bash
#!/bin/bash
# scripts/weekly_maintenance.sh

echo "[$(date)] Running weekly maintenance..."

# Analyze database
docker-compose exec postgres psql -U trading_user wealth_builder <<EOF
REINDEX DATABASE wealth_builder;
ANALYZE;
EOF

# Generate weekly analysis
python scripts/generate_weekly_report.py

# Check for security updates
docker pull python:3.11-slim
docker pull postgres:16

# Review error logs
docker logs wealth_builder_agent_1 | grep -i error | tail -20

# Verify backups are valid
for backup in backups/*.sql.gz; do
  gunzip -t "$backup" && echo "$backup: OK" || echo "$backup: CORRUPTION"
done

echo "[$(date)] Weekly maintenance complete"
```

### 3. Monthly Tasks

```bash
# Crontab
0 3 1 * * cd /opt/ai-agent && bash scripts/monthly_maintenance.sh

# Scripts/monthly_maintenance.sh
- Professional security audit
- Database optimization and reindexing
- Capacity planning review
- AI model performance analysis (50+ data points)
- ML model retraining from scratch if drift detected
- Disaster recovery drill (restore from backup to test environment)
- Update dependencies (security patches)
```

### 4. Deployment Checklist

```markdown
## Pre-Deployment
- [ ] All tests passing
- [ ] Dry-run validation complete
- [ ] Security review done
- [ ] Load testing passed
- [ ] Database backup taken
- [ ] Incident response team briefed

## Deployment
- [ ] Version tag created (git tag v1.2.3)
- [ ] Build new Docker image
- [ ] Push image to registry
- [ ] Update docker-compose.yml with new version
- [ ] Pull new image: docker-compose pull
- [ ] Stop current: docker-compose stop agent
- [ ] Start new: docker-compose up -d agent
- [ ] Monitor startup logs: docker-compose logs -f agent

## Post-Deployment
- [ ] Health check passes
- [ ] Verify trading is executing
- [ ] Check dashboard loads
- [ ] Monitor error logs
- [ ] Set up continued monitoring
- [ ] Document changes
- [ ] Schedule rollback if needed
```

---

**Related Documents:**
- [SECURITY.md](SECURITY.md) - Security hardening
- [TESTING.md](TESTING.md) - Testing procedures
- [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment guide

---

**Last Updated:** 2025-02-17  
**Revision:** 1.0
