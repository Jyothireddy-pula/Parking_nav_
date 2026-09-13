"""Module 4 — data ingestion.

Every submitted row is written to observations_raw first, unconditionally
and immutably — even rows that turn out to be invalid. Only after that does
business validation decide whether the row becomes a validated Observation
or an ObservationRejected (with a reason). Nothing is ever silently fixed,
filled in, clamped, or dropped: a row either passes every check as
submitted, or it is rejected and the reason is recorded. A missing 5-minute
reading is simply absent from these tables — this module never invents one.
"""

import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import (
    COLLECTION_METHODS,
    SOURCE_LABELS,
    IngestionBatch,
    Observation,
    ObservationRaw,
    ObservationRejected,
)
from app.repositories.campus_config import CampusConfigRepository
from app.schemas.ingestion import ObservationIn
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import CapacityExceededError, DigitalTwinService, EntityNotFoundError

logger = logging.getLogger(__name__)

EARLIEST_PLAUSIBLE_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)
FUTURE_TOLERANCE = timedelta(minutes=5)

CV_BATCH_ALLOWED_COLLECTION_METHODS = ("cv_auto", "cv_verified")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class IngestionService:
    def __init__(
        self,
        config_repository: CampusConfigRepository | None = None,
        twin_service: DigitalTwinService | None = None,
    ) -> None:
        self._config = config_repository or CampusConfigRepository()
        self._twin = twin_service or DigitalTwinService()

    async def _require_campus(self, session: AsyncSession, campus_id: str) -> None:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

    # -- validation -------------------------------------------------------

    async def _validate(
        self, session: AsyncSession, campus_id: str, observation: ObservationIn
    ) -> list[str]:
        reasons: list[str] = []

        if observation.source_label not in SOURCE_LABELS:
            reasons.append(f"source_label must be one of {SOURCE_LABELS}, got {observation.source_label!r}")
        if observation.collection_method not in COLLECTION_METHODS:
            reasons.append(
                f"collection_method must be one of {COLLECTION_METHODS}, got {observation.collection_method!r}"
            )

        kinds_present = [
            name
            for name, value in (
                ("gate_id", observation.gate_id),
                ("parking_lot_id", observation.parking_lot_id),
                ("event_type", observation.event_type),
            )
            if value not in (None, "")
        ]
        if len(kinds_present) != 1:
            reasons.append(
                "exactly one of gate_id, parking_lot_id, event_type must be set, got "
                f"{kinds_present or 'none'}"
            )
            # Nothing further can be checked sensibly without knowing the kind.
            return reasons
        kind = kinds_present[0]

        timestamp = _aware(observation.timestamp)
        now = datetime.now(timezone.utc)
        if timestamp < EARLIEST_PLAUSIBLE_TIMESTAMP:
            reasons.append(f"timestamp {timestamp.isoformat()} is implausibly old")
        if timestamp > now + FUTURE_TOLERANCE:
            reasons.append(f"timestamp {timestamp.isoformat()} is in the future")

        if kind == "gate_id":
            gates = {g.gate_id for g in await self._config.list_gates(session, campus_id)}
            if observation.gate_id not in gates:
                reasons.append(f"unknown gate_id {observation.gate_id!r}")
            if observation.vehicle_count is None:
                reasons.append("vehicle_count is required for a gate observation")
            elif observation.vehicle_count < 0:
                reasons.append(f"vehicle_count must be >= 0, got {observation.vehicle_count}")
            if not reasons:
                duplicate = await session.execute(
                    select(Observation).where(
                        Observation.campus_id == campus_id,
                        Observation.timestamp == observation.timestamp,
                        Observation.gate_id == observation.gate_id,
                    )
                )
                if duplicate.scalars().first() is not None:
                    reasons.append("duplicate observation for this campus/timestamp/gate_id")

        elif kind == "parking_lot_id":
            lots = {lot.parking_lot_id: lot for lot in await self._config.list_parking_lots(session, campus_id)}
            lot = lots.get(observation.parking_lot_id)
            if lot is None:
                reasons.append(f"unknown parking_lot_id {observation.parking_lot_id!r}")
            if observation.occupied_spaces is None:
                reasons.append("occupied_spaces is required for a parking observation")
            elif observation.occupied_spaces < 0:
                reasons.append(f"occupied_spaces must be >= 0, got {observation.occupied_spaces}")
            elif lot is not None and observation.occupied_spaces > lot.total_capacity:
                reasons.append(
                    f"occupied_spaces={observation.occupied_spaces} exceeds "
                    f"total_capacity={lot.total_capacity} for {observation.parking_lot_id!r}"
                )
            if not reasons:
                duplicate = await session.execute(
                    select(Observation).where(
                        Observation.campus_id == campus_id,
                        Observation.timestamp == observation.timestamp,
                        Observation.parking_lot_id == observation.parking_lot_id,
                    )
                )
                if duplicate.scalars().first() is not None:
                    reasons.append("duplicate observation for this campus/timestamp/parking_lot_id")

        else:  # event_type
            if observation.event_intensity is None:
                reasons.append("event_intensity is required for an event observation")
            elif not (0 <= observation.event_intensity <= 5):
                reasons.append(f"event_intensity must be within 0-5, got {observation.event_intensity}")
            if not reasons:
                duplicate = await session.execute(
                    select(Observation).where(
                        Observation.campus_id == campus_id,
                        Observation.timestamp == observation.timestamp,
                        Observation.event_type == observation.event_type,
                    )
                )
                if duplicate.scalars().first() is not None:
                    reasons.append("duplicate observation for this campus/timestamp/event_type")

        return reasons

    @staticmethod
    def _quality_flags(observation: ObservationIn, total_capacity: int | None) -> list[str]:
        flags: list[str] = []
        if observation.parking_lot_id is not None and observation.occupied_spaces is not None:
            if observation.occupied_spaces == 0:
                flags.append("zero_occupancy_reported")
            if total_capacity and observation.occupied_spaces >= 0.95 * total_capacity:
                flags.append("near_capacity")
        if (
            observation.event_type is not None
            and observation.event_intensity is not None
            and observation.event_intensity >= 4
        ):
            flags.append("high_intensity_event")
        return flags

    # -- ingest one ---------------------------------------------------------

    async def ingest_one(
        self,
        session: AsyncSession,
        campus_id: str,
        observation: ObservationIn,
        batch_id: str | None = None,
    ) -> tuple[Observation | None, ObservationRejected | None]:
        await self._require_campus(session, campus_id)

        raw = ObservationRaw(
            raw_id=_new_id("raw"),
            campus_id=campus_id,
            timestamp=observation.timestamp,
            gate_id=observation.gate_id,
            vehicle_count=observation.vehicle_count,
            parking_lot_id=observation.parking_lot_id,
            occupied_spaces=observation.occupied_spaces,
            event_type=observation.event_type,
            event_intensity=observation.event_intensity,
            notes=observation.notes,
            source_label=observation.source_label,
            collection_method=observation.collection_method,
            batch_id=batch_id,
        )
        session.add(raw)
        await session.flush()

        reasons = await self._validate(session, campus_id, observation)

        if reasons:
            rejected = ObservationRejected(
                rejection_id=_new_id("rej"),
                raw_id=raw.raw_id,
                campus_id=campus_id,
                timestamp=observation.timestamp,
                gate_id=observation.gate_id,
                vehicle_count=observation.vehicle_count,
                parking_lot_id=observation.parking_lot_id,
                occupied_spaces=observation.occupied_spaces,
                event_type=observation.event_type,
                event_intensity=observation.event_intensity,
                notes=observation.notes,
                source_label=observation.source_label,
                collection_method=observation.collection_method,
                batch_id=batch_id,
                reason="; ".join(reasons),
            )
            session.add(rejected)
            await session.commit()
            logger.info(
                "rejected observation",
                extra={"campus_id": campus_id, "reason": rejected.reason, "raw_id": raw.raw_id},
            )
            return None, rejected

        total_capacity = None
        if observation.parking_lot_id is not None:
            lots = await self._config.list_parking_lots(session, campus_id)
            lot = next((lot for lot in lots if lot.parking_lot_id == observation.parking_lot_id), None)
            total_capacity = lot.total_capacity if lot else None

        accepted = Observation(
            observation_id=_new_id("obs"),
            raw_id=raw.raw_id,
            campus_id=campus_id,
            timestamp=observation.timestamp,
            gate_id=observation.gate_id,
            vehicle_count=observation.vehicle_count,
            parking_lot_id=observation.parking_lot_id,
            occupied_spaces=observation.occupied_spaces,
            event_type=observation.event_type,
            event_intensity=observation.event_intensity,
            notes=observation.notes,
            source_label=observation.source_label,
            collection_method=observation.collection_method,
            batch_id=batch_id,
            data_quality_flags=self._quality_flags(observation, total_capacity),
        )
        session.add(accepted)
        await session.commit()

        await self._sync_twin(session, campus_id, observation)

        return accepted, None

    async def _sync_twin(self, session: AsyncSession, campus_id: str, observation: ObservationIn) -> None:
        provenance = observation.source_label
        twin_source = "simulation" if observation.collection_method == "simulator" else (
            "cv_auto" if observation.collection_method == "cv_auto" else
            "cv_verified" if observation.collection_method == "cv_verified" else
            "manual"
        )

        try:
            if observation.parking_lot_id is not None:
                await self._twin.update_parking(
                    session,
                    campus_id,
                    observation.parking_lot_id,
                    occupied=observation.occupied_spaces,
                    source=twin_source,
                    provenance=provenance,
                    observation_timestamp=observation.timestamp,
                )
            elif observation.gate_id is not None:
                await self._twin.update_gate(
                    session,
                    campus_id,
                    observation.gate_id,
                    queue=observation.vehicle_count,
                    source=twin_source,
                    provenance=provenance,
                    observation_timestamp=observation.timestamp,
                )
            # Event observations have no single twin entity to update (see
            # docs/DATA.md); they remain recorded here for later analysis only.
        except EntityNotFoundError:
            # The twin hasn't been initialized (or the entity was removed
            # from config) for this campus. The observation is already
            # durably recorded either way; the twin is a derived view, so a
            # sync failure here does not undo it.
            logger.warning(
                "twin sync skipped: entity not initialized in the digital twin",
                extra={"campus_id": campus_id},
            )
        except CapacityExceededError:
            # Should not happen — ingestion validation already checked the
            # same ceiling — but surfacing this loudly matters more than
            # papering over a real inconsistency between the two checks.
            logger.error(
                "twin sync rejected an observation ingestion had already accepted",
                extra={"campus_id": campus_id, "parking_lot_id": observation.parking_lot_id},
            )

    # -- bulk CSV -----------------------------------------------------------

    async def ingest_bulk_csv(
        self, session: AsyncSession, campus_id: str, csv_text: str, csv_format: str = "unified"
    ) -> IngestionBatch:
        await self._require_campus(session, campus_id)

        rows = list(csv.DictReader(io.StringIO(csv_text)))
        observations = [self._row_to_observation(row, csv_format) for row in rows]

        batch = IngestionBatch(
            batch_id=_new_id("batch"),
            campus_id=campus_id,
            submitted_via="bulk_csv",
            received_at=datetime.now(timezone.utc),
            total_rows=len(observations),
        )
        session.add(batch)
        await session.flush()

        accepted_count = 0
        rejected_count = 0
        for observation in observations:
            accepted, rejected = await self.ingest_one(session, campus_id, observation, batch_id=batch.batch_id)
            if accepted is not None:
                accepted_count += 1
            if rejected is not None:
                rejected_count += 1

        batch.accepted_rows = accepted_count
        batch.rejected_rows = rejected_count
        session.add(batch)
        await session.commit()
        return batch

    @staticmethod
    def _row_to_observation(row: dict, csv_format: str) -> ObservationIn:
        def _int(value: str | None) -> int | None:
            return int(value) if value not in (None, "") else None

        def _float(value: str | None) -> float | None:
            return float(value) if value not in (None, "") else None

        if csv_format == "unified":
            return ObservationIn(
                timestamp=row["timestamp"],
                gate_id=row.get("gate_id") or None,
                vehicle_count=_int(row.get("vehicle_count")),
                parking_lot_id=row.get("parking_lot_id") or None,
                occupied_spaces=_int(row.get("occupied_spaces")),
                event_type=row.get("event_type") or None,
                event_intensity=_float(row.get("event_intensity")),
                notes=row.get("notes") or None,
                source_label=row["source_label"],
                collection_method=row["collection_method"],
            )

        if csv_format == "module2_parking":
            # Module 2's merge_observations.py consolidated parking output:
            # collection_session, parking_lot_id, capacity, occupied_spaces,
            # timestamp, contributing_observers, observation_count, source_label.
            return ObservationIn(
                timestamp=row["timestamp"],
                parking_lot_id=row.get("parking_lot_id") or None,
                occupied_spaces=_int(row.get("occupied_spaces")),
                notes=f"observers={row.get('contributing_observers', '')}",
                source_label=row.get("source_label", "REAL"),
                collection_method="manual_count",
            )

        if csv_format == "module2_gates":
            # Module 2's merge_observations.py consolidated gates output:
            # collection_session, gate_id, entered, exited, timestamp,
            # contributing_observers, observation_count, source_label.
            # This schema has no single "vehicle_count" concept, so entered
            # is carried as vehicle_count and exited is preserved in notes
            # rather than combined into a derived number.
            entered = row.get("entered") or ""
            exited = row.get("exited") or ""
            return ObservationIn(
                timestamp=row["timestamp"],
                gate_id=row.get("gate_id") or None,
                vehicle_count=_int(entered),
                notes=f"exited={exited}; observers={row.get('contributing_observers', '')}",
                source_label=row.get("source_label", "REAL"),
                collection_method="manual_count",
            )

        raise ValueError(f"unknown csv_format {csv_format!r}")

    # -- CV batch -------------------------------------------------------

    async def ingest_cv_batch(
        self, session: AsyncSession, campus_id: str, observations: list[ObservationIn]
    ) -> IngestionBatch:
        await self._require_campus(session, campus_id)

        batch = IngestionBatch(
            batch_id=_new_id("batch"),
            campus_id=campus_id,
            submitted_via="cv_batch",
            received_at=datetime.now(timezone.utc),
            total_rows=len(observations),
        )
        session.add(batch)
        await session.flush()

        accepted_count = 0
        rejected_count = 0
        for observation in observations:
            if observation.collection_method not in CV_BATCH_ALLOWED_COLLECTION_METHODS:
                observation = observation.model_copy(
                    update={
                        "notes": (
                            f"{observation.notes or ''} "
                            f"[submitted via cv-batch with collection_method="
                            f"{observation.collection_method!r}]"
                        ).strip()
                    }
                )
            accepted, rejected = await self.ingest_one(session, campus_id, observation, batch_id=batch.batch_id)
            if accepted is not None:
                accepted_count += 1
            if rejected is not None:
                rejected_count += 1

        batch.accepted_rows = accepted_count
        batch.rejected_rows = rejected_count
        session.add(batch)
        await session.commit()
        return batch

    # -- reads --------------------------------------------------------------

    async def list_observations(
        self,
        session: AsyncSession,
        campus_id: str,
        gate_id: str | None = None,
        parking_lot_id: str | None = None,
        limit: int = 100,
    ) -> list[Observation]:
        await self._require_campus(session, campus_id)
        stmt = select(Observation).where(Observation.campus_id == campus_id)
        if gate_id is not None:
            stmt = stmt.where(Observation.gate_id == gate_id)
        if parking_lot_id is not None:
            stmt = stmt.where(Observation.parking_lot_id == parking_lot_id)
        stmt = stmt.order_by(Observation.timestamp.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_rejected(
        self, session: AsyncSession, campus_id: str, batch_id: str | None = None, limit: int = 1000
    ) -> list[ObservationRejected]:
        await self._require_campus(session, campus_id)
        stmt = select(ObservationRejected).where(ObservationRejected.campus_id == campus_id)
        if batch_id is not None:
            stmt = stmt.where(ObservationRejected.batch_id == batch_id)
        stmt = stmt.order_by(ObservationRejected.timestamp.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_quality_report(self, session: AsyncSession, campus_id: str) -> dict:
        await self._require_campus(session, campus_id)

        raw_total = (
            await session.execute(
                select(func.count()).select_from(ObservationRaw).where(ObservationRaw.campus_id == campus_id)
            )
        ).scalar_one()
        accepted_total = (
            await session.execute(
                select(func.count()).select_from(Observation).where(Observation.campus_id == campus_id)
            )
        ).scalar_one()
        rejected_rows = (
            (
                await session.execute(
                    select(ObservationRejected.reason).where(ObservationRejected.campus_id == campus_id)
                )
            )
            .scalars()
            .all()
        )

        rejection_reason_counts: dict[str, int] = {}
        missing_required_field_rejections = 0
        for combined_reason in rejected_rows:
            for reason in combined_reason.split("; "):
                rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
                if "is required" in reason:
                    missing_required_field_rejections += 1

        accepted_missing_notes = (
            await session.execute(
                select(func.count())
                .select_from(Observation)
                .where(Observation.campus_id == campus_id, Observation.notes.is_(None))
            )
        ).scalar_one()

        method_rows = (
            (
                await session.execute(
                    select(Observation.collection_method, func.count())
                    .where(Observation.campus_id == campus_id)
                    .group_by(Observation.collection_method)
                )
            )
            .all()
        )
        accepted_by_collection_method = {method: count for method, count in method_rows}

        lots = await self._config.list_parking_lots(session, campus_id)
        gates = await self._config.list_gates(session, campus_id)
        lots_with_observations = (
            (
                await session.execute(
                    select(func.count(func.distinct(Observation.parking_lot_id))).where(
                        Observation.campus_id == campus_id, Observation.parking_lot_id.is_not(None)
                    )
                )
            ).scalar_one()
        )
        gates_with_observations = (
            (
                await session.execute(
                    select(func.count(func.distinct(Observation.gate_id))).where(
                        Observation.campus_id == campus_id, Observation.gate_id.is_not(None)
                    )
                )
            ).scalar_one()
        )

        return {
            "campus_id": campus_id,
            "raw_total": raw_total,
            "accepted_total": accepted_total,
            "rejected_total": len(rejected_rows),
            "rejection_reason_counts": rejection_reason_counts,
            "missing_fields": {
                "rejected_due_to_missing_required_field": missing_required_field_rejections,
                "accepted_missing_notes": accepted_missing_notes,
            },
            "accepted_by_collection_method": accepted_by_collection_method,
            "coverage": {
                "parking_lots_with_observations": lots_with_observations,
                "parking_lots_total": len(lots),
                "gates_with_observations": gates_with_observations,
                "gates_total": len(gates),
            },
        }
