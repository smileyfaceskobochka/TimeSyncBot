#!/bin/bash

# TimeSync Distroless-Style Entrypoint Script
# Roles:
#   server  — runs the FastAPI server + parser scheduler (python server/main.py)
#   bot     — runs the Telegram bot client (python main.py)

set -e

ROLE="${APP_ROLE:-bot}"

echo "🚀 TimeSync container starting (role: ${ROLE})..."

# --- Role-specific validation ---
if [ "${ROLE}" = "server" ]; then
    if [ -z "$BOT_API_KEY" ]; then
        echo "❌ Error: BOT_API_KEY environment variable is not set (required for the internal API)"
        exit 1
    fi
else
    if [ -z "$BOT_TOKEN" ]; then
        echo "❌ Error: BOT_TOKEN environment variable is not set"
        exit 1
    fi

    if [ -z "$ADMIN_IDS" ]; then
        echo "❌ Error: ADMIN_IDS environment variable is not set"
        exit 1
    fi

    if [ -z "$BOT_API_KEY" ]; then
        echo "❌ Error: BOT_API_KEY environment variable is not set (must match the server)"
        exit 1
    fi
fi

echo "✓ Environment variables validated"

# Create directories if they don't exist
mkdir -p /app/data/pdf /app/data/temp /app/logs
echo "✓ Data directories created"

# Timezone sanity check (Python zoneinfo needs tzdata)
if python -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Moscow')" 2>/dev/null; then
    echo "✓ Timezone database OK (TZ=${TZ:-Europe/Moscow})"
else
    echo "⚠️ Warning: zoneinfo lookup failed — install the 'tzdata' package"
fi

echo "📡 Starting ${ROLE}..."
exec "$@"
