/**
 * Behaviour tests for the stale-pose rule.
 *
 * AGENTS.md invariant 10 ("honest states") means: when telemetry stops, the
 * cockpit freezes the last known pose and states its age. It must not keep
 * animating presumed motion, and it must not substitute a zero or a fresh-looking
 * value.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { RobotInspector } from "./RobotInspector"
import { describePoseFreshness, describeChannelFreshness } from "../../lib/map/freshness"
import type { RobotInspection } from "../../lib/api/types"

const HORIZON_S = 2.5

function robot(overrides: Partial<RobotInspection> = {}): RobotInspection {
  return {
    robot_id: "AMR2",
    index: 1,
    identity: {
      robot_id: "AMR2",
      model: "nihara-tug",
      max_linear_mps: 1.2,
      footprint: { length_m: 0.9, width_m: 0.7, turning_radius_m: 0.6 },
    },
    session: {
      robot_id: "AMR2",
      session_id: "sess-2",
      started_at_ns: 1_000_000_000,
      pid: 4242,
      host: "127.0.0.1",
      listening_port: 9102,
    },
    pose_estimate: {
      map_id: "warehouse-a",
      observed_at_ns: 12_500_000_000,
      time_domain: "logical",
      pose: { x: 7.25, y: 3.5, theta: 1.2 },
      uncertainty: { kind: "gaussian_sigma", sigma_m: 0.04, sigma_rad: 0.01, source: "ekf" },
    },
    motion: {
      stop_reason: "zone_authority_missing",
      linear_velocity_mps: 0,
      angular_velocity_radps: 0,
      actuator: "braking",
    },
    battery: { source: "simulated", fraction: 0.62, drain_model: "distance+service" },
    task: { task_id: "T-07", pickup_station_id: "PICK-A", drop_station_id: "DROP-B", priority: 1 },
    ownership: {
      task_id: "T-07",
      state: "owned",
      ownership_version: 4,
      allocation_round: 3,
      awarded_at_ns: 4_000_000_000,
    },
    custody: { task_id: "T-07", state: "at_station", custody_version: 1 },
    carrying_payload: false,
    held_zones: [{ zone_id: "Z-2", robot_id: "AMR2", state: "granted", since_seq: 88, acquired_at_sim_s: 4.2 }],
    observed_zones: [{ zone_id: "Z-3", occupant: "AMR3", state: "occupied", source: "agent_report", confidence: 0.9, age_s: 0.3 }],
    last_accepted_intent: "hold at stop line SL-2",
    planner_state: "awaiting_authority",
    plan_version: 17,
    map_epoch: "epoch-3",
    degraded: false,
    degraded_reason: null,
    why_waiting: {
      blocked: true,
      reason: "Z-2 is promised to AMR3, which has not released it.",
      blocking_request_id: "req-9911",
      blocking_peer: "AMR3",
      blocking_resource: "Z-2",
      blocking_zone_id: "Z-2",
      evidence_age_s: 4.1,
      recovery_condition: "AMR3 releases Z-2, or recovery completes for its session.",
      timer_expires_permission_only: true,
    },
    reasons: [
      { at_seq: 810, sim_time_s: 42.4, category: "authority", text: "refreshed AMR3 state", severity: "info" },
    ],
    stale: false,
    pose_age_s: 0.2,
    recent_events: [],
    ...overrides,
  }
}

describe("describePoseFreshness", () => {
  it("freezes the pose once evidence is older than the freshness horizon", () => {
    const result = describePoseFreshness(9.5, HORIZON_S)
    expect(result.frozen).toBe(true)
    expect(result.tone).toBe("stale")
    expect(result.label).toMatch(/Frozen at the last known pose/)
    expect(result.label).toMatch(/9\.5 s old/)
    expect(result.label).toMatch(/not confirmed/)
  })

  it("warns before the horizon expires", () => {
    const result = describePoseFreshness(2.0, HORIZON_S)
    expect(result.frozen).toBe(false)
    expect(result.tone).toBe("aging")
  })

  it("never reports a fresh pose when nothing has ever arrived", () => {
    const result = describePoseFreshness(null, HORIZON_S)
    expect(result.frozen).toBe(true)
    expect(result.tone).toBe("absent")
    expect(result.age_s).toBeNull()
  })
})

describe("describeChannelFreshness", () => {
  it("separates a dropped channel from a silent one", () => {
    expect(describeChannelFreshness(null, 4)).toEqual({ tone: "never", label: "dropped 4 · never heard" })
    expect(describeChannelFreshness(9, 0)).toEqual({ tone: "stale", label: "9.0 s old · 0 dropped" })
  })
})

describe("RobotInspector", () => {
  function renderInspector(props: {
    robot?: RobotInspection
    freshnessHorizonS?: number
    liveAgeS: number | null
    streamLive?: boolean
  }) {
    return render(
      <RobotInspector
        robot={props.robot ?? robot()}
        freshnessHorizonS={props.freshnessHorizonS ?? HORIZON_S}
        liveAgeS={props.liveAgeS}
        streamLive={props.streamLive ?? true}
      />,
    )
  }

  it("shows the frozen pose and its evidence age when telemetry is stale", () => {
    renderInspector({ liveAgeS: 11.2 })

    // The pose shown is the last known one, unchanged.
    expect(screen.getByTestId("robot-pose")).toHaveTextContent("7.25 m E")
    expect(screen.getByTestId("robot-pose")).toHaveTextContent("3.50 m N")

    // ...and it is explicitly frozen with its age, not silently presented.
    const frozen = screen.getByTestId("robot-frozen-pose")
    expect(frozen).toHaveTextContent("Frozen.")
    expect(frozen).toHaveTextContent("11.2 s old")
    expect(frozen).toHaveTextContent("not confirmed")
  })

  it("does not claim a freeze while telemetry is fresh", () => {
    renderInspector({ liveAgeS: 0.2 })
    expect(screen.queryByTestId("robot-frozen-pose")).toBeNull()
    expect(screen.getByTestId("robot-pose")).toHaveTextContent("7.25 m E")
  })

  it("states that no pose evidence exists rather than rendering the origin", () => {
    renderInspector({ robot: robot({ pose_estimate: null, pose_age_s: null }), liveAgeS: null })
    expect(screen.getByText("No pose evidence has been received for this robot.")).toBeInTheDocument()
    expect(screen.queryByTestId("robot-pose")).toBeNull()
  })

  it("freezes the pose when the stream is down, however fresh the agent says it is", () => {
    // The agent declares a 200 ms old observation, but *this browser* has
    // received no telemetry. Freshness must be judged on browser evidence.
    renderInspector({ liveAgeS: null, streamLive: false })
    expect(screen.getByTestId("robot-frozen-pose")).toHaveTextContent("No pose evidence")
    expect(screen.getByText("browser age")).toBeInTheDocument()
    // The agent's own claim is still shown, as a separate, labelled fact.
    expect(screen.getByText("agent age")).toBeInTheDocument()
  })

  it("labels battery provenance so a simulated charge is never read as measured", () => {
    renderInspector({ liveAgeS: 0.2 })
    expect(screen.getByText("simulated")).toBeInTheDocument()
    expect(screen.getByText(/Battery is not a measured value in this run/)).toBeInTheDocument()
  })

  it("renders unavailable battery as unavailable, not as zero percent", () => {
    renderInspector({ robot: robot({ battery: { source: "unavailable", fraction: null } }), liveAgeS: 0.2 })
    const batteryField = screen.getByText("battery").closest("div")?.parentElement
    expect(batteryField?.textContent).toContain("unavailable")
    expect(batteryField?.textContent).not.toContain("0%")
  })

  it("explains why the robot is waiting and what would clear the block", () => {
    renderInspector({ liveAgeS: 0.2 })
    const why = screen.getByTestId("why-waiting")
    expect(why).toHaveTextContent("Blocked.")
    expect(why).toHaveTextContent("Z-2 is promised to AMR3")
    expect(why).toHaveTextContent("req-9911")
    expect(why).toHaveTextContent("4.1 s")
    expect(why).toHaveTextContent("AMR3 releases Z-2")
    // Conservative occupancy is restated, not left implicit.
    expect(why).toHaveTextContent(/permission to assume/)
  })

  it("shows the boot session identity an operator needs to attribute a message", () => {
    renderInspector({ liveAgeS: 0.2 })
    expect(screen.getByText("sess-2")).toBeInTheDocument()
    expect(screen.getByText(/pid 4242/)).toBeInTheDocument()
    expect(screen.getByText(/9102/)).toBeInTheDocument()
  })
})