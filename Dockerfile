FROM python:3.13-slim

WORKDIR /app

# Install build deps and runtime deps
COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip wheel setuptools \
    && pip install -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY shared/ ./shared/
COPY README* LICENSE* ./

ENV PYTHONPATH=/app/src \
    SERVICE_NAME=engine \
    SERVICE_TYPE=engine \
    SERVICE_PORT=8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 CMD ["python", "-c", "import os,urllib.request,sys;port=os.getenv('SERVICE_PORT','8003');url=f'http://localhost:{port}/health';\n\nimport contextlib;\ntry:\n  with urllib.request.urlopen(url,timeout=5) as r: sys.exit(0 if 200<=r.status<300 else 1)\nexcept Exception: sys.exit(1)"]

EXPOSE 8003

RUN adduser --disabled-password --gecos "" appuser || useradd -m appuser || true
USER appuser

CMD ["python", "src/main.py"]
