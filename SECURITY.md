# Security Guide - AI Agent Wealth Builder

**Critical security practices for autonomous trading system**

---

## ⚠️ Risk Disclaimer

This system executes **real trades with real money** when `DRY_RUN=false`. Improper security configuration could result in:
- Unauthorized fund access
- Loss of trading capital
- API key theft/abuse
- Database compromise

**Follow every step in this guide before production deployment.**

---

## Table of Contents

1. [Secret Management](#secret-management)
2. [Network Security](#network-security)
3. [Database Security](#database-security)
4. [API Security](#api-security)
5. [Key Rotation](#key-rotation)
6. [Audit & Logging](#audit--logging)
7. [Incident Response](#incident-response)

---

## Secret Management

### 1. Environment Variables

❌ **NEVER**:
```bash
# Wrong - password in command
docker run -e "POLYGON_PRIVATE_KEY=0x..." agent

# Wrong - credentials in code
DATABASE_URL = "postgresql://user:password@..."

# Wrong - secrets in git history
git commit -m "Added keys" && git push
```

✅ **DO THIS INSTEAD**:
```bash
# Using .env file (not committed to git)
cp .env.example .env
chmod 600 .env  # Only owner can read
# Edit .env with secure editor
nano .env

# Docker Compose will load from .env automatically
docker-compose up -d

# Verify keys are not exposed
ps aux | grep python  # Should NOT show keys
docker inspect container_id | grep DATABASE_URL  # Should be redacted
```

### 2. Secure Storage by Platform

#### Local Development
```bash
# Use .env file with restricted permissions
chmod 600 ~/.env
chmod 600 /opt/ai-agent/.env

# Never commit
echo ".env" >> .gitignore
git add .gitignore && git commit -m "Ignore .env"
```

#### Docker / Docker Compose
```bash
# Use Docker secrets (production)
echo "sk-your-openai-key" | docker secret create openai_key -

# Reference in docker-compose.yml
services:
  agent:
    secrets:
      - openai_key
    environment:
      OPENAI_API_KEY_FILE: /run/secrets/openai_key
```

#### Vercel
```bash
# Use environment variables dashboard
# Settings → Environment Variables → Add

# Never use in code
// ❌ WRONG
const apiKey = "sk-..."

// ✅ RIGHT
const apiKey = process.env.OPENAI_API_KEY
```

#### AWS
```bash
# Store in AWS Secrets Manager
aws secretsmanager create-secret \
  --name wealth-builder/openai-key \
  --secret-string 'sk-...'

# Reference in ECS task definition
{
  "secrets": [
    {
      "name": "OPENAI_API_KEY",
      "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789:secret:wealth-builder/openai-key"
    }
  ]
}
```

#### GitHub (CI/CD)
```bash
# Use repository secrets
# Settings → Secrets and variables → Actions → New repository secret

# Reference in workflow
- name: Deploy
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: ./deploy.sh
```

### 3. Secret Rotation

**Create and document a rotation schedule:**

```bash
# Rotation schedule (calendar reminder)
- OpenAI API Key: Quarterly (Jan 1, Apr 1, Jul 1, Oct 1)
- Polygon Private Key: Immediately if suspected compromise
- Database Password: Every 6 months
- Polygon Wallet: Validate balance weekly

# Steps to rotate OpenAI key:
1. Create new key in OpenAI dashboard
2. Update environment variable
3. Test with dry-run cycle
4. Delete old key from dashboard
5. Document rotation in SECURITY_LOG.md
```

---

## Network Security

### 1. Firewall Configuration

```bash
# Only allow SSH and application ports
sudo ufw enable
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH (limit to specific IPs if possible)
sudo ufw allow 22/tcp
sudo ufw allow from 192.168.1.0/24 to any port 22

# Application API
sudo ufw allow 8000/tcp

# Database (only from agent container)
# Don't expose port 5432 externally

# Verify
sudo ufw status numbered
```

### 2. PostgreSQL Access Control

```sql
-- Restrict to specific host
CREATE USER trading_user WITH PASSWORD 'strong_password';
ALTER USER trading_user CONNECTION LIMIT 10;

-- Only allow connections from agent
-- In postgresql.conf:
# listen_addresses = 'localhost'  # Or specific IP

-- pg_hba.conf
local   wealth_builder  trading_user                md5
host    wealth_builder  trading_user 127.0.0.1/32  md5
host    wealth_builder  trading_user ::1/128       md5
# Specify Docker network if needed:
# host    wealth_builder  trading_user 172.20.0.0/16  md5
```

### 3. API Endpoint Security

```python
# Add authentication to monitoring endpoints
from functools import wraps
from flask import Flask, request

app = Flask(__name__)

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key != os.getenv('API_KEY'):
            return {'error': 'Unauthorized'}, 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/dashboard')
@require_api_key
def dashboard():
    # Protected endpoint
    return get_dashboard_data()
```

### 4. HTTPS/TLS

```bash
# Generate self-signed certificate for local HTTPS
openssl req -x509 -newkey rsa:2048 -nodes -out cert.pem -keyout key.pem -days 365

# Or use Let's Encrypt for production
sudo apt install certbot
sudo certbot certonly --standalone -d your.domain.com

# Configure in application
# Django: SECURE_SSL_REDIRECT = True
# Flask: Use ssl_context=('cert.pem', 'key.pem')
```

---

## Database Security

### 1. Password Strength

```bash
# Generate strong password (32 chars, mixed)
openssl rand -base64 32
# Output: AbCdEfGhIjKlMnOpQrStUvWxYz1234567890

# Use in DATABASE_URL
DATABASE_URL=postgresql://trading_user:AbCdEfGhIjKlMnOpQrStUvWxYz1234567890@localhost:5432/wealth_builder
```

### 2. Backup Encryption

```bash
# Backup database with encryption
pg_dump -U trading_user wealth_builder | \
  gpg --symmetric --cipher-algo AES256 > backup.sql.gpg

# Restore encrypted backup
gpg --decrypt backup.sql.gpg | \
  psql -U trading_user -d wealth_builder

# Store in secure cloud storage
aws s3 cp backup.sql.gpg s3://secure-backups/ \
  --sse AES256 \
  --storage-class GLACIER
```

### 3. Connection Pooling

```bash
# postgresql.conf - limit connections
max_connections = 100
# Connection pooling via PgBouncer
# config: database = admin password=...
```

### 4. Audit Logging

```sql
-- Enable query logging
ALTER admin_user SET log_connections = on;
ALTER admin_user SET log_disconnections = on;

-- Log all statements to file
ALTER SYSTEM SET  log_statement = 'all';
ALTER SYSTEM SET log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log';

-- Verify
SHOW log_statement;
SHOW log_directory;
```

---

## API Security

### 1. Rate Limiting

```python
from ratelimit import limits, sleep_and_retry
import time

# Max 60 API calls per minute
@sleep_and_retry
@limits(calls=60, period=60)
def call_openai_api(prompt):
    return openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

# Exponential backoff for retries
@sleep_and_retry
@limits(calls=3, period=60)
def call_polymarket_api(endpoint):
    response = requests.get(endpoint)
    if response.status_code == 429:
        time.sleep(2 ** attempt)  # Exponential backoff
    return response
```

### 2. Input Validation

```python
# Validate all inputs
from pydantic import BaseModel, validator

class TradeRequest(BaseModel):
    market_id: str
    amount_usd: float
    action: str
    
    @validator('amount_usd')
    def validate_amount(cls, v):
        if v <= 0 or v > 10000:
            raise ValueError('Amount must be 0-10000 USD')
        return v
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['BUY', 'SELL']:
            raise ValueError('Action must be BUY or SELL')
        return v
```

### 3. Error Handling

```python
# Never expose sensitive details
❌ Wrong:
return {
    'error': 'Database connection failed: postgresql://user:password@localhost'
}

✅ Correct:
return {
    'error': 'Database connection failed',
    'error_id': 'DB_CONNECTION_ERROR_12345'
}
# Log details separately with the error_id
```

---

## Key Rotation

### 1. OpenAI API Key Rotation

```bash
#!/bin/bash
# rotate_openai_key.sh

# 1. Create new key in OpenAI dashboard manually

# 2. Update environment
NEW_KEY="sk-your-new-key"
export OPENAI_API_KEY=$NEW_KEY

# 3. Test agent with new key (dry-run)
DRY_RUN=true python -c "from src.ai_analyzer import analyze_market; analyze_market({'title': 'Test'})"

# 4. If successful, update Docker
docker-compose restart agent

# 5. Monitor for 1 hour
docker-compose logs -f agent | grep -i error

# 6. Revoke old key in OpenAI dashboard

# 7. Document rotation
echo "OpenAI Key rotated at $(date)" >> SECURITY_LOG.md
```

### 2. Polygon Private Key Rotation

⚠️ **CRITICAL**: Never share private key. If compromised, funds at risk.

```bash
# Steps to rotate (requires wallet migration):
# 1. Generate new Polygon wallet
from web3 import Web3
new_account = Web3().eth.account.create()
print(f"New address: {new_account.address}")
print(f"New private key: {new_account.key.hex()}")

# 2. Transfer funds from old wallet to new wallet
# Done manually in MetaMask or via Web3

# 3. Update POLYGON_PRIVATE_KEY in environment

# 4. Test with small amount (dry-run first)
DRY_RUN=true python -c "from src.trade_executor import execute_trade; ..."

# 5. Go live with new key

# 6. Monitor old wallet for unauthorized access
```

### 3. Database Password Rotation

```bash
# 1. Generate new password
NEW_PASS=$(openssl rand -base64 32)
echo $NEW_PASS

# 2. Update PostgreSQL user password
docker-compose exec postgres psql -U postgres -c "ALTER USER trading_user WITH PASSWORD '$NEW_PASS';"

# 3. Update DATABASE_URL in .env
sed -i "s|postgresql://trading_user:.*@|postgresql://trading_user:$NEW_PASS@|" .env

# 4. Restart agent to reconnect
docker-compose restart agent

# 5. Verify connection
docker-compose exec agent python -c "from src.models import init_db; init_db(); print('Connected')"
```

---

## Audit & Logging

### 1. Application Logs

```python
import logging
from pythonjsonlogger import jsonlogger

# Structured JSON logging
logger = logging.getLogger()
logHandler = logging.FileHandler('logs/app.log')
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)

# Log all trades
logger.info('trade_executed', extra={
    'trade_id': trade_id,
    'market_id': market_id,
    'action': action,
    'amount_usd': amount,
    'timestamp': datetime.utcnow().isoformat(),
    'user_id': user_id  # Can be anonymized
})
```

### 2. Database Audit Trail

```sql
-- Create audit table
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    table_name TEXT,
    action TEXT,  -- INSERT, UPDATE, DELETE
    old_values JSONB,
    new_values JSONB,
    changed_at TIMESTAMP DEFAULT NOW(),
    changed_by TEXT
);

-- Create trigger for automatic logging
CREATE OR REPLACE FUNCTION log_changes() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (table_name, action, old_values, new_values, changed_by)
    VALUES (TG_TABLE_NAME, TG_OP, row_to_json(OLD), row_to_json(NEW), current_user);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to trades table
CREATE TRIGGER trades_audit_trigger
AFTER INSERT OR UPDATE OR DELETE ON trades
FOR EACH ROW EXECUTE FUNCTION log_changes();
```

### 3. Monitor Audit Logs

```bash
# Check for suspicious activity
docker-compose exec postgres psql -U trading_user wealth_builder -c "
SELECT * FROM audit_log
WHERE changed_at > NOW() - INTERVAL '1 hour'
ORDER BY changed_at DESC;"

# Alert on changes to system tables
# (send Slack/email notification)
```

---

## Incident Response

### 1. Suspected Key Compromise

**Immediate Actions:**
```bash
# 1. Pause trading immediately
echo "DRY_RUN=true" >> .env
docker-compose restart agent

# 2. Revoke compromised keys
# - OpenAI: Revoke in dashboard
# - Polygon: Transfer funds to new wallet
# - Database: Change password

# 3. Rotate all related secrets

# 4. Review logs for unauthorized access
docker-compose logs agent | grep -i "trade\|execute" | tail -100

# 5. Document incident
cat >> SECURITY_LOG.md <<EOF
## Incident: Possible key compromise
Date: $(date)
Key: OPENAI_API_KEY
Actions taken: Revoked, rotated, funds verified
Status: Paused trading, monitoring 24h
EOF
```

### 2. Unauthorized Trade Detected

```bash
# 1. Kill agent immediately
docker-compose kill agent

# 2. Review recent trades
docker-compose exec postgres psql -U trading_user wealth_builder -c "
SELECT * FROM trades 
ORDER BY executed_at DESC 
LIMIT 20;"

# 3. Check for balance anomalies
docker-compose exec postgres psql -U trading_user wealth_builder -c "
SELECT * FROM positions 
WHERE closed_at IS NULL;"

# 4. Calculate damage
# Funds lost = SUM(losses) - SUM(gains)

# 5. Notify stakeholders
# Send incident report with:
# - Time of incident
# - Trades executed
# - Funds lost
# - Root cause
# - Prevention measures

# 6. Prevent recurrence
# - Implement stricter rate limiting
# - Add approval workflow for large trades
# - Reduce max position size
```

### 3. Database Corruption

```bash
# 1. Stop agent
docker-compose stop agent

# 2. Take backup immediately (if accessible)
docker-compose exec postgres pg_dump -U trading_user wealth_builder > emergency_backup.sql

# 3. Restore from recent backup
# Ensure backup is from before corruption detected

# 4. Rebuild from scratch if needed
docker-compose down -v  # Remove volumes
docker-compose up -d

# 5. Rerun initialization
docker-compose exec agent python -c "from src.models import init_db; init_db()"

# 6. Resume with caution
# Start in DRY_RUN mode first
```

---

## Security Checklist

Before Production Deployment:

### Access Control
- [ ] `.env` excluded from git
- [ ] File permissions restrictive (chmod 600 on .env)
- [ ] API endpoints authenticated
- [ ] Database firewall enabled
- [ ] SSH key-based auth only (no passwords)

### Secrets
- [ ] No secrets in code/comments
- [ ] Environment variables used for all secrets
- [ ] Secrets stored in secure management system
- [ ] Key rotation schedule documented
- [ ] Incident rotation process documented

### Encryption
- [ ] HTTPS/TLS enabled on API endpoints
- [ ] Database connections encrypted
- [ ] Backups encrypted
- [ ] Private keys secured
- [ ] Passwords hashed (bcrypt/scrypt)

### Logging & Auditing
- [ ] Application logs enabled
- [ ] Database audit triggers set up
- [ ] JSON logging format for parsing
- [ ] Logs stored securely
- [ ] Audit trail immutable (append-only)

### Monitoring
- [ ] Failed login attempts tracked
- [ ] Suspicious trade patterns detected
- [ ] Resource usage monitored
- [ ] Alerts configured for anomalies
- [ ] Incident response team assigned

### Network
- [ ] Firewall configured
- [ ] Rate limiting enabled
- [ ] DDoS protection considered
- [  Penetration testing scheduled
- [ ] Network segmentation planned

---

## Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE Top 25](https://cwe.mitre.org/top25/)
- [AWS Security Best Practices](https://docs.aws.amazon.com/security/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/sql-syntax.html)
- [Python Safety Checker](https://safety.readthedocs.io/)

---

**Last Updated:** 2025-02-17  
**Next Review:** 2025-03-17

For security issues, contact: security@yourdomain.com
