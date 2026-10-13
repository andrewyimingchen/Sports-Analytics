"""Optional error tracking (Sentry), off unless ``SENTRY_DSN`` is set.

Install with ``uv sync --extra monitoring``. Events carry no personal data:
query strings (which can hold player names), cookies, and auth headers
(``X-API-Key``, ``Authorization``) are stripped before sending, matching the
central handler's rule of logging method and path only.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization"}
_enabled = False


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Drop query strings, cookies, and auth headers from a Sentry event."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("query_string", None)
        request.pop("cookies", None)
        request.pop("data", None)
        if isinstance(request.get("url"), str):
            request["url"] = request["url"].split("?", 1)[0]
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: value
                for key, value in headers.items()
                if key.lower() not in _SENSITIVE_HEADERS
            }
    return event


def init_error_tracking() -> bool:
    """Start Sentry when ``SENTRY_DSN`` is set and the extra is installed."""
    global _enabled
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is missing: uv sync --extra monitoring")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE"),
        send_default_pii=False,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        before_send=scrub_event,  # type: ignore[arg-type]
    )
    _enabled = True
    logger.info("error tracking enabled")
    return True


def capture_exception(error: BaseException) -> None:
    """Report an unexpected exception (no-op unless error tracking is on)."""
    if not _enabled:
        return
    import sentry_sdk

    sentry_sdk.capture_exception(error)
