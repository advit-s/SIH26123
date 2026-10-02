"""Recording gaps: an explicit, visible hole in the evidence.

A gap is not an error to be smoothed over. It is a fact about the run, and any
metric that depends on the missing evidence must be reported ``excluded``
rather than computed from whatever happens to remain (``AGENTS.md`` rule 10:
missing metric is ``unavailable``, never zero).

:class:`RecordingGapTracker` is the single place that decides which metrics a gap
invalidates. ``rebuild_read_model`` and the evaluator consume the same tracker,
so a hole cannot be visible in one place and invisible in another.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from niharamesh.domain.telemetry import DURABLE_CATEGORIES, EventCategory, RecordingGap

__all__ = [
    "DEFAULT_AFFECTED_METRICS",
    "GapSummary",
    "RecordingGapTracker",
]

#: Metrics invalidated by a gap in each durable category. Conservative by
#: default: a hole in evaluation evidence invalidates every headline claim.
DEFAULT_AFFECTED_METRICS: dict[EventCategory, tuple[str, ...]] = {
    EventCategory.AUTHORITY: ("zone_wait_s", "authority_transitions", "grant_cycles"),
    EventCategory.EVALUATION: ("makespan_s", "collisions", "min_clearance_m"),
    EventCategory.TASK: ("makespan_s", "tasks_completed"),
    EventCategory.SAFETY: ("collisions", "min_clearance_m", "safety_stops"),
    EventCategory.FAULT: ("fault_effects",),
    EventCategory.COMMAND: ("operator_interventions",),
    EventCategory.TELEMETRY: ("trajectory_density",),
    EventCategory.PLANNING: (),
    EventCategory.LIFECYCLE: (),
}


@dataclass(frozen=True, slots=True)
class GapSummary:
    """Aggregate gap state for one run."""

    total: int
    durable_unrecovered: int
    categories: dict[str, int]
    excluded_metrics: tuple[str, ...]
    durable_complete: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "durable_unrecovered": self.durable_unrecovered,
            "categories": dict(self.categories),
            "excluded_metrics": list(self.excluded_metrics),
            "durable_complete": self.durable_complete,
        }


@dataclass(slots=True)
class RecordingGapTracker:
    """Collects gaps and names the metrics they invalidate.

    One tracker per run. :meth:`record` is idempotent for an identical gap so a
    restart that re-reads persisted gaps does not inflate the count.
    """

    _gaps: list[RecordingGap] = field(default_factory=list)
    _excluded: set[str] = field(default_factory=set)
    _affected: dict[EventCategory, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_AFFECTED_METRICS)
    )

    def __len__(self) -> int:
        return len(self._gaps)

    def record(self, gap: RecordingGap) -> RecordingGap:
        """Add *gap* and exclude the metrics it invalidates."""
        if gap not in self._gaps:
            self._gaps.append(gap)
            self._excluded.update(self._affected.get(gap.category, ()))
        return gap

    def record_many(self, gaps: Iterable[RecordingGap]) -> int:
        count = 0
        for gap in gaps:
            self.record(gap)
            count += 1
        return count

    def open_gap(
        self,
        *,
        run_id: str,
        category: EventCategory,
        from_seq: int,
        to_seq: int,
        cause: str,
        sim_time_from_s: float = 0.0,
        sim_time_to_s: float = 0.0,
    ) -> RecordingGap:
        """Construct and record a gap in one step."""
        return self.record(
            RecordingGap(
                run_id=run_id,
                category=category,
                from_seq=from_seq,
                to_seq=to_seq,
                sim_time_from_s=sim_time_from_s,
                sim_time_to_s=sim_time_to_s,
                cause=cause,
            )
        )

    def mark_recovered(self, index: int) -> None:
        """Mark a gap recovered after the missing evidence was re-derived.

        Recovery does *not* un-exclude the metrics by itself: the caller must call
        :meth:`clear_exclusions` if the evidence genuinely came back.
        """
        if 0 <= index < len(self._gaps):
            gap = self._gaps[index]
            self._gaps[index] = gap.model_copy(update={"recovered": True})

    def unrecovered_durable_gaps(self) -> tuple[RecordingGap, ...]:
        """Durable holes that were never recovered. Any of these fails the run."""
        return tuple(gap for gap in self._gaps if not gap.recovered and gap.category in DURABLE_CATEGORIES)

    def gaps(self, category: EventCategory | None = None) -> tuple[RecordingGap, ...]:
        if category is None:
            return tuple(self._gaps)
        return tuple(gap for gap in self._gaps if gap.category is category)

    def excluded_metrics(self) -> tuple[str, ...]:
        """Metric keys that must be reported ``excluded``, not measured."""
        return tuple(sorted(self._excluded))

    def clear_exclusions(self, metrics: Sequence[str]) -> None:
        """Remove keys from the exclusion set after evidence was genuinely restored."""
        for key in metrics:
            self._excluded.discard(key)

    def durable_complete(self) -> bool:
        return not self.unrecovered_durable_gaps()

    def summary(self) -> GapSummary:
        categories: dict[str, int] = {}
        for gap in self._gaps:
            categories[gap.category.value] = categories.get(gap.category.value, 0) + 1
        unrecovered = len(self.unrecovered_durable_gaps())
        return GapSummary(
            total=len(self._gaps),
            durable_unrecovered=unrecovered,
            categories=categories,
            excluded_metrics=self.excluded_metrics(),
            durable_complete=unrecovered == 0,
        )

    def health(self) -> dict[str, object]:
        """Doctor-facing view."""
        return {
            **self.summary().as_dict(),
            "gaps": [
                {
                    "category": gap.category.value,
                    "from_seq": gap.from_seq,
                    "to_seq": gap.to_seq,
                    "cause": gap.cause,
                    "recovered": gap.recovered,
                }
                for gap in self._gaps
            ],
        }
