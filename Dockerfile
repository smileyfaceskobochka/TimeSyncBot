# TimeSyncBot Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Moscow

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data/pdf /app/data/temp /app/logs

# Health check (verify python process is running)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD pgrep -f "python main.py" || exit 1

# Entrypoint
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Default command
CMD ["python", "main.py"]
