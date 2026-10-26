# TrustGuard REST API container. The LLM (Ollama / OpenAI-compatible server) runs outside the container;
# point TRUSTGUARD_LLM_BASE_URL at the host. Verification models download on first run (or bake them in
# by running scripts.download_models during build with network access).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    TRUSTGUARD_LLM_BASE_URL=http://host.docker.internal:11434

WORKDIR /app

# System deps kept minimal; CPU-only torch wheel from PyPI.
COPY requirements.txt .
RUN pip install torch==2.4.1 -r requirements.txt

COPY . .

# Non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import requests,sys; sys.exit(0 if requests.get('http://localhost:8000/health',timeout=3).ok else 1)"

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
