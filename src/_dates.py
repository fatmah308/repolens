"""Small shared date helpers. GitHub returns ISO-8601 UTC timestamps like
``2024-05-01T12:34:56Z``; these helpers keep the parsing logic in one place
so every tool computes ages/staleness the same way.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_github_datetime(value: str) -> datetime:
    """Parse a GitHub API timestamp into a timezone-aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
