FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run ingestion at build time so the vector store is ready
RUN python -m src.ingestion.ingest_pipeline --force

EXPOSE 8000
