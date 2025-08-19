#!/bin/bash

# Build and deployment script for DailyUX Backend

set -e

echo "🏗️  Building DailyUX Backend Docker container..."

# Build the Docker image
docker build -t dailyux-backend:latest .

echo "✅ Build completed successfully!"

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found. Creating from template..."
    cp .env.example .env
    echo "📝 Please edit .env file with your actual values before running."
fi

echo "🚀 Ready to deploy! Available commands:"
echo ""
echo "  Local development:"
echo "    docker-compose up"
echo ""
echo "  Production (with nginx):"
echo "    docker-compose --profile production up -d"
echo ""
echo "  Push to registry:"
echo "    docker tag dailyux-backend:latest your-registry/dailyux-backend:latest"
echo "    docker push your-registry/dailyux-backend:latest"
echo ""
echo "  Deploy to cloud:"
echo "    # AWS ECS, Google Cloud Run, Azure Container Instances, etc."
echo "    # See deployment guides in README.md"
