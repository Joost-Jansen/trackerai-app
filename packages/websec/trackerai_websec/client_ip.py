"""The real client address behind a reverse proxy, without trusting headers anyone can send.

`CF-Connecting-IP` and `X-Forwarded-For` are plain request headers: a visitor who reaches the app directly (or over a
VPN listener of the proxy) can set them to any value and so dodge a per-IP limit. They are only believed when the
socket peer is one of the configured proxies (TRUSTED_PROXIES, comma-separated IPs or CIDRs). Without that setting the
socket peer is the client.

    trusted = trusted_networks(os.environ.get("TRUSTED_PROXIES"))
    ip = client_ip(request, trusted)
"""

from __future__ import annotations

import ipaddress
from typing import Iterable

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def trusted_networks(env_value: str | None) -> list[Network]:
    """"10.0.0.0/8, 172.18.0.2" -> networks. Raises ValueError for an entry that is not an IP or CIDR (a typo must
    not silently trust nothing, or everything)."""
    out: list[Network] = []
    for part in (env_value or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(ipaddress.ip_network(part, strict=False))
    return out


def _parse(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    value = value.strip().strip('"')
    if value.startswith("[") and "]" in value:  # [2001:db8::1]:443
        value = value[1 : value.index("]")]
    elif value.count(":") == 1:  # 203.0.113.7:51234
        value = value.split(":", 1)[0]
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if isinstance(ip, ipaddress.IPv6Address) else ip


def is_trusted(ip: str | None, trusted: Iterable[Network]) -> bool:
    addr = _parse(ip)
    return addr is not None and any(addr in net for net in trusted)


def client_ip(request, trusted: Iterable[Network]) -> str:
    """The client's IP as a string ("unknown" when there is no peer at all, e.g. some test clients).

    Only when the socket peer is trusted: `CF-Connecting-IP` (set by Cloudflare, and overwritten by the edge proxy
    on any listener that Cloudflare does not front), else the rightmost hop of `X-Forwarded-For` that is not itself
    a trusted proxy (hops left of it were written by the client and prove nothing)."""
    trusted = list(trusted)
    peer = request.client.host if getattr(request, "client", None) else None
    if not peer:
        return "unknown"
    if not is_trusted(peer, trusted):
        return str(_parse(peer) or peer)
    cf = _parse(request.headers.get("cf-connecting-ip"))
    if cf is not None:
        return str(cf)
    hops = [h for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    for hop in reversed(hops):
        addr = _parse(hop)
        if addr is None:
            break  # garbage in the chain: stop believing it
        if not any(addr in net for net in trusted):
            return str(addr)
    return str(_parse(peer) or peer)
