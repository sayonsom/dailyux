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
GEMINI_MODEL=gemini-1.5-pro
TZ=Asia/Kolkata
```

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
  --set-env-vars GOOGLE_API_KEY=your_key,GEMINI_MODEL=gemini-1.5-pro
```

#### 2. AWS ECS/Fargate
```bash
# Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker tag dailyux-backend:latest YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/dailyux-backend:latest
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/dailyux-backend:latest

# Create ECS task definition and service
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
  --environment-variables GOOGLE_API_KEY=your_key
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
  - key: GOOGLE_API_KEY
    value: your_key
    type: SECRET
  http_port: 8080
```

#### 5. Railway
```bash
# Install Railway CLI
npm install -g @railway/cli

# Deploy
railway login
railway init
railway up
```

### Production Considerations

1. **Security:**
   - Use secrets management (AWS Secrets Manager, Google Secret Manager, etc.)
   - Enable HTTPS with proper SSL certificates
   - Configure CORS appropriately
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

✅ **Multi-stage optimized build**  
✅ **Security hardened** (non-root user)  
✅ **Health checks** configured  
✅ **Environment variable** support  
✅ **Production-ready** nginx configuration  
✅ **Docker Compose** for local development  
✅ **Cloud deployment** ready  

The container is approximately **~150MB** compressed and starts in **~5 seconds**.
