"""Expected failure categories and their stable reason codes.

Graceful degradation catches only these. Anything else (TypeError,
AttributeError, a bug in an analysis function) propagates to the API's
central handler, which logs it and answers 500 ``internal_error`` instead of
dressing a defect up as "data unavailable".

The analysis layer signals a missing player/column with ``KeyError`` and an
unusable input with ``ValueError`` (project convention), and positional
lookups on an empty frame raise ``IndexError``; :data:`DATA_ERRORS` treats
those as data problems.
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import ClassVar


class NBAInsightsError(Exception):
    """Base for expected, categorized failures."""

    reason: ClassVar[str] = "internal_error"


class UpstreamError(NBAInsightsError):
    """A remote source (stats.nba.com, a CDN, a scraped page) failed after retries."""

    reason = "upstream_unavailable"


class DataUnavailableError(NBAInsightsError):
    """The data exists but lacks what this view needs (rows, columns, a season)."""

    reason = "data_unavailable"


class ArtifactUnavailableError(NBAInsightsError):
    """A trained model or metrics artifact is missing or unreadable."""

    reason = "artifact_unavailable"


class ProviderError(NBAInsightsError):
    """An optional third-party service (the AI provider) failed."""

    reason = "provider_failed"


DATA_ERRORS: tuple[type[Exception], ...] = (DataUnavailableError, KeyError, ValueError, IndexError)
EXPECTED_ERRORS: tuple[type[Exception], ...] = (
    UpstreamError,
    ArtifactUnavailableError,
    *DATA_ERRORS,
)


def reason_for(error: BaseException) -> str:
    """Stable machine-readable code for an expected (or unexpected) failure."""
    if isinstance(error, NBAInsightsError):
        return error.reason
    if isinstance(error, DATA_ERRORS):
        return DataUnavailableError.reason
    return NBAInsightsError.reason


class FailureCounter:
    """Process-wide tally of failures by reason, surfaced on /readyz."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def record(self, reason: str) -> None:
        with self._lock:
            self._counts[reason] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()


FAILURES = FailureCounter()
