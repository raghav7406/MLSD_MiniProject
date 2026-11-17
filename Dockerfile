FROM python:3.12-slim

# Prevent Python from writing .pyc files and ensure immediate unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system utilities for health checks and container diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 -r requirements.txt

# Copy application source, data, policies, and configuration
COPY . .

# Build the semantic index, embeddings, and vector store at image build time
RUN python -m src.ingestion.ingest_pipeline --force

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501
