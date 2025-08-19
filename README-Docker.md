# DailyUX Backend - Docker Deployment Guide

## 🐳 Containerized Deployment

This application is now fully containerized and ready for cloud deployment.

### Quick Start

1. **Build the container:**
   ```bash
   ./build.sh
   ```

2. **Run locally:**
   ```bash
   docker-compose up
   ```

3. **Run with nginx (production-like):**
   ```bash
   docker-compose --profile production up -d
   ```

### Environment Variables

Create a `.env` file:
```bash
GOOGLE_API_KEY=your_actual_api_key
GEMINI_MODEL=gemini-2.5-pro
TZ=Asia/Kolkata
LLM_MODE=client  # default; ensures server never calls LLMs
```

Notes:
- The Dockerfile and docker-compose default to `LLM_MODE=client` so backend won’t call Gemini.
- You can override at runtime by setting `LLM_MODE=server` (for local/dev only).

### Cloud Deployment Options

#### 1. Google Cloud Run (Recommended)
```bash
# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT/dailyux-backend

# Deploy to Cloud Run
gcloud run deploy dailyux-backend \
  --image gcr.io/YOUR_PROJECT/dailyux-backend \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars LLM_MODE=client,GEMINI_MODEL=gemini-2.5-pro
```

#### 2. AWS ECS/Fargate
```bash
# Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker tag dailyux-backend:latest YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/dailyux-backend:latest
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/dailyux-backend:latest

# Ensure task definition env:
#   LLM_MODE=client
#   GEMINI_MODEL=gemini-2.5-pro
```

#### 3. Azure Container Instances
```bash
# Build and push to ACR
az acr build --registry YOUR_REGISTRY --image dailyux-backend:latest .

# Deploy to ACI
az container create \
  --resource-group YOUR_RG \
  --name dailyux-backend \
  --image YOUR_REGISTRY.azurecr.io/dailyux-backend:latest \
  --ports 8000 \
  --environment-variables LLM_MODE=client GEMINI_MODEL=gemini-2.5-pro
```

#### 4. DigitalOcean App Platform
```yaml
# app.yaml
name: dailyux-backend
services:
- name: api
  source_dir: /
  github:
    repo: your-username/dailyux-backend
    branch: main
  run_command: uvicorn app.main:app --host 0.0.0.0 --port 8080
  environment_slug: python
  instance_count: 1
  instance_size_slug: basic-xxs
  envs:
  - key: LLM_MODE
    value: client
  - key: GEMINI_MODEL
    value: gemini-2.5-pro
  http_port: 8080
```

### Production Considerations

1. **Security:**
   - Use secrets management (AWS Secrets Manager, Google Secret Manager, etc.)
   - Enable HTTPS with proper SSL certificates
   - Configure CORS appropriately (currently permissive for dev)
   - Use non-root user (already configured in Dockerfile)

2. **Scaling:**
   - Configure horizontal pod autoscaling
   - Set up load balancing
   - Consider using Redis for session storage if needed

3. **Monitoring:**
   - Add application logs
   - Configure health checks
   - Set up monitoring (CloudWatch, Stackdriver, etc.)

4. **CI/CD:**
   - Set up GitHub Actions or similar for automated deployments
   - Configure staging and production environments

### Local Development

For development with hot reloading:
```bash
# Run with volume mount for code changes
docker-compose up

# Or run directly with Python
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### API Endpoints

- **REST API:** `http://localhost:8000/api/`
- **WebSocket:** `ws://localhost:8000/ws/`
- **Documentation:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/api/profiles`

### Container Features

✅ **Security hardened** (non-root user)  
✅ **Health checks** configured  
✅ **Environment variable** support  
✅ **Production-ready** nginx configuration  
✅ **Docker Compose** for local development  
✅ **Cloud deployment** ready  

---

## 🔧 Client-LLM Test Script

Use this script to verify that the client performs LLM work and the backend accepts results.

Create `scripts/test_client_llm.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${BASE_URL:-http://localhost:8000}"
PROFILE="${PROFILE:-Ravindra}"

# 1) Health
curl -s "$BASE_URL/health" | jq .

# 2) Get supervisor prompt (server computes context; client does LLM)
SUP=$(curl -s "$BASE_URL/api/prompts/supervisor?profile_id=$PROFILE")
echo "$SUP" | jq . > /dev/null
PROMPT=$(echo "$SUP" | jq -r '.prompt')

# 3) Simulate client LLM bullets (you would call Gemini client-side here)
# For demo, just fake three bullets
BULLETS='["Protect 60m deep work 09:00-10:00","Batch emails at 12:30 and 17:30","Prep unwind by 21:30"]'

# 4) Call backend with client bullets
curl -s -X POST "$BASE_URL/api/plan/day" \
  -H 'Content-Type: application/json' \
  -d "{\"profile_id\":\"$PROFILE\",\"supervisor_insights_bullets\":$BULLETS}" | jq '.cards[0], .rationale'

# 5) Natural language via client_action (skip server LLM)
curl -s -X POST "$BASE_URL/api/nl" \
  -H 'Content-Type: application/json' \
  -d "{\"profile_id\":\"$PROFILE\",\"target\":\"birthday\",\"client_action\":{\"type\":\"change_venue\",\"venue\":\"The Blue Door\"}}" | jq .

echo "Done. Client provided LLM outputs; backend did not call Gemini."
```

Then:
```bash
chmod +x scripts/test_client_llm.sh
./scripts/test_client_llm.sh
```

If you want a WebSocket test, I can add a Node or Python snippet as well.
