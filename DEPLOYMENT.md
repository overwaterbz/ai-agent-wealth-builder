# Deployment Guide - AI Agent Wealth Builder

**Complete guide for deploying to GitHub, Vercel, and self-hosted environments**

---

## Table of Contents

1. [GitHub Setup](#github-setup)
2. [Local Development](#local-development)
3. [Docker Deployment](#docker-deployment)
4. [Self-Hosted VPS](#self-hosted-vps)
5. [Vercel Deployment (Monitoring Only)](#vercel-deployment)
6. [AWS Deployment](#aws-deployment)
7. [Monitoring & Maintenance](#monitoring--maintenance)

---

## GitHub Setup

### 1. Initialize Repository

```bash
cd ai-agent-wealth-builder

# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit: AI Agent Wealth Builder"

# Add remote (replace with your GitHub repo URL)
git remote add origin https://github.com/yourusername/ai-agent-wealth-builder.git
git branch -M main
git push -u origin main
```

### 2. Add `.env` to `.gitignore`

Verify `.env` is in `.gitignore` (it should be):

```bash
# Confirm
grep "^\.env$" .gitignore  # Should print .env

# If not there, add it:
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Ensure .env is ignored"
git push
```

### 3. GitHub Secrets (for CI/CD)

Setup in GitHub repo settings:

**Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:
- `OPENAI_API_KEY` - Your OpenAI key
- `POLYGON_PRIVATE_KEY` - Your Polygon private key
- `DATABASE_URL` - Production database URL (for tests)

---

## Local Development

### Quick Start

```bash
# 1. Clone your repo
git clone https://github.com/yourusername/ai-agent-wealth-builder.git
cd ai-agent-wealth-builder

# 2. Create .env from template
cp .env.example .env
# Edit .env with your local values
nano .env  # or use VS Code

# 3. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 4. Install dependencies
pip install -e .

# 5. Initialize database
python -c "from src.models import init_db; init_db()"

# 6. Run in dry-run (safe) mode
python main.py
```

### Testing

```bash
# Run all tests
pytest

# Run specific test
pytest tests/test_agent.py -v

# Run with coverage
pytest --cov=src

# Test trading cycle (dry-run)
DRY_RUN=true python -c "from src.agent import run_trading_cycle; run_trading_cycle()"
```

---

## Docker Deployment

### Development with Docker Compose

**Fastest way to run locally:**

```bash
# 1. Create .env file
cp .env.example .env
# Edit .env - fill in your API keys

# 2. Start everything (builds image automatically)
docker-compose up -d

# 3. View logs
docker-compose logs -f agent

# 4. Monitor PostgreSQL
docker-compose exec postgres psql -U trading_user -d wealth_builder

# 5. Stop everything
docker-compose down

# 6. Clean up volumes (careful - deletes data)
docker-compose down -v
```

### Production Docker

**Build and push to Docker Hub:**

```bash
# Build image
docker build -t yourusername/ai-agent-wealth-builder:latest .

# Tag with version
docker tag yourusername/ai-agent-wealth-builder:latest yourusername/ai-agent-wealth-builder:1.0.0

# Push to Docker Hub
docker login  # Enter credentials
docker push yourusername/ai-agent-wealth-builder:latest
docker push yourusername/ai-agent-wealth-builder:1.0.0

# Run on server
docker run -d \
  --name wealth-agent \
  --restart always \
  -e DATABASE_URL="postgresql://user:pass@db.example.com:5432/wealth" \
  -e OPENAI_API_KEY="sk-..." \
  -e POLYGON_PRIVATE_KEY="0x..." \
  -e DRY_RUN="false" \
  -e LOG_LEVEL="INFO" \
  -v /data/logs:/app/logs \
  -v /data/models:/app/models/trained \
  yourusername/ai-agent-wealth-builder:latest
```

---

## Self-Hosted VPS

### Setup on Ubuntu 20.04+ VPS

#### Step 1: Server Prerequisites

```bash
# SSH to your server
ssh root@your.server.ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

#### Step 2: Clone Repository

```bash
# Create app directory
mkdir -p /opt/ai-agent
cd /opt/ai-agent

# Clone your repo
git clone https://github.com/yourusername/ai-agent-wealth-builder.git .

# Set permissions
sudo chown -R $USER:$USER /opt/ai-agent
chmod 755 /opt/ai-agent
```

#### Step 3: Configure Environment

```bash
# Create .env from template
cp .env.example .env

# Edit with your secrets
nano .env

# Restrict permissions (important for security)
chmod 600 .env

# Verify secrets are not visible in process list
cat .env  # Only you should see this
```

#### Step 4: Start Service

```bash
# Pull latest code
git pull origin main

# Start services
docker-compose up -d

# Verify running
docker-compose ps

# Check logs
docker-compose logs -f agent

# Test database
docker-compose exec postgres psql -U trading_user -d wealth_builder -c "SELECT COUNT(*) FROM trades;"
```

#### Step 5: Setup Auto-Start

Create systemd service to restart on reboot:

```bash
# Create service file
sudo tee /etc/systemd/system/ai-agent-wealth-builder.service > /dev/null <<EOF
[Unit]
Description=AI Agent Wealth Builder
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=$USER
WorkingDirectory=/opt/ai-agent
ExecStart=/usr/bin/docker-compose up -d
ExecStop=/usr/bin/docker-compose down
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable ai-agent-wealth-builder.service
sudo systemctl start ai-agent-wealth-builder.service

# Check status
sudo systemctl status ai-agent-wealth-builder.service
```

#### Step 6: Setup Monitoring

```bash
# Install monitoring tools
sudo apt install -y htop iotop nethogs

# Monitor resource usage
docker stats

# Monitor logs
docker-compose logs -f --tail=100
```

---

## Vercel Deployment

### Monitoring API Only (Agent runs elsewhere)

**Note:** Vercel cannot run long-running processes, so we use separate infrastructure for the agent. Vercel hosts the monitoring dashboard.

#### Create API Endpoint

```typescript
// vercel/api/dashboard.ts
import { VercelRequest, VercelResponse } from '@vercel/node';
import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export default async function handler(
  req: VercelRequest,
  res: VercelResponse
) {
  try {
    const result = await pool.query(`
      SELECT 
        COUNT(*) as total_trades,
        SUM(CASE WHEN action = 'BUY' THEN amount_usd ELSE -amount_usd END) as total_pnl,
        COUNT(DISTINCT DATE(executed_at)) as trading_days
      FROM trades
    `);

    res.status(200).json(result.rows[0]);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
```

#### Deploy to Vercel

```bash
# Create vercel.json
cat > vercel.json <<EOF
{
  "buildCommand": "npm run build",
  "outputDirectory": ".vercel/output",
  "functions": {
    "vercel/api/*.ts": {
      "runtime": "nodejs18.x"
    }
  },
  "env": {
    "DATABASE_URL": "@database_url",
    "OPENAI_API_KEY": "@openai_api_key"
  }
}
EOF

# Deploy
vercel --prod
```

---

## AWS Deployment

### Complete Setup with ECS + RDS

#### Architecture

```
┌─────────────────────────────────────┐
│         AWS Account                 │
├─────────────────────────────────────┤
│                                     │
│  ┌───────────────┐                 │
│  │   ECS Task    │ (Agent)          │
│  │  (Docker)     │                 │
│  └───────┬───────┘                 │
│          │                         │
│          ▼                         │
│  ┌───────────────┐                 │
│  │   RDS         │ (PostgreSQL)    │
│  │  (Database)   │                 │
│  └───────────────┘                 │
│                                     │
└─────────────────────────────────────┘
```

#### Step 1: Prepare ECR Image

```bash
# Create ECR repository
aws ecr create-repository --repository-name ai-agent-wealth-builder --region us-east-1

# Build and push
docker build -t ai-agent-wealth-builder:latest .

# Get AWS credentials
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Tag and push
docker tag ai-agent-wealth-builder:latest ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ai-agent-wealth-builder:latest
docker push ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ai-agent-wealth-builder:latest
```

#### Step 2: Create RDS Database

```bash
aws rds create-db-instance \
  --db-instance-identifier wealth-builder-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --master-username trading_user \
  --master-user-password YOUR_SECURE_PASSWORD \
  --allocated-storage 20 \
  --vpc-security-group-ids sg-YOUR_SECURITY_GROUP
```

#### Step 3: Create ECS Task Definition

```json
{
  "family": "ai-agent-wealth-builder",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "containerDefinitions": [
    {
      "name": "wealth-builder-agent",
      "image": "ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/ai-agent-wealth-builder:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "DRY_RUN",
          "value": "false"
        },
        {
          "name": "CYCLE_INTERVAL_MINUTES",
          "value": "10"
        }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:database-url"
        },
        {
          "name": "OPENAI_API_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:openai-key"
        },
        {
          "name": "POLYGON_PRIVATE_KEY",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:polygon-key"
        }
      ]
    }
  ]
}
```

#### Step 4: Run ECS Task

```bash
aws ecs create-service \
  --cluster wealth-builders-cluster \
  --service-name ai-agent-service \
  --task-definition ai-agent-wealth-builder \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}"
```

---

## Monitoring & Maintenance

### Health Checks

```bash
# Docker container health
docker-compose ps

# Database connectivity
docker-compose exec agent python -c "from src.models import init_db; init_db()"

# API health
curl http://localhost:8000/health

# Logs
docker-compose logs -f agent --tail 100
```

### Backup Strategy

```bash
# Backup database daily
docker-compose exec postgres pg_dump -U trading_user wealth_builder > backup_$(date +%Y%m%d).sql

# Upload to S3 (example)
aws s3 cp backup_*.sql s3://my-ai-agent-backups/

# Automated backup (add to crontab)
0 2 * * * cd /opt/ai-agent && docker-compose exec -T postgres pg_dump -U trading_user wealth_builder | gzip > backups/backup_$(date +\%Y\%m\%d_\%H\%M\%S).sql.gz
```

### Scaling Considerations

**Single Agent (Current):**
- CPU: 1-2 cores
- Memory: 512MB - 1GB
- Trades: ~5-20 per day
- Database: 500GB-1TB storage

**Multiple Agents (Future):**
- Each agent: separate container
- Shared PostgreSQL with read replicas
- Load balancer for API endpoints
- Message queue (RabbitMQ) for coordination

---

## Troubleshooting

### Agent not starting

```bash
# Check logs
docker-compose logs agent | grep ERROR

# Verify environment
docker-compose exec agent env | grep -E "OPENAI|POLYGON|DATABASE"

# Test database connection
docker-compose exec agent python -c "
from src.models import init_db
init_db()
print('Database OK')
"
```

### Trades not executing

```bash
# Enable debug logging
# Edit docker-compose.yml: LOG_LEVEL=DEBUG
# Restart: docker-compose restart

# Check OpenAI API
docker-compose exec agent python -c "import openai; print(openai.Model.list())"

# Check Polygon connection
docker-compose exec agent python -c "from web3 import Web3; w3 = Web3(); print(w3.is_connected())"
```

### Database errors

```bash
# Check disk space
docker-compose exec postgres df -h

# Check connection limits
docker-compose exec postgres psql -U trading_user wealth_builder -c "SELECT count(*) FROM pg_stat_activity;"

# Vacuum/analyze
docker-compose exec postgres psql -U trading_user wealth_builder -c "VACUUM ANALYZE;"
```

---

## Security Checklist

Before production:

- [ ] `.env` file is in `.gitignore`
- [ ] SSL/TLS enabled for database connections
- [ ] Firewalls configured (only necessary ports open)
- [ ] Secrets stored in secure manager (AWS Secrets, Vercel env vars, etc.)
- [ ] Key rotation scheduled (quarterly for API keys)
- [ ] Database backups automated and tested
- [ ] Monitoring & alerting configured
- [ ] Incident response plan documented

---

## Next Steps

1. **Test locally:** `docker-compose up -d`
2. **Test in dry-run:** `DRY_RUN=true` for 24 hours
3. **Deploy to staging:** Test on VPS with small capital
4. **Monitor carefully:** Review logs, metrics, trades
5. **Go live gradually:** Start with small amounts, scale up

---

**Questions?** See [README.md](./README.md) or [SECURITY.md](./SECURITY.md)
