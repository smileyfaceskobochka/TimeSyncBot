#!/bin/bash

# TimeSyncBot Docker Entrypoint Script

set -e

echo "🚀 TimeSyncBot Container Starting..."

# Check required environment variables
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ Error: BOT_TOKEN environment variable is not set"
    exit 1
fi

if [ -z "$ADMIN_IDS" ]; then
    echo "❌ Error: ADMIN_IDS environment variable is not set"
    exit 1
fi

echo "✓ Environment variables validated"

# Create directories if they don't exist
mkdir -p /app/data/pdf /app/data/temp /app/logs
echo "✓ Data directories created"

# Run the bot
echo "📡 Starting bot..."
exec "$@"
