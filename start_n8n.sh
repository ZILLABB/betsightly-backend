#!/bin/bash

# BetSightly N8N Startup Script
# This script starts N8N with the proper configuration for BetSightly

echo "🚀 Starting BetSightly N8N Integration..."

# Check if N8N is installed
if ! command -v n8n &> /dev/null; then
    echo "❌ N8N is not installed. Installing now..."
    npm install -g n8n
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install N8N. Please install manually:"
        echo "   npm install -g n8n"
        exit 1
    fi
fi

# Load environment variables if .env.n8n exists
if [ -f ".env.n8n" ]; then
    echo "📋 Loading N8N configuration..."
    export $(cat .env.n8n | grep -v '^#' | xargs)
fi

# Set default N8N configuration
export N8N_BASIC_AUTH_ACTIVE=${N8N_BASIC_AUTH_ACTIVE:-false}
export N8N_HOST=${N8N_HOST:-0.0.0.0}
export N8N_PORT=${N8N_PORT:-5678}
export N8N_PROTOCOL=${N8N_PROTOCOL:-http}
export WEBHOOK_URL=${WEBHOOK_URL:-http://localhost:5678/}

# Create N8N data directory if it doesn't exist
mkdir -p ~/.n8n

echo "🌐 Starting N8N on http://localhost:${N8N_PORT}"
echo "📊 N8N will be available for BetSightly integration"
echo ""
echo "🔧 Configuration:"
echo "   - Host: ${N8N_HOST}"
echo "   - Port: ${N8N_PORT}"
echo "   - Protocol: ${N8N_PROTOCOL}"
echo "   - Webhook URL: ${WEBHOOK_URL}"
echo ""

# Start N8N
echo "⏳ Starting N8N..."
n8n start

# If we reach here, N8N has stopped
echo ""
echo "⚠️  N8N has stopped. Check the logs above for any errors."
