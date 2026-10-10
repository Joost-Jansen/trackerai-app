# health-api: the FastAPI API of health-tracker (health-web, web/Dockerfile, serves the site in front of it).
# The data lives in Postgres (DATABASE_URL); the image contains only code.
#
# Build context: the repo root (`docker build -f health-tracker/api/Dockerfile .`), for packages/.

FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY health-tracker/api/requirements.txt api/requirements.txt
RUN pip install -r api/requirements.txt
# The shared packages: the account (login, two-step login) and the web security building blocks
COPY packages/accounts /tmp/accounts
COPY packages/websec /tmp/websec
RUN pip install /tmp/websec /tmp/accounts && rm -rf /tmp/websec /tmp/accounts
COPY health-tracker/api/ api/
COPY health-tracker/tools/ tools/
COPY health-tracker/scripts/seed_demo.py scripts/seed_demo.py
# /data: temporary files (Apple uploads up to 2 GB, exports) and the example account, on a volume in docker-compose.yml so
# the container's own filesystem can stay read-only. Owned by appuser: a new named volume copies that ownership.
RUN useradd --uid 1000 --create-home appuser && mkdir -p /data/tmp /data/uploads /data/example && chown -R appuser:appuser /data
ENV TMPDIR=/data/tmp APPLE_UPLOAD_DIR=/data/uploads EXAMPLE_DATA_DIR=/data/example
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/api/health' % os.environ.get('PORT','8000')).getcode()==200 else 1)"
# HOST 0.0.0.0, not :: (otherwise the IPv4 healthcheck on Railway fails).
CMD ["sh", "-c", "exec uvicorn api.main:create_app --factory --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --no-proxy-headers --no-server-header"]
