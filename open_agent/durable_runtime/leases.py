"""Pure lease and retry-delay calculations for durable workers."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Callable

from .models import ClaimToken


def next_backoff(
    attempt: int,
    base_seconds: float,
    cap_seconds: float,
    jitter: float,
    *,
    random_source: Callable[[], float] | None = None,
) -> float:
    """Return a capped exponential delay with optional injected symmetric jitter."""
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise ValueError("attempt must be an integer")
    if attempt < 0:
        raise ValueError("attempt must not be negative")
    if not isfinite(base_seconds) or base_seconds <= 0:
        raise ValueError("base_seconds must be positive")
    if not isfinite(cap_seconds) or cap_seconds <= 0 or cap_seconds < base_seconds:
        raise ValueError("cap_seconds must be at least base_seconds")
    if not isfinite(jitter) or not 0 <= jitter <= 1:
        raise ValueError("jitter must be between 0 and 1")

    delay = base_seconds
    for _ in range(attempt):
        if delay >= cap_seconds / 2:
            delay = cap_seconds
            break
        delay *= 2
    if jitter == 0:
        return delay
    if random_source is None:
        raise ValueError("random_source is required when jitter is non-zero")

    draw = random_source()
    if not 0 <= draw <= 1:
        raise ValueError("random_source must return a value between 0 and 1")
    return min(cap_seconds, max(0.0, delay * (1 + jitter * ((2 * draw) - 1))))


def lease_is_valid(token: ClaimToken, now: datetime) -> bool:
    """Return whether *token* remains valid strictly after the supplied instant."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return token.expires_at > now
