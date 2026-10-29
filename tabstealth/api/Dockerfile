# tabstealth-api: the FastAPI API of tabstealth (tabstealth-web, web/Dockerfile, serves the site in front of it) and the
# converter. The libraries live in Postgres (DATABASE_URL); /data (a volume) holds the converter's cache: the frame
# scans per video, so reading a video again does not download it again.
#
# Build context: the repo root (`docker build -f tabstealth/api/Dockerfile .`), for packages/.

FROM denoland/deno:bin-2.9.8 AS deno

FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam
# tesseract: chord names, sections, tuning and capo on screen; tzdata for TZ
RUN apt-get update && apt-get install -y --no-install-recommends tzdata tesseract-ocr && rm -rf /var/lib/apt/lists/*
# yt-dlp solves YouTube's JavaScript challenges with a JS runtime (its yt-dlp-ejs extra): Deno
COPY --from=deno /deno /usr/local/bin/deno
WORKDIR /app
COPY tabstealth/api/requirements.txt requirements.txt
RUN pip install -r requirements.txt "yt-dlp[default]==2026.10.26"
# The shared packages: the account (login, two-step login) and the web security building blocks
COPY packages/accounts /tmp/accounts
COPY packages/websec /tmp/websec
RUN pip install /tmp/websec /tmp/accounts && rm -rf /tmp/websec /tmp/accounts
COPY tabstealth/api/ ./
RUN useradd --uid 1000 --create-home appuser && mkdir -p /data && chown -R appuser:appuser /data /app
ENV TABSTEALTH_DATA=/data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/api/health' % os.environ.get('PORT','8000')).getcode()==200 else 1)"
# HOST 0.0.0.0, not :: (otherwise the IPv4 healthcheck on Railway fails).
CMD ["sh", "-c", "exec uvicorn app:create_app --factory --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --no-proxy-headers --no-server-header"]
