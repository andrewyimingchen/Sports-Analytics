"""Access controls and in-process request budgets for sensitive API routes.

The defaults keep direct localhost development frictionless. Remote AI and
salary access require an API key; simulations remain public but rate-limited
unless ``POSSESSION_LAB_REQUIRE_API_KEY`` is enabled. Forwarding headers only
affect client identity when the immediate peer is explicitly trusted.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from math import ceil

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_FORWARDED_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("ignoring invalid integer in %s", name)
        return default
    if value < 1:
        logger.warning("ignoring non-positive integer in %s", name)
        return default
    return value


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


def _trusted_proxy_ips() -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    trusted = set()
    for raw in os.environ.get("POSSESSION_LAB_TRUSTED_PROXY_IPS", "").split(","):
        if raw.strip() and (address := _ip(raw)) is not None:
            trusted.add(address)
    return trusted


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _peer_is_trusted_proxy(request: Request) -> bool:
    peer = _ip(_peer_host(request))
    return peer is not None and peer in _trusted_proxy_ips()


def client_identity(request: Request) -> str:
    """Return a stable rate-limit identity, honoring only trusted proxies."""
    peer = _peer_host(request)
    if _peer_is_trusted_proxy(request):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0]
        if forwarded and (address := _ip(forwarded)) is not None:
            return str(address)
        real_ip = request.headers.get("x-real-ip", "")
        if real_ip and (address := _ip(real_ip)) is not None:
            return str(address)
    return peer


def is_local_request(request: Request) -> bool:
    """Whether the original caller is safely known to be local.

    TestClient is admitted for endpoint coverage. A loopback peer carrying an
    untrusted forwarding header is treated as remote; this prevents a reverse
    proxy from accidentally turning every internet caller into localhost.
    """
    peer = _peer_host(request)
    if peer == "testclient":
        return True
    forwarded = any(request.headers.get(name) for name in _FORWARDED_HEADERS)
    if forwarded and not _peer_is_trusted_proxy(request):
        return False
    identity = _ip(client_identity(request))
    return bool(identity and identity.is_loopback)


def _provided_api_key(request: Request) -> str:
    direct = request.headers.get("x-api-key", "").strip()
    if direct:
        return direct
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    return credential.strip() if scheme.lower() == "bearer" else ""


def has_valid_api_key(request: Request) -> bool:
    expected = os.environ.get("POSSESSION_LAB_API_KEY", "")
    provided = _provided_api_key(request)
    return bool(expected and provided and secrets.compare_digest(expected, provided))


def can_access_private_data(request: Request) -> bool:
    return is_local_request(request) or has_valid_api_key(request)


def require_private_access(request: Request) -> None:
    """Require direct-local access or the configured API key."""
    if can_access_private_data(request):
        return
    if not os.environ.get("POSSESSION_LAB_API_KEY"):
        raise HTTPException(403, "remote access to this endpoint is disabled")
    raise HTTPException(
        401,
        "a valid API key is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_simulation_access(request: Request) -> None:
    """Optionally require remote simulation callers to authenticate."""
    if _enabled("POSSESSION_LAB_REQUIRE_API_KEY") and not is_local_request(request):
        require_private_access(request)


class SlidingWindowBudget:
    """Small per-process weighted request budget with a sliding time window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._events: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._lock = threading.Lock()

    def consume(self, key: str, cost: int, limit: int, window_seconds: int) -> None:
        now = self._clock()
        with self._lock:
            events = self._events[key]
            cutoff = now - window_seconds
            while events and events[0][0] <= cutoff:
                events.popleft()
            used = sum(event_cost for _, event_cost in events)
            if cost > limit or used + cost > limit:
                retry_after = (
                    window_seconds
                    if not events
                    else max(1, ceil(events[0][0] + window_seconds - now))
                )
                raise HTTPException(
                    429,
                    "request budget exceeded; retry later",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append((now, cost))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_BUDGET = SlidingWindowBudget()


def protect_simulation(request: Request, *, cost: int) -> None:
    """Apply optional API-key auth and a weighted simulation budget."""
    require_simulation_access(request)
    _BUDGET.consume(
        f"simulation:{client_identity(request)}",
        cost=max(1, int(cost)),
        limit=_positive_int("POSSESSION_LAB_SIMULATION_BUDGET", 100_000),
        window_seconds=_positive_int("POSSESSION_LAB_RATE_WINDOW_SECONDS", 60),
    )


def protect_ai(request: Request) -> None:
    """Keep paid AI remote access authenticated and request-budgeted."""
    require_private_access(request)
    _BUDGET.consume(
        f"ai:{client_identity(request)}",
        cost=1,
        limit=_positive_int("POSSESSION_LAB_AI_REQUEST_BUDGET", 5),
        window_seconds=_positive_int("POSSESSION_LAB_RATE_WINDOW_SECONDS", 60),
    )
