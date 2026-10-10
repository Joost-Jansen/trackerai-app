"""
The app's rate limits and the visitor's address — wiring around app/websec.

The primary guard against floods is a rate-limiting rule at the edge
(Cloudflare, see docs/DEPLOY.md). These in-memory limits are the backstop for
whatever gets through, and the only layer that can count per *account*. They
reset on a restart; that is acceptable for a single-box deploy.

The client address comes from `websec.client_ip`: forwarding headers
(CF-Connecting-IP, X-Forwarded-For) are only believed when the socket peer is
one of TRUSTED_PROXIES (comma-separated IPs/CIDRs, e.g. the docker network of
the shared Caddy). Without it every request counts as its socket peer, so a
client that reaches the app directly cannot pick its own address to dodge the
per-IP limits.
"""

import os

from fastapi import Request

from trackerai_websec.client_ip import client_ip as _client_ip
from trackerai_websec.client_ip import trusted_networks
from trackerai_websec.throttle import Limiter

TRUSTED = trusted_networks(os.environ.get("TRUSTED_PROXIES"))

# The same numbers in health-tracker.
LOGIN_PER_USER = Limiter(10, 15 * 60)
LOGIN_PER_IP = Limiter(30, 15 * 60)
REGISTER_PER_IP = Limiter(5, 60 * 60)
# Failed agent/MCP token attempts per IP: a token is long and random, so this
# only stops someone from hammering the endpoint, never a real client.
AGENT_FAILURES_PER_IP = Limiter(20, 15 * 60)
# Failed password re-entry for account deletion / two-step changes, per user.
REAUTH_PER_USER = Limiter(10, 15 * 60)

ALL = (LOGIN_PER_USER, LOGIN_PER_IP, REGISTER_PER_IP, AGENT_FAILURES_PER_IP, REAUTH_PER_USER)


def client_ip(request: Request) -> str:
    return _client_ip(request, TRUSTED)


def peer_is_trusted(request: Request) -> bool:
    """The socket peer is one of TRUSTED_PROXIES (so its forwarding headers count)."""
    import ipaddress

    try:
        peer = ipaddress.ip_address(request.client.host) if request.client else None
    except ValueError:
        return False
    return peer is not None and any(peer in net for net in TRUSTED if peer.version == net.version)


def reset_all() -> None:
    for limiter in ALL:
        limiter.reset()
