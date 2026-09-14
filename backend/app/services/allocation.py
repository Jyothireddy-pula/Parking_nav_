"""The allocation strategy interface Module 7's engine calls into on every
vehicle assignment.

Module 7 shipped exactly one strategy (NearestAvailableLotStrategy) as the
minimum needed to make the engine runnable and testable. Module 8 adds two
more baselines plus a registry so ExperimentRunner can address strategies by
name. All three here are baselines, not the optimizer:

- B1 FirstAvailableStrategy: no intelligence at all — takes whichever lot
  with room sorts first by lot_id. The floor every real strategy must beat.
- B2 NearestAvailableLotStrategy: Module 7's original, using Module 6's real
  travel times.
- B3 PredictionOnlyStrategy: a STUB. It load-balances on apparent_available
  (the jittered occupancy signal already computed by the engine from
  prediction_error_level) because no real prediction service exists yet.
  Module 11 replaces its internals with actual predicted demand/availability
  — the interface and registry key ("prediction_only") stay the same.
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


class FirstAvailableStrategy:
    """B1 baseline: the first candidate (by lot_id, for determinism) that
    appears to have room. Ignores travel time and load entirely — the
    simplest possible policy, useful as a floor for comparison."""

    def choose(self, context: AllocationContext) -> str | None:
        viable = [c for c in context.candidates if c.apparent_available > 0]
        if not viable:
            return None
        return min(viable, key=lambda c: c.lot_id).lot_id


class NearestAvailableLotStrategy:
    """B2 baseline: picks the candidate with the shortest travel time among
    those that appear to have room. Ties broken by lot_id for determinism."""

    def choose(self, context: AllocationContext) -> str | None:
        viable = [c for c in context.candidates if c.apparent_available > 0]
        if not viable:
            return None
        viable.sort(key=lambda c: (c.travel_time_s, c.lot_id))
        return viable[0].lot_id


class PredictionOnlyStrategy:
    """B3 baseline — STUB until Module 11 ships a real prediction service.

    For now this load-balances on apparent_available (the same jittered
    occupancy signal the engine already exposes to every strategy), picking
    the candidate that appears to have the most room, ignoring travel time.
    That is a deliberately simple stand-in, not a prediction: it exists so
    the experiment runner has a third strategy to compare against B1/B2 and
    so later modules can drop a real predictor in without changing callers.
    """

    def choose(self, context: AllocationContext) -> str | None:
        viable = [c for c in context.candidates if c.apparent_available > 0]
        if not viable:
            return None
        viable.sort(key=lambda c: (-c.apparent_available, c.lot_id))
        return viable[0].lot_id


STRATEGY_REGISTRY: dict[str, type] = {
    "first_available": FirstAvailableStrategy,
    "nearest_available": NearestAvailableLotStrategy,
    "prediction_only": PredictionOnlyStrategy,
}


def build_strategy(name: str) -> AllocationStrategy:
    try:
        return STRATEGY_REGISTRY[name]()
    except KeyError:
        raise UnknownStrategyError(name) from None


class UnknownStrategyError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"unknown allocation strategy {name!r}; known: {sorted(STRATEGY_REGISTRY)}")
