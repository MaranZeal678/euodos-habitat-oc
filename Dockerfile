# Keystone: one image serves the dashboard, the demo, the REST API and the MCP server.
# Build with ML extras (CNN inference + ingestion pipeline):  docker build --build-arg WITH_ML=1 -t keystone .
FROM python:3.13-slim

ARG WITH_ML=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KEYSTONE_HOST=0.0.0.0 PORT=8000
# bubblewrap gives the agent sandbox its OS boundary on Linux (no network, private writable dir)
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$WITH_ML" = "1" ]; then pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-ml.txt; fi
COPY keystone ./keystone
COPY data/processed ./data/processed
COPY data/raw/hmda_oc_2024.csv ./data/raw/
COPY artifacts ./artifacts
RUN useradd -m keystone && chown -R keystone /app
USER keystone
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["sh", "-c", "uvicorn keystone.app.server:app --host 0.0.0.0 --port ${PORT}"]
