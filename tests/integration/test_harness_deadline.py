"""``max_sim_time_s`` is a budget in seconds; the harness must honour it exactly.

The previous loop was::

    while self.clock.now_s() < deadline:
        for _ in range(physics_step_hz):
            ...step...

so a run always executed a whole one-second block and stopped at the first
whole-second boundary at or after the deadline. A 0.05 s budget ran a full second:
14x the requested work, 20x the requested simulated time. That is not rounding, it
is a different experiment -- and it is the reason no short scenario probe was
possible.

Semantics declared here, and asserted below:

* **Discrete fixed step.** Time only advances by whole physics steps. There is no
  partial step, so no tick ever reports a duration the world did not integrate.
* **Floor, not ceiling.** At most ``floor(deadline / dt)`` steps execute. A
  deadline of 0.05 s at 50 Hz is 2 steps = 0.04 s of simulated time. The leftover
  0.01 s is *not* rounded up and never becomes a third step.
* **The reported duration is the measured one**, taken from the clock after the
  last step that actually ran -- never from the requested budget.
* **An extra full second is never executed.** This is the property the old
  implementation broke and the one an operator's wall clock notices.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.scenario.library import build_all

_DT_S = 1.0 / 20.0  # the authored scenarios run a 20 Hz physics step


@pytest.fixture(scope="module")
def snapshot():  # type: ignore[no-untyped-def]
    return freeze_snapshot(build_all()["dynamic-arrivals"])


@pytest.fixture
def fleet(snapshot) -> Iterator[DeterministicHarness]:  # type: ignore[no-untyped-def]
    harness = DeterministicHarness(snapshot, run_id="deadline-boundary")
    try:
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


@contextmanager
def _fresh(snapshot, run_id: str) -> Iterator[DeterministicHarness]:  # type: ignore[no-untyped-def]
    """A harness that has not run yet, closed on the way out."""
    harness = DeterministicHarness(snapshot, run_id=run_id)
    try:
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


def _expected_steps(deadline_s: float) -> int:
    """``floor(deadline / dt)`` computed in **integer nanoseconds**.

    Float division is not usable for this: ``0.3 / 0.05`` is 5.999999999999999 in
    binary floating point, so ``int()`` on the quotient returns 5 where the exact
    answer is 6. The harness works in nanoseconds precisely so this class of
    off-by-one cannot occur in the code under test, and the test helper has to
    agree with it.
    """
    return round(deadline_s * 1e9) // round(_DT_S * 1e9)


def test_zero_budget_executes_no_physics_step(fleet: DeterministicHarness) -> None:
    result = fleet.run(max_sim_time_s=0.0)

    assert result.steps == 0
    assert result.sim_duration_s == pytest.approx(0.0)


def test_two_physics_ticks_execute_exactly_two_steps(fleet: DeterministicHarness) -> None:
    result = fleet.run(max_sim_time_s=2 * _DT_S)

    assert result.steps == 2
    assert result.sim_duration_s == pytest.approx(2 * _DT_S)


def test_subsecond_budget_is_floored_not_ceiled(fleet: DeterministicHarness) -> None:
    """The defect this file exists for.

    0.075 s at 20 Hz is 1.5 steps. One step is 0.05 s. The old loop compared the
    clock against the deadline only at the top of a whole one-second block, so a
    0.075 s budget ran a full second -- 13x the requested work.
    """
    result = fleet.run(max_sim_time_s=0.075)

    assert result.steps == 1
    assert result.sim_duration_s == pytest.approx(0.05)


def test_no_budget_ever_executes_an_extra_full_second(fleet: DeterministicHarness) -> None:
    for deadline in (0.01, 0.05, 0.3, 0.99, 1.0, 1.01, 2.5):
        harness = DeterministicHarness(fleet.snapshot, run_id=f"ceil-{deadline}")
        try:
            result = harness.run(max_sim_time_s=deadline)
        finally:
            for agent in harness.agents.values():
                agent.close()

        assert result.steps == _expected_steps(deadline), deadline
        assert result.sim_duration_s <= deadline + 1e-9, deadline
        assert result.sim_duration_s == pytest.approx(result.steps * _DT_S), deadline


def test_non_integral_tick_deadline_does_not_run_a_partial_step(
    fleet: DeterministicHarness,
) -> None:
    """1.07 s at 20 Hz is 21.4 steps, so 21 steps = 1.05 s.

    The reported duration must be the integrated one, not the requested 1.07 s:
    claiming a duration the world never reached would be an invented measurement.
    """
    result = fleet.run(max_sim_time_s=1.07)

    assert result.steps == 21
    assert result.sim_duration_s == pytest.approx(1.05)
    assert result.sim_duration_s != pytest.approx(1.07)


def test_a_deadline_one_nanosecond_over_a_step_boundary_floors(
    fleet: DeterministicHarness,
) -> None:
    """The exact boundary case, where a float comparison would round the wrong way.

    ``0.05 + 1e-9`` is 1 step plus one nanosecond, so still one step. A float
    ``while now < deadline`` loop happens to get this right; what it does not get
    right is the case below. Both are checked so the boundary is nailed from both
    sides rather than from the convenient one.
    """
    # A fresh harness per case: :meth:`run` advances the clock and there is no
    # rewind, so two calls on one harness would *add* their budgets.
    with _fresh(fleet.snapshot, "boundary-over") as over:
        assert over.run(max_sim_time_s=_DT_S + 1e-9).steps == 1
    with _fresh(fleet.snapshot, "boundary-under") as under:
        just_under = under.run(max_sim_time_s=1.0 - 1e-9)
    # 0.999999999 s at 20 Hz is 19.99999998 steps, so 19 steps = 0.95 s. The
    # harness measures in whole nanoseconds, and a 1 ns shortfall really does cost
    # a step -- which is the correct reading, not a rounding artefact to be papered
    # over with an epsilon.
    assert just_under.steps == 19
    assert just_under.sim_duration_s == pytest.approx(0.95)


def test_authored_full_budget_is_honoured_exactly(fleet: DeterministicHarness) -> None:
    """The scenario's own declared budget, with no explicit override.

    Uses a scenario copy whose authored budget is 3.05 s -- a non-integral number
    of ticks -- so the authored path and the exact-quantisation path are checked
    against each other rather than only against each other.
    """
    authored = 3.05
    scenario = fleet.scenario.model_copy(update={"max_sim_time_s": authored})
    harness = DeterministicHarness(freeze_snapshot(scenario), run_id="authored-budget")
    try:
        result = harness.run()
    finally:
        for agent in harness.agents.values():
            agent.close()

    assert result.steps == int(authored * 20)  # 61 steps = 3.05 s exactly
    assert result.sim_duration_s == pytest.approx(authored)


def test_negative_budget_is_refused_rather_than_silently_clamped(
    fleet: DeterministicHarness,
) -> None:
    """A budget below zero is a caller error, not a run of zero steps.

    Reporting zero steps would be indistinguishable from "the deadline expired
    before anything happened", which is exactly the kind of quiet agreement this
    project refuses.
    """
    with pytest.raises(ValueError, match="max_sim_time_s"):
        fleet.run(max_sim_time_s=-1.0)
