FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  UV_SYSTEM_PYTHON=1 \
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && pip install --no-cache-dir uv \
  && useradd --create-home --shell /usr/sbin/nologin appuser

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY src ./src

RUN uv sync --frozen --no-dev

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl --fail http://localhost:${PORT:-8501}/_stcore/health || exit 1

CMD ["sh", "-c", ".venv/bin/streamlit run app/app.py --server.address=0.0.0.0 --server.port=${PORT:-8501} --server.headless=true"]