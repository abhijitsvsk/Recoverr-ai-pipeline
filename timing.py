"""
Timing Module for RecoverAI Payment Recovery Agent.
Manages retry backoff interval timing based on DEMO_MODE env variable.
AGENTS.md Rule 11: DEMO_MODE changes only timing (retry backoff), never policy logic.
"""

import os
from datetime import datetime, timezone
from typing import Optional

DEFAULT_DEMO_RETRY_BACKOFF_SECONDS = 15     # 15 seconds in DEMO_MODE=true
DEFAULT_PROD_RETRY_BACKOFF_SECONDS = 900    # 15 minutes (900s) in Production (DEMO_MODE=false)


def is_demo_mode() -> bool:
    """Return True if DEMO_MODE environment variable is set to true (default: True)."""
    val = os.environ.get("DEMO_MODE", "true").lower()
    return val in ("true", "1", "yes")


def get_retry_backoff_seconds() -> int:
    """
    Return the minimum required backoff interval in seconds before a RETRY is permitted.
    DEMO_MODE=true  -> 15 seconds
    DEMO_MODE=false -> 900 seconds (15 minutes)
    """
    if is_demo_mode():
        return DEFAULT_DEMO_RETRY_BACKOFF_SECONDS
    return DEFAULT_PROD_RETRY_BACKOFF_SECONDS


def is_retry_backoff_satisfied(
    last_attempt_at_str: Optional[str],
    ref_dt: Optional[datetime] = None,
    override_backoff_seconds: Optional[int] = None,
) -> bool:
    """
    Check if the time elapsed since last_attempt_at satisfies the required retry backoff interval.
    
    :param last_attempt_at_str: ISO formatted timestamp string of the last attempt
    :param ref_dt: Reference datetime for evaluation (defaults to datetime.now(timezone.utc))
    :param override_backoff_seconds: Optional explicit backoff threshold in seconds
    :return: True if elapsed time >= required backoff seconds, False otherwise
    """
    if not last_attempt_at_str:
        return True  # If unknown, assume satisfied

    required_seconds = (
        override_backoff_seconds
        if override_backoff_seconds is not None
        else get_retry_backoff_seconds()
    )

    try:
        clean_str = last_attempt_at_str.replace("Z", "+00:00")
        last_attempt_dt = datetime.fromisoformat(clean_str)
        if last_attempt_dt.tzinfo is None:
            last_attempt_dt = last_attempt_dt.replace(tzinfo=timezone.utc)

        if ref_dt is None:
            ref_dt = datetime.now(timezone.utc)
        elif ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        elapsed = (ref_dt - last_attempt_dt).total_seconds()
        return elapsed >= required_seconds
    except Exception:
        return True  # Graceful fallback on parse error
