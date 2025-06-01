# BetSightly Deployment Guide

## Overview

This guide covers deploying the BetSightly backend API in various environments.

## Prerequisites

- Python 3.11 or higher
- Git
- 4GB+ RAM recommended
- 10GB+ disk space for models and cache

## Environment Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd betsightly-backend
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Environment Variables

Create a `.env` file in the project root:

```env
# API Keys
API_FOOTBALL_KEY=your_api_football_key
FOOTBALL_DATA_KEY=your_football_data_key

# Database
DATABASE_URL=sqlite:///data/database.db

# ML Settings
ML_MODEL_DIR=models
ML_DATA_DIR=data
ML_CACHE_DIR=cache

# API Settings
APP_NAME=BetSightly
APP_VERSION=1.0.0
DEBUG=false
ENVIRONMENT=production

# Odds Categories
TWO_ODDS_MIN=1.0
TWO_ODDS_MAX=2.0
TWO_ODDS_MIN_CONFIDENCE=50.0
TWO_ODDS_LIMIT=10

FIVE_ODDS_MIN=2.0
FIVE_ODDS_MAX=5.0
FIVE_ODDS_MIN_CONFIDENCE=40.0
FIVE_ODDS_LIMIT=5

TEN_ODDS_MIN=5.0
TEN_ODDS_MAX=10.0
TEN_ODDS_MIN_CONFIDENCE=30.0
TEN_ODDS_LIMIT=3

ROLLOVER_MIN=1.0
ROLLOVER_MAX=1.5
ROLLOVER_MIN_CONFIDENCE=60.0
ROLLOVER_TARGET=10.0
```

### 5. Initialize Database

```bash
python -c "from database import init_db; init_db()"
```

### 6. Download/Train Models

```bash
# Run the streamlined ML pipeline
python ml_pipeline_streamlined.py

# Or use existing models if available
# Copy model files to the models/ directory
```

## Development Deployment

### Local Development Server

```bash
# Start the development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- API: http://localhost:8000
- Documentation: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Development with Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# Build and run
docker build -t betsightly-backend .
docker run -p 8000:8000 -v $(pwd)/data:/app/data betsightly-backend
```

## Production Deployment

### Option 1: Traditional Server (Ubuntu/CentOS)

#### 1. System Dependencies

```bash
# Ubuntu
sudo apt update
sudo apt install python3.11 python3.11-venv nginx supervisor

# CentOS
sudo yum update
sudo yum install python3.11 python3.11-venv nginx supervisor
```

#### 2. Application Setup

```bash
# Create application user
sudo useradd -m -s /bin/bash betsightly
sudo su - betsightly

# Clone and setup application
git clone <repository-url> /home/betsightly/app
cd /home/betsightly/app
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 3. Gunicorn Configuration

Create `/home/betsightly/app/gunicorn.conf.py`:

```python
bind = "127.0.0.1:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 30
keepalive = 2
preload_app = True
```

#### 4. Supervisor Configuration

Create `/etc/supervisor/conf.d/betsightly.conf`:

```ini
[program:betsightly]
command=/home/betsightly/app/venv/bin/gunicorn main:app -c gunicorn.conf.py
directory=/home/betsightly/app
user=betsightly
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/betsightly.log
```

#### 5. Nginx Configuration

Create `/etc/nginx/sites-available/betsightly`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /home/betsightly/app/static/;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/betsightly /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl restart supervisor
```

### Option 2: Docker Production

#### Docker Compose Setup

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/betsightly
    volumes:
      - ./data:/app/data
      - ./models:/app/models
      - ./cache:/app/cache
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=betsightly
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - app
    restart: unless-stopped

volumes:
  postgres_data:
```

```bash
# Deploy
docker-compose up -d
```

### Option 3: Cloud Deployment (AWS/GCP/Azure)

#### AWS Elastic Beanstalk

1. Install EB CLI
2. Create `application.py` (alias for main.py)
3. Create `.ebextensions/` configuration
4. Deploy:

```bash
eb init
eb create production
eb deploy
```

#### Google Cloud Run

```bash
# Build and deploy
gcloud builds submit --tag gcr.io/PROJECT_ID/betsightly
gcloud run deploy --image gcr.io/PROJECT_ID/betsightly --platform managed
```

#### Azure Container Instances

```bash
# Build and push to ACR
az acr build --registry myregistry --image betsightly .
az container create --resource-group mygroup --name betsightly --image myregistry.azurecr.io/betsightly
```

## Monitoring and Maintenance

### Health Checks

```bash
# Check API health
curl http://localhost:8000/api/health/

# Check specific endpoints
curl http://localhost:8000/api/predictions/
```

### Log Management

```bash
# View application logs
tail -f /var/log/betsightly.log

# View nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### Cache Management

```bash
# Clean expired cache
python scripts/cleanup_cache.py

# Schedule cache cleanup (crontab)
0 2 * * * /home/betsightly/app/venv/bin/python /home/betsightly/app/scripts/cleanup_cache.py
```

### Database Backup

```bash
# SQLite backup
cp data/database.db data/database_backup_$(date +%Y%m%d).db

# PostgreSQL backup
pg_dump betsightly > backup_$(date +%Y%m%d).sql
```

### Model Updates

```bash
# Update models
python ml_pipeline_streamlined.py

# Restart application
sudo supervisorctl restart betsightly
```

## Performance Optimization

### Database Optimization

```python
# Run database optimization
python -c "from utils.database_optimization import optimize_database; optimize_database()"
```

### Caching Strategy

- Enable Redis for production caching
- Configure cache expiry times
- Monitor cache hit rates

### Load Balancing

For high traffic, use multiple application instances behind a load balancer.

## Security Considerations

1. **API Keys**: Store in environment variables, never in code
2. **Rate Limiting**: Configure appropriate limits
3. **HTTPS**: Use SSL certificates in production
4. **Firewall**: Restrict access to necessary ports only
5. **Updates**: Keep dependencies updated

## Troubleshooting

### Common Issues

1. **Import Errors**: Check Python path and virtual environment
2. **Model Loading**: Ensure model files are present and accessible
3. **Database Connection**: Verify database URL and permissions
4. **API Timeouts**: Increase timeout settings for ML predictions

### Debug Mode

```bash
# Enable debug mode
export DEBUG=true
uvicorn main:app --reload --log-level debug
```

## Scaling

### Horizontal Scaling

- Use multiple application instances
- Implement load balancing
- Consider microservices architecture

### Vertical Scaling

- Increase server resources (CPU, RAM)
- Optimize database queries
- Use caching effectively

## Backup and Recovery

### Automated Backups

```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d_%H%M%S)
cp data/database.db backups/database_$DATE.db
tar -czf backups/models_$DATE.tar.gz models/
tar -czf backups/cache_$DATE.tar.gz cache/
```

### Recovery Procedures

1. Stop application
2. Restore database and models
3. Clear cache if necessary
4. Restart application
5. Verify functionality

This deployment guide covers the essential steps for deploying BetSightly in various environments. Adjust configurations based on your specific requirements and infrastructure.
