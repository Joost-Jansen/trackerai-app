# Stock Tracker API (FastAPI) container image.
#
# Build context is the trackerai repository root — see docker-compose.yml's
# `build: {context: .., dockerfile: wealth-tracker/backend/Dockerfile}` — for
# the shared packages (packages/accounts, packages/websec) next to wealth-tracker/; the image
# holds wealth-tracker/ as /app, as before. Dockerfile.dockerignore next to this
# file lists what goes in.
# Runtime state (per-user SQLite DBs, uploads, auth_config.yaml) is bind-
# mounted at runtime, same as the Streamlit image.
FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The app stores and displays timestamps as naive *local* time (see the
# frontend's lib/format.ts, "sqlite, local time"). The slim image ships no
# tzdata, so its local time is UTC — which made "prices updated" read 2 hours
# off (the CEST offset) right after a refresh, because the browser parses the
# same naive string as its own local time. Pin the container to Amsterdam so
# server-side datetime.now() agrees with the browser.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Amsterdam

COPY wealth-tracker/requirements.txt ./requirements.txt
COPY wealth-tracker/backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt
# The shared packages: the trackerai account (login, two-step login) and the web security building blocks
COPY packages/accounts /tmp/accounts
COPY packages/websec /tmp/websec
RUN pip install /tmp/websec /tmp/accounts && rm -rf /tmp/websec /tmp/accounts

COPY wealth-tracker/ .

RUN useradd --uid 1000 --create-home appuser
USER appuser

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/api/health' % os.environ.get('PORT','8000')).getcode()==200 else 1)"

# HOST and PORT from the environment, with the Pi values as default. 0.0.0.0 also
# works on Railway: the private network there has IPv4, and the healthcheck comes
# in over IPv4. Only an old, IPv6-only Railway environment needs HOST=::.
#
# --no-proxy-headers: uvicorn would otherwise rewrite the client address from
# X-Forwarded-For for some peers itself. The app decides that, and only for
# TRUSTED_PROXIES (app/core/throttle.py). --no-server-header: no version banner.
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"${HOST:-0.0.0.0}\" --port \"${PORT:-8000}\" --no-proxy-headers --no-server-header"]
