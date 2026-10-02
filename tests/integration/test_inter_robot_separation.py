"""Two robots must not occupy the same space. This file records a real failure.

Measured 2026-10-03 on ``dynamic-arrivals`` at a 62.5 s budget, on the authored
snapshot with no fault injected and no map edited:

* ``amr-01`` (task ``t-dyn-0``, pickup at ``stn-pick-a`` then drop at
  ``stn-drop-a``) drives **east** along the bottom row aisle.
* ``amr-02`` (task ``t-dyn-1``, pickup at ``stn-pick-b``) drives **west** along
  the same aisle and then north.
* They meet head-on near ``(13.4, 2.0)``. The safety gate correctly stops both --
  ``obstacle_in_path`` for both, forward clearance falling to 0.226 m against a
  0.32 m stopping budget -- but the bodies are **already overlapping**: 356
  consecutive physics samples with ``sat_overlap`` true, centre distance 0.563 m.

That is a collision, and the project reports collisions (``KNOWN_LIMITATIONS.md``
item 2 says a zero count is not proof, and this is the inverse: a non-zero count
is proof). The root cause is a genuine gap, and it is stated precisely:

**The safety gate has no inter-robot overlap check.** ``_overlaps_static``
consults only the static map. A peer is visible to the gate only as a single
scalar, ``GateContext.obstacle_distance_m``, which is the nearest ray inside a
+/-90 degree cone and is compared against a **longitudinal braking budget**. That
quantity answers "is there something in front of me that I cannot stop before",
which is the right question for a shelf and the wrong one for a peer that is
*beside* the robot. A robot 0.5 m off the nose at 90 degrees is inside the cone
and outside the budget, so the gate permits motion straight into it.

``dynamic-arrivals`` exposes this because its map declares **no zones at all**:
there is nothing for the exclusive-zone protocol to arbitrate, so two robots
assigned opposing tasks in one aisle are left to the local safety layer alone.
That is a scenario-authoring consequence, not a scenario bug -- but the missing
local safety behaviour is a product defect, and it is this file's subject.

These tests therefore assert the *required* property and are expected to fail
until the gate refuses motion that would bring the body within a declared
separation of a **sensed peer**. They are not skipped, not marked xfail, and not
weakened to the behaviour that happens to ship.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest

from niharamesh.domain.geometry import Pose
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.safety.collision import sat_overlap
from niharamesh.scenario.library import dynamic_arrivals

#: Two 0.6 x 0.4 m bodies must not come within this centre distance of each other.
#: The sum of half-diagonals is 0.36 m each, so any *overlap* is below 0.72 m; the
#: declared separation adds a body half-width plus a localisation margin on top,
#: which is what a real pair of AMRs would be specified to keep.
_DECLARED_SEPARATION_M = 0.9

#: Enough of the run for the head-on to happen. Measured: first body overlap at
#: 62.2 s.
_BUDGET_S = 90.0


@pytest.fixture(scope="module")
def overlap_run() -> tuple[list[tuple[str, str, int, float]], DeterministicHarness]:
    """One run, sampled for peer separation. Read by every test here."""
    harness = DeterministicHarness(freeze_snapshot(dynamic_arrivals()), run_id="separation")
    samples: list[tuple[str, str, int, float]] = []

    world_type = type(harness.world)
    original = world_type.observe

    def spy(self: object, robot_id: str) -> object:  # type: ignore[no-untyped-def]
        observation = original(self, robot_id)  # type: ignore[arg-type]
        if robot_id == "amr-01":
            truth = self.truth().robots  # type: ignore[attr-defined]
            ids = sorted(truth)
            for i, first in enumerate(ids):
                for second in ids[i + 1 :]:
                    a, b = truth[first], truth[second]
                    ba = harness.agents[first].identity.footprint.body_at(Pose(a.x, a.y, a.theta))
                    bb = harness.agents[second].identity.footprint.body_at(Pose(b.x, b.y, b.theta))
                    if sat_overlap(ba, bb):
                        samples.append(
                            (
                                first,
                                second,
                                int(self.sim_time_ns),  # type: ignore[attr-defined]
                                math.hypot(a.x - b.x, a.y - b.y),
                            )
                        )
        return observation

    world_type.observe = spy  # type: ignore[method-assign]
    try:
        harness.run(max_sim_time_s=_BUDGET_S)
    finally:
        world_type.observe = original  # type: ignore[method-assign]
    return samples, harness


@pytest.fixture
def fleet(
    overlap_run: tuple[list[tuple[str, str, int, float]], DeterministicHarness],
) -> Iterator[DeterministicHarness]:
    _, harness = overlap_run
    yield harness
    for agent in harness.agents.values():
        agent.close()


def test_two_robots_never_occupy_the_same_space(
    overlap_run: tuple[list[tuple[str, str, int, float]], DeterministicHarness],
) -> None:
    """REQUIRED: no two robot bodies overlap at any instant of the run.

    The evaluator may read world truth to assert this -- that is its job. Nothing
    here is visible to a robot's decision.
    """
    samples, _ = overlap_run
    if not samples:
        pytest.skip("no overlap observed; the head-on did not reproduce in this build")

    first, last = samples[0], samples[-1]
    offenders = sorted({f"{a}/{b}" for a, b, _, _ in samples})
    pytest.fail(
        f"{len(samples)} overlapping physics samples, first at "
        f"{first[2] / 1e9:.2f} s and last at {last[2] / 1e9:.2f} s, between {offenders}; "
        f"tightest centre distance {min(s[3] for s in samples):.3f} m. "
        f"The safety gate has no inter-robot overlap check: a peer is visible to it "
        f"only as one forward-cone distance compared against a longitudinal braking "
        f"budget, which is the wrong quantity for a robot beside the nose. "
        f"Required separation for two declared bodies is {_DECLARED_SEPARATION_M} m."
    )


def test_the_stalled_head_on_is_reported_not_hidden(
    overlap_run: tuple[list[tuple[str, str, int, float]], DeterministicHarness],
) -> None:
    """The stall itself is correct behaviour; the overlap is not.

    Both robots stop with ``obstacle_in_path`` and neither resolves the deadlock,
    because a mutual stop in a 1.4 m aisle with no passing place is a genuine
    standoff. This test pins that the stop is *attributed* -- an operator must be
    able to read "I am blocked by a peer" rather than a bare veto -- and it fails
    on the missing attribution, which is the honest current state.
    """
    _, harness = overlap_run
    for robot_id in ("amr-01", "amr-02"):
        agent = harness.agents[robot_id]
        assert agent.stop_reason.value == "obstacle_in_path", (
            f"{robot_id} stopped for {agent.stop_reason.value}, not the peer ahead"
        )
        constraint = "" if agent._last_refusal is None else agent._last_refusal.limiting_constraint
        assert constraint != "", (
            f"{robot_id} was refused with no stated constraint: a veto an operator "
            f"cannot read is indistinguishable from a sensor fault"
        )
