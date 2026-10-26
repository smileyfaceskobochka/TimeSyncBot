# TimeSync Dockerfile (single image, two roles: server + bot)
FROM python:3.11-slim

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Moscow \
    PATH="/app/.venv/bin:$PATH"

# Install system dependencies (curl used by healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using uv sync from lockfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code and install project
COPY . .
RUN uv sync --frozen --no-dev

# Create data directories
RUN mkdir -p /app/data/pdf /app/data/temp /app/logs

# Healthchecks are defined per-service in docker-compose.yml
# (the bot client doesn't serve HTTP, so only the server gets one)
# Entrypoint
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Default command
CMD ["python", "main.py"]
