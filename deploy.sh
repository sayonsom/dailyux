#!/bin/bash

# DailyUX Backend - Cloud Deployment Script
# Supports multiple cloud providers and deployment methods

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
IMAGE_NAME="dailyux-backend"
VERSION=${VERSION:-"latest"}

show_help() {
    echo "DailyUX Backend Deployment Script"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  build           Build Docker image"
    echo "  local           Run locally with Docker Compose"
    echo "  gcp             Deploy to Google Cloud Run"
    echo "  aws             Deploy to AWS ECS/Fargate"
    echo "  azure           Deploy to Azure Container Instances"
    echo "  k8s             Deploy to Kubernetes"
    echo "  railway         Deploy to Railway"
    echo "  digitalocean    Deploy to DigitalOcean App Platform"
    echo ""
    echo "Options:"
    echo "  --version       Set version tag (default: latest)"
    echo "  --help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 gcp --version v1.0.0"
    echo "  $0 k8s"
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_env() {
    if [ ! -f .env ]; then
        warn ".env file not found. Creating from template..."
        cp .env.example .env
        warn "Please edit .env file with your actual values"
        return 1
    fi
    return 0
}

build_image() {
    log "Building Docker image: $IMAGE_NAME:$VERSION"
    docker build -t $IMAGE_NAME:$VERSION .
    log "✅ Build completed successfully!"
}

deploy_local() {
    log "Starting local deployment with Docker Compose..."
    check_env || exit 1
    docker-compose up -d
    log "✅ Local deployment running at http://localhost:8000"
    log "📖 API docs: http://localhost:8000/docs"
}

deploy_gcp() {
    log "Deploying to Google Cloud Run..."
    
    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        error "gcloud CLI not found. Please install Google Cloud SDK."
        exit 1
    fi
    
    # Build and push to Google Container Registry
    PROJECT_ID=$(gcloud config get-value project)
    if [ -z "$PROJECT_ID" ]; then
        error "No GCP project set. Run: gcloud config set project YOUR_PROJECT"
        exit 1
    fi
    
    IMAGE_URL="gcr.io/$PROJECT_ID/$IMAGE_NAME:$VERSION"
    
    log "Building and pushing to GCR: $IMAGE_URL"
    gcloud builds submit --tag $IMAGE_URL
    
    log "Deploying to Cloud Run..."
    gcloud run deploy $IMAGE_NAME \
        --image $IMAGE_URL \
        --platform managed \
        --region us-central1 \
        --allow-unauthenticated \
        --set-env-vars "GEMINI_MODEL=gemini-1.5-pro,TZ=Asia/Kolkata" \
        --memory 512Mi \
        --cpu 1 \
        --max-instances 10
    
    log "✅ Deployed to Google Cloud Run!"
}

deploy_aws() {
    log "Deploying to AWS ECS..."
    
    if ! command -v aws &> /dev/null; then
        error "AWS CLI not found. Please install AWS CLI."
        exit 1
    fi
    
    # This is a simplified example - you'd need to set up ECS cluster, task definition, etc.
    warn "AWS deployment requires additional setup. Please refer to README-Docker.md"
    log "Basic steps:"
    log "1. Create ECR repository"
    log "2. Push image to ECR"
    log "3. Create ECS task definition"
    log "4. Create ECS service"
}

deploy_azure() {
    log "Deploying to Azure Container Instances..."
    
    if ! command -v az &> /dev/null; then
        error "Azure CLI not found. Please install Azure CLI."
        exit 1
    fi
    
    warn "Azure deployment requires additional setup. Please refer to README-Docker.md"
}

deploy_k8s() {
    log "Deploying to Kubernetes..."
    
    if ! command -v kubectl &> /dev/null; then
        error "kubectl not found. Please install kubectl."
        exit 1
    fi
    
    log "Applying Kubernetes manifests..."
    kubectl apply -f k8s/deployment.yaml
    
    log "✅ Deployed to Kubernetes!"
    log "Check status: kubectl get pods -l app=dailyux-backend"
}

deploy_railway() {
    log "Deploying to Railway..."
    
    if ! command -v railway &> /dev/null; then
        error "Railway CLI not found. Install with: npm install -g @railway/cli"
        exit 1
    fi
    
    railway up
    log "✅ Deployed to Railway!"
}

deploy_digitalocean() {
    log "Deploying to DigitalOcean App Platform..."
    
    if ! command -v doctl &> /dev/null; then
        error "doctl not found. Please install DigitalOcean CLI."
        exit 1
    fi
    
    warn "DigitalOcean deployment requires app.yaml configuration."
    log "Please refer to README-Docker.md for setup instructions."
}

# Parse arguments
COMMAND=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --version)
            VERSION="$2"
            shift 2
            ;;
        --help)
            show_help
            exit 0
            ;;
        build|local|gcp|aws|azure|k8s|railway|digitalocean)
            COMMAND="$1"
            shift
            ;;
        *)
            error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Execute command
case $COMMAND in
    build)
        build_image
        ;;
    local)
        deploy_local
        ;;
    gcp)
        deploy_gcp
        ;;
    aws)
        deploy_aws
        ;;
    azure)
        deploy_azure
        ;;
    k8s)
        deploy_k8s
        ;;
    railway)
        deploy_railway
        ;;
    digitalocean)
        deploy_digitalocean
        ;;
    "")
        error "No command specified"
        show_help
        exit 1
        ;;
    *)
        error "Unknown command: $COMMAND"
        show_help
        exit 1
        ;;
esac
