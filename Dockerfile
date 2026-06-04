# Nexus backend — production Docker image
FROM python:3.12-slim

LABEL maintainer="Nexus LLM Interface"
LABEL description="Production local LLM interface backend"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Data directory
RUN mkdir -p /data/memory /data/skills /data/research /data/logs

# Non-root user for security
RUN useradd -m -u 1000 nexus && chown -R nexus:nexus /app /data
USER nexus

# Pre-download embedding model (baked into image so no startup delay)
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || true

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
