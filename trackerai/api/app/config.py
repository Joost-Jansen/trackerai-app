"""trackerai-api's settings, all from the environment (no per-deployment values in code).

    PUBLIC_ORIGINS        where the front door is served, e.g. "https://www.trackerai.nl,https://trackerai.nl"
    TRUSTED_PROXIES       whose X-Forwarded-For is believed (Railway's proxy), IPs or CIDRs
    HEALTH_API_URL        health-tracker's API, for the admin page's hub (else LANDING_HEALTH_URL)
    WEALTH_API_URL        wealth-tracker's API, the same (else LANDING_WEALTH_URL)
    COOKIE_SECURE         "false" only on plain http (development); also turns HSTS off

The account itself (ACCOUNTS_*, SESSION_COOKIE_DOMAIN, REQUIRE_TOTP, mail) is read by packages/accounts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

# The API answers JSON, never HTML to render: nothing may load, frame or run from its responses.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _list(value: str | None) -> list[str]:
    return [v.strip().rstrip("/") for v in (value or "").split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    public_origins: list[str] = field(default_factory=list)
    trusted_proxies: str = ""
    trackers: dict[str, str] = field(default_factory=dict)  # {app: its API base, without /api}
    cookie_secure: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        trackers = {}
        for app in ("health", "wealth"):
            base = env.get(f"{app.upper()}_API_URL") or env.get(f"LANDING_{app.upper()}_URL")
            if base:
                trackers[app] = base.strip().rstrip("/")
        return cls(
            public_origins=_list(env.get("PUBLIC_ORIGINS")),
            trusted_proxies=env.get("TRUSTED_PROXIES", ""),
            trackers=trackers,
            cookie_secure=env.get("COOKIE_SECURE", "true").lower() != "false",
        )
