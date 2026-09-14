"""The allocation strategy interface Module 7's engine calls into on every
vehicle assignment. Module 7 ships exactly one strategy —
NearestAvailableLotStrategy — as the minimum needed to make the engine
runnable and testable; it is a placeholder, not an optimizer. Module 8
supplies real (predictive, load-balancing, etc.) strategies against this
same interface without the engine changing.
"""

from dataclasses import dataclass
from random import Random
from typing import Protocol


@dataclass(frozen=True)
class LotCandidate:
    lot_id: str
    travel_time_s: float
    # Capacity as the strategy is allowed to see it — jittered by the
    # scenario's prediction_error_level. The engine's own bookkeeping
    # (capacity-never-exceeded) always uses the true count, never this.
    apparent_available: float


@dataclass(frozen=True)
class AllocationContext:
    minute: int
    gate_id: str
    candidates: list[LotCandidate]
    rng: Random


class AllocationStrategy(Protocol):
    def choose(self, context: AllocationContext) -> str | None:
        """Return the chosen lot_id, or None if no candidate should be
        assigned (e.g. all apparently full)."""
        ...


class NearestAvailableLotStrategy:
    """Picks the candidate with the shortest travel time among those that
    appear to have room. Ties broken by lot_id for determinism."""

    def choose(self, context: AllocationContext) -> str | None:
        viable = [c for c in context.candidates if c.apparent_available > 0]
        if not viable:
            return None
        viable.sort(key=lambda c: (c.travel_time_s, c.lot_id))
        return viable[0].lot_id
