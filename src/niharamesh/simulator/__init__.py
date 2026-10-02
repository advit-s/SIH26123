"""Physical world simulation: physics, sensing, occupancy and event ordering.

What lives here
---------------
* :mod:`~niharamesh.simulator.kinematics` -- differential-drive integration with
  declared acceleration, deceleration and a watchdog that brakes instead of
  teleporting.
* :mod:`~niharamesh.simulator.world` -- :class:`~niharamesh.simulator.world.World`,
  the :class:`~niharamesh.ports.WorldPort` implementation. It applies commands and
  never refuses a colliding one.
* :mod:`~niharamesh.simulator.sensors` -- declared range sensing with explicit
  latency, dropout and uncertainty.
* :mod:`~niharamesh.simulator.occupancy` -- conservative uniform-grid free space
  for planning.
* :mod:`~niharamesh.simulator.scheduler` -- deterministic fixed-step logical clock
  with a canonical event order.

Authority, restated because it is the thing reviewers check first: nothing in
this package plans a route, awards a task, grants a zone, or judges whether a
run was safe. Collision *evidence* is produced by
:mod:`niharamesh.safety.collision`, which is a separate module with its own
algorithms so that it cannot be quietly satisfied by the same code that moved the
robots.
"""

from __future__ import annotations

from niharamesh.simulator.kinematics import (
    KinematicResult,
    braking_distance_m,
    clamp_command,
    ramp_towards,
)
from niharamesh.simulator.occupancy import OccupancyGrid
from niharamesh.simulator.scheduler import DeterministicScheduler, Priority, ScheduledEvent
from niharamesh.simulator.sensors import (
    SensorScene,
    cast_rays,
    generate_observation,
    generate_pose_estimate,
)
from niharamesh.simulator.world import World

__all__ = [
    "DeterministicScheduler",
    "KinematicResult",
    "OccupancyGrid",
    "Priority",
    "ScheduledEvent",
    "SensorScene",
    "World",
    "braking_distance_m",
    "cast_rays",
    "clamp_command",
    "generate_observation",
    "generate_pose_estimate",
    "ramp_towards",
]
