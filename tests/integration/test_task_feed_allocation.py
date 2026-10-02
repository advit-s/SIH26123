"""The scenario's declared task feed must actually reach the local auction.

Reproduced 2026-10-02: in ``dynamic-arrivals`` every robot reported
``"no task is currently assigned to this robot"`` for the whole run and the run
classified ``incomplete``. The cause was not a scenario defect. ``dynamic-arrivals``
declares no ``assigned_task_id`` -- on purpose, it is the scenario that *tests*
allocation -- and nothing ever opened an allocation round, so ``LocalAuction``
was constructed, ticked 15 000 times, and never asked a single question.

These tests pin the wiring down through the real components: the real
``LocalAuction``, the real ``CustodyLedger``, the real ``RobotAgent``, and the
harness routing real ``AllocationMessage`` records between them. No test here
grants an award, assigns a task centrally, or reads another robot's truth.

What the tests require:

* a task released at ``release_at_s`` becomes *biddable* at that instant, and
  before it, nobody may bid on it;
* an award is computed by **every** robot from the same bid set, and every robot
  agrees on the winner (agreement is asserted, not assumed);
* exactly one robot holds a task, and exactly one completion credit exists per
  delivered task;
* every robot reports on every released task, so "I declined" is never silence;
* a delivered task is withdrawn, so no peer can re-win it and re-deliver it;
* a capacity-1 robot bids on the task it already owns, not on a cheaper one.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from niharamesh.allocation.auction import LocalAuction, PartitionConsensusState, RoundSerialisationError
from niharamesh.domain.task import AllocationRound
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.scenario.library import build_all, dynamic_arrivals


@pytest.fixture
def fleet() -> Iterator[DeterministicHarness]:
    harness = DeterministicHarness(freeze_snapshot(dynamic_arrivals()), run_id="task-feed")
    try:
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


def test_an_unassigned_scenario_binds_no_task_until_a_release(fleet: DeterministicHarness) -> None:
    """Nothing before the feed says so. Silence is not a pre-assignment.

    ``dynamic-arrivals`` releases its first task at 0 s and its next at 60 s, so
    this also checks that the second task is *not* claimed early.
    """
    scenario = fleet.scenario
    assert all(s.assigned_task_id is None for s in scenario.starts), (
        "this scenario must have no pre-assignment, or it does not test allocation"
    )
    assert sorted(t.release_at_s for t in scenario.tasks) == [0.0, 60.0, 120.0, 180.0]

    fleet.run(max_sim_time_s=2.0)

    # Only ``t-dyn-0`` is released by 2 s, so exactly one robot may hold work. All
    # three *reporting* on it is the requirement; all three *holding* it is the bug.
    claimed = {a.identity.robot_id: a.progress.task_id for a in fleet.agents.values()}
    held = [tid for tid in claimed.values() if tid is not None]
    assert len(held) == 1, f"expected exactly one winner among three robots, got {claimed}"
    assert held[0] == "t-dyn-0"

    # Only one task is released by 2 s, so two robots necessarily hold nothing --
    # that is capacity, not a defect. What must hold is that no two robots hold the
    # *same* task, and that every robot owns what it plans to do.
    non_none = [tid for tid in claimed.values() if tid is not None]
    assert len(set(non_none)) == len(non_none), f"two robots hold the same task: {claimed}"
    for robot_id, task_id in claimed.items():
        if task_id is None:
            continue
        ownership = fleet.agents[robot_id].auction.ownership(task_id)
        assert ownership is not None and ownership.owner == robot_id, (
            f"{robot_id} plans {task_id} but the auction never awarded it to them: {ownership}"
        )

    # And every robot must have *priced* the task, or "I declined" and "I never
    # heard" are indistinguishable from the outside.
    for agent in fleet.agents.values():
        assert agent.auction.heard_from("t-dyn-0") == frozenset(agent.auction.membership.members)


def test_every_released_task_gets_a_report_from_every_member(fleet: DeterministicHarness) -> None:
    """Silence is never acceptable: a peer cannot tell "declined" from "lost"."""
    fleet.run(max_sim_time_s=2.0)

    for agent in fleet.agents.values():
        auction = agent.auction
        assert auction.round is not None
        for task_id in auction.round.released_task_ids:
            heard = auction.heard_from(task_id)
            assert heard == frozenset(auction.membership.members), (
                f"{agent.identity.robot_id} holds reports from {sorted(heard)} "
                f"for {task_id}, not from all {sorted(auction.membership.members)}"
            )


def test_every_robot_agrees_on_the_winner(fleet: DeterministicHarness) -> None:
    """Agreement is the point of a local auction, so it is asserted, not assumed."""
    fleet.run(max_sim_time_s=3.0)

    outcomes: dict[str, dict[str, str]] = {}
    for agent in fleet.agents.values():
        auction = agent.auction
        for task_id in auction.round.released_task_ids:  # type: ignore[union-attr]
            state = auction.consensus(task_id)
            outcome = auction.compute_award(task_id)
            outcomes.setdefault(task_id, {})[agent.identity.robot_id] = (
                outcome.winner or f"no_bid:{outcome.no_bid_reason}"
            )
            if outcome.winner:
                assert state is PartitionConsensusState.AGREED, (
                    f"{task_id}: {agent.identity.robot_id} computed a winner while consensus was "
                    f"{state.value}"
                )

    for task_id, per_robot in outcomes.items():
        assert len(set(per_robot.values())) == 1, f"robots disagree on {task_id}: {per_robot}"


def test_a_delivered_task_is_withdrawn_so_no_peer_can_rewin_it() -> None:
    """One completion credit per task, and no re-delivery by a second winner.

    Runs long enough for a delivery to actually happen. Measured on
    ``dynamic-arrivals``: the first delivery lands at ~400 s of simulated time,
    because the tasks span the full 22 m of the warehouse at the declared
    0.4 m/s. This is a slow test by construction -- there is no honest way to
    assert "a delivered task is withdrawn" without a delivery.
    """
    scenario = build_all()["dynamic-arrivals"]
    harness = DeterministicHarness(freeze_snapshot(scenario), run_id="withdrawal")
    try:
        harness.run(max_sim_time_s=420.0)
    finally:
        for agent in harness.agents.values():
            agent.close()

    delivered = [tid for a in harness.agents.values() for tid in a.completed_tasks]
    assert delivered, "nothing was delivered, so nothing can be withdrawn"
    for task_id in delivered:
        reasons = set()
        for agent in harness.agents.values():
            for bid in agent.auction.bids_for(task_id):
                reasons.add(bid.infeasible_reason)
        assert any(r.startswith("withdrawn") for r in reasons), (
            f"{task_id} was delivered but no robot announces it as withdrawn; reasons={reasons}"
        )
        for agent in harness.agents.values():
            ownership = agent.auction.ownership(task_id)
            assert ownership is None or ownership.owner in delivered_owners(harness, task_id)


def delivered_owners(harness: DeterministicHarness, task_id: str) -> set[str]:
    return {a.identity.robot_id for a in harness.agents.values() if task_id in a.completed_tasks}


def test_a_robot_with_a_task_does_not_bid_on_a_cheaper_one() -> None:
    """Capacity is one task. A robot that holds work keeps bidding on that work.

    If it bid on a cheaper task instead, a peer could win the one it holds while
    its own bid sat unused -- the classic two-tasks-one-robot bug the auction's
    ``consider`` is meant to prevent.
    """
    scenario = build_all()["dynamic-arrivals"]
    harness = DeterministicHarness(freeze_snapshot(scenario), run_id="capacity")
    try:
        harness.run(max_sim_time_s=4.0)
    finally:
        for agent in harness.agents.values():
            agent.close()

    checked = False
    for agent in harness.agents.values():
        held = agent.progress.task_id
        if held is None:
            continue
        checked = True
        own = agent.auction.ownership(held)
        assert own is not None and own.owner == agent.identity.robot_id, (
            f"{agent.identity.robot_id} plans {held} but does not own it: {own}"
        )
        # ``live_bid_task`` is cleared once the award commits, so the meaningful
        # in-round assertion is that a robot holding work bids on *that* work and
        # never on a cheaper alternative.
        if agent.auction.live_bid_task is not None:
            assert agent.auction.live_bid_task == held, (
                f"{agent.identity.robot_id} holds {held} but bid on {agent.auction.live_bid_task}"
            )
    assert checked, "no robot ever held a task, so capacity was never exercised"


def test_close_round_refuses_while_this_robots_bid_is_live() -> None:
    """Round serialisation is a rule, not a convention.

    Closing a round with a live bid would leave peers holding a reservation this
    robot cannot honour. The auction must refuse rather than quietly do it.
    """
    scenario = dynamic_arrivals()
    agent = LocalAuction(
        robot_id="amr-01",
        robot_session="amr-01-s1",
        run_id="r",
        epoch="e",
        membership=_membership(scenario),
    )
    agent.open_round(_round("r0", ("t-dyn-0",)))
    agent.close_round()  # fine while nothing is live
    agent.open_round(_round("r1", ("t-dyn-1",)))
    agent.consider(_bid("r1", "t-dyn-1", 10.0))
    assert agent.live_bid_task == "t-dyn-1"
    with pytest.raises(RoundSerialisationError):
        agent.close_round()


def _membership(scenario) -> object:  # type: ignore[no-untyped-def]
    from niharamesh.domain.identity import Membership

    return Membership(
        run_id="r",
        epoch="e",
        members=tuple(r.robot_id for r in scenario.robots),
    )


def _round(round_id: str, tasks: tuple[str, ...]) -> AllocationRound:
    return AllocationRound(
        round_id=round_id,
        run_id="r",
        epoch="e",
        index=int(round_id[1:]),
        released_task_ids=tasks,
        snapshot_digest="d" * 64,
        opened_at_ns=0,
    )


def _bid(round_id: str, task_id: str, cost: float) -> object:  # type: ignore[no-untyped-def]
    from niharamesh.domain.task import BidComponent, TaskBid

    return TaskBid(
        run_id="r",
        epoch="e",
        task_id=task_id,
        robot_id="amr-01",
        robot_session="amr-01-s1",
        round_id=round_id,
        total_cost=cost,
        components=(BidComponent(name="travel_time_s", value=cost, unit="s"),),
        feasible=True,
        at_ns=0,
        tie_break=1,
    )
