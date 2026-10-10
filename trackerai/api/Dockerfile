# trackerai-api: the API behind trackerai.nl (login, sign-up, the account, the admin page's hub). FastAPI.
# It keeps no data of its own (the accounts database is shared), so the image holds only code.
#
# Build context: the repo root (`docker build -f trackerai/api/Dockerfile .`), for packages/.

FROM python:3.13-slim
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Amsterdam
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY trackerai/api/requirements.txt requirements.txt
RUN pip install -r requirements.txt
# The shared account (packages/accounts) and the security helpers (packages/websec)
COPY packages/accounts /tmp/accounts
COPY packages/websec /tmp/websec
RUN pip install /tmp/accounts /tmp/websec && rm -rf /tmp/accounts /tmp/websec
COPY trackerai/api/app/ app/
RUN useradd --uid 1000 --create-home appuser
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/api/health' % os.environ.get('PORT','8000')).getcode()==200 else 1)"
# HOST 0.0.0.0, not :: (otherwise the IPv4 healthcheck on Railway fails).
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --no-proxy-headers --no-server-header"]
