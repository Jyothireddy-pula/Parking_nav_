from datetime import datetime, timezone

FRESH = "FRESH"
AGING = "AGING"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

# Configurable per entity type: how old an observation can be (in seconds)
# before it stops being FRESH, then AGING, then STALE. Beyond aging_seconds
# it is always STALE — there's no further category for "very old."
FRESHNESS_THRESHOLDS_SECONDS: dict[str, dict[str, int]] = {
    "parking": {"fresh_seconds": 300, "aging_seconds": 900},
    "gate": {"fresh_seconds": 180, "aging_seconds": 600},
    "road": {"fresh_seconds": 180, "aging_seconds": 600},
    "vehicle": {"fresh_seconds": 60, "aging_seconds": 300},
}


def compute_freshness(
    observation_timestamp: datetime | None, entity_type: str, now: datetime | None = None
) -> str:
    """A missing observation is UNKNOWN, never presented as current. An
    observation is FRESH/AGING/STALE based on its age against this entity
    type's configured thresholds."""

    if observation_timestamp is None:
        return UNKNOWN
    if entity_type not in FRESHNESS_THRESHOLDS_SECONDS:
        raise ValueError(f"no freshness thresholds configured for entity type {entity_type!r}")

    now = now or datetime.now(timezone.utc)
    if observation_timestamp.tzinfo is None:
        # Some DB backends (e.g. SQLite) don't round-trip tzinfo; every
        # timestamp this system writes is UTC, so treat a naive value as UTC
        # rather than comparing naive-to-aware and crashing.
        observation_timestamp = observation_timestamp.replace(tzinfo=timezone.utc)
    age_seconds = (now - observation_timestamp).total_seconds()
    thresholds = FRESHNESS_THRESHOLDS_SECONDS[entity_type]

    if age_seconds < 0:
        # An observation timestamped in the future is not "fresher than
        # fresh" — treat it as freshly observed rather than extrapolate.
        return FRESH
    if age_seconds <= thresholds["fresh_seconds"]:
        return FRESH
    if age_seconds <= thresholds["aging_seconds"]:
        return AGING
    return STALE
