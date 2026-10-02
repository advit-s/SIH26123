"""Generate the authoritative JSON Schemas from the Pydantic domain models.

The Pydantic models are the single source of truth. This script writes them to
``src/niharamesh/contracts/schemas/*.json`` - inside the Python package, so the
schemas ship with the wheel - and the TypeScript build generates its types from
that same directory. Regenerate with::

    uv run python scripts/generate_contracts.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "src" / "niharamesh" / "contracts" / "schemas"

SCHEMAS: dict[str, str] = {}


def _register(title: str, model: type) -> None:
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = title
    schema["$id"] = f"https://niharamesh.local/schemas/{title}.json"
    schema["x-niharamesh-version"] = __import__(
        "niharamesh.domain.units", fromlist=["SCHEMA_VERSION"]
    ).SCHEMA_VERSION
    SCHEMAS[title] = schema


def build() -> dict[str, str]:
    from niharamesh.domain import (
        config,
        coordination,
        faults,
        identity,
        pose,
        scenario,
        task,
        telemetry,
    )
    from niharamesh.domain import map as map_mod

    _register("RobotIdentity", identity.RobotIdentity)
    _register("RobotSession", identity.RobotSession)
    _register("Membership", identity.Membership)
    _register("PeerEndpoint", identity.PeerEndpoint)
    _register("PoseEstimate", pose.PoseEstimate)
    _register("Pose2", pose.Pose2)
    _register("Footprint", pose.Footprint)
    _register("MotionState", pose.MotionState)
    _register("MotionCommand", pose.MotionCommand)
    _register("BatteryState", pose.BatteryState)
    _register("WarehouseMap", map_mod.WarehouseMap)
    _register("Zone", map_mod.Zone)
    _register("Station", map_mod.Station)
    _register("Berth", map_mod.Berth)
    _register("StopLine", map_mod.StopLine)
    _register("Obstacle", map_mod.Obstacle)
    _register("ZoneRequestBody", coordination.ZoneRequestBody)
    _register("ZoneGrantBody", coordination.ZoneGrantBody)
    _register("ZoneCancelBody", coordination.ZoneCancelBody)
    _register("ZoneCancelAckBody", coordination.ZoneCancelAckBody)
    _register("ZoneOccupyBody", coordination.ZoneOccupyBody)
    _register("ZoneReleaseBody", coordination.ZoneReleaseBody)
    _register("ZoneFenceBody", coordination.ZoneFenceBody)
    _register("PeerState", coordination.PeerState)
    _register("PeerIntent", coordination.PeerIntent)
    _register("ObstructionReport", coordination.ObstructionReport)
    _register("Heartbeat", coordination.Heartbeat)
    _register("PeerEnvelope", coordination.PeerEnvelope)
    _register("PeerMessage", coordination.PeerMessage)
    _register("Task", task.Task)
    _register("TaskOwnership", task.TaskOwnership)
    _register("PayloadCustody", task.PayloadCustody)
    _register("TaskBid", task.TaskBid)
    _register("TaskAward", task.TaskAward)
    _register("AllocationRound", task.AllocationRound)
    _register("TaskTransition", task.TaskTransition)
    _register("FaultSpec", faults.FaultSpec)
    _register("FaultRecord", faults.FaultRecord)
    _register("SimulationConfig", config.SimulationConfig)
    _register("FeatureFlags", config.FeatureFlags)
    _register("StoppingBudget", config.StoppingBudget)
    _register("DomainEvent", telemetry.DomainEvent)
    _register("TelemetrySample", telemetry.TelemetrySample)
    _register("RecordingGap", telemetry.RecordingGap)
    _register("RunManifest", telemetry.RunManifest)
    _register("RunResult", telemetry.RunResult)
    _register("RunDescriptor", telemetry.RunDescriptor)
    _register("MetricDefinition", telemetry.MetricDefinition)
    _register("MetricValue", telemetry.MetricValue)
    _register("ReplayIndex", telemetry.ReplayIndex)
    _register("EnvironmentRecord", telemetry.EnvironmentRecord)
    _register("Scenario", scenario.Scenario)
    _register("ScenarioSnapshot", scenario.ScenarioSnapshot)
    _register("RobotStart", scenario.RobotStart)
    _register("RunPolicy", scenario.RunPolicy)
    return SCHEMAS


def main() -> int:
    schemas = build()
    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    for title, schema in sorted(schemas.items()):
        path = OUT / f"{title}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        index[title] = path.name
    (OUT / "index.json").write_text(
        json.dumps(
            {
                "version": __import__(
                    "niharamesh.domain.units", fromlist=["SCHEMA_VERSION"]
                ).SCHEMA_VERSION,
                "protocol_version": __import__(
                    "niharamesh.domain.units", fromlist=["PROTOCOL_VERSION"]
                ).PROTOCOL_VERSION,
                "count": len(index),
                "schemas": index,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(index)} schemas to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
