"""``nihara doctor`` - runtime self-check.

Reports what is actually available on this machine. Values are only shown when
they were collected; a missing measurement is reported as unavailable, never as
zero. The exit code is non-zero when a *required* capability is missing, so it
can gate CI honestly.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["DoctorReport", "add_parser", "collect", "run"]

EXIT_OK = 0
EXIT_DEGRADED = 4
EXIT_FAILED = 5


@dataclass(slots=True)
class Check:
    name: str
    status: str  # ok | unavailable | degraded | failed
    detail: str = ""
    required: bool = False
    remedy: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
            "remedy": self.remedy,
        }


@dataclass(slots=True)
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    build_identity: dict[str, Any] = field(default_factory=dict)
    collected_utc: str = ""

    @property
    def failed_required(self) -> list[Check]:
        return [c for c in self.checks if c.required and c.status in ("failed", "unavailable")]

    @property
    def degraded(self) -> list[Check]:
        return [c for c in self.checks if c.status == "degraded"]

    @property
    def exit_code(self) -> int:
        if self.failed_required:
            return EXIT_FAILED
        if self.degraded:
            return EXIT_DEGRADED
        return EXIT_OK


def _tool_version(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603
            [*cmd], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0] if text else None


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _git(*args: str) -> str | None:
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603, S607 - git already resolved via shutil.which
            ["git", *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def collect(*, api_host: str = "127.0.0.1", api_port: int = 8100, web_port: int = 5173) -> DoctorReport:
    report = DoctorReport(collected_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    c = report.checks

    # -- toolchain ----------------------------------------------------------
    for name, cmd, required, remedy in (
        (
            "python",
            [sys.executable, "--version"],
            True,
            "install Python 3.12 (uv python install 3.12)",
        ),
        ("uv", ["uv", "--version"], True, "install uv: https://docs.astral.sh/uv/"),
        ("node", ["node", "--version"], True, "install Node.js 22.12+ or newer"),
        ("pnpm", ["pnpm", "--version"], True, "install pnpm 11 or newer"),
        ("git", ["git", "--version"], True, "install Git"),
        (
            "opencode",
            ["opencode", "--version"],
            False,
            "optional: only needed to run coding agents",
        ),
        (
            "docker",
            ["docker", "--version"],
            False,
            "optional: the native launcher works without Docker",
        ),
    ):
        v = _tool_version(cmd)
        if v is None:
            c.append(
                Check(
                    name=name,
                    status="unavailable" if required else "degraded",
                    detail=f"{name} not found on PATH",
                    required=required,
                    remedy=remedy,
                )
            )
        else:
            c.append(Check(name=name, status="ok", detail=v, required=required))

    # -- package versions ---------------------------------------------------
    try:
        import pydantic

        c.append(Check(name="pydantic", status="ok", detail=pydantic.__version__, required=True))
    except ImportError as exc:  # pragma: no cover - environment problem
        c.append(
            Check(
                name="pydantic",
                status="failed",
                detail=str(exc),
                required=True,
                remedy="run 'uv sync --extra dev'",
            )
        )

    # -- contracts ----------------------------------------------------------
    try:
        from niharamesh import contracts

        index = contracts.schema_index()
        c.append(
            Check(
                name="contracts",
                status="ok",
                detail=(
                    f"{index.get('count')} schemas, schema {index.get('version')}, "
                    f"protocol {index.get('protocol_version')}"
                ),
                required=True,
            )
        )
    except Exception as exc:
        c.append(
            Check(
                name="contracts",
                status="failed",
                detail=str(exc),
                required=True,
                remedy="run 'uv run python scripts/generate_contracts.py'",
            )
        )

    # -- scenario library ---------------------------------------------------
    try:
        from niharamesh.scenario.library import build_all
        from niharamesh.scenario.validation import validate_scenario

        library = build_all()
        invalid = [s.scenario_id for s in library.values() if not validate_scenario(s).diagnostic_allowed]
        status = "ok" if not invalid else "degraded"
        c.append(
            Check(
                name="scenarios",
                status=status,
                detail=f"{len(library)} built-in scenarios"
                + (f", structurally invalid: {', '.join(invalid)}" if invalid else ""),
                required=True,
                remedy="run 'uv run nihara scenarios validate'" if invalid else "",
            )
        )
    except Exception as exc:
        c.append(Check(name="scenarios", status="failed", detail=str(exc), required=True))

    # -- optional Python modules -------------------------------------------
    for mod in (
        "niharamesh.simulator.world",
        "niharamesh.transport.peer",
        "niharamesh.api.app",
        "niharamesh.agent.runtime",
    ):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            c.append(
                Check(
                    name=mod,
                    status="unavailable",
                    detail=f"{type(exc).__name__}: {exc}"[:200],
                    required=False,
                    remedy="this component is not installed yet on this checkout",
                )
            )
        else:
            c.append(Check(name=mod, status="ok", detail="importable"))

    # -- ports --------------------------------------------------------------
    for label, host, port in (("api", api_host, api_port), ("web", "127.0.0.1", web_port)):
        if _port_free(host, port):
            c.append(Check(name=f"port:{label}", status="ok", detail=f"{host}:{port} is free"))
        else:
            c.append(
                Check(
                    name=f"port:{label}",
                    status="degraded",
                    detail=f"{host}:{port} is already in use",
                    required=False,
                    remedy=(
                        f"set NIHARA_{label.upper()}_PORT to another port. "
                        "NĪHĀRAMESH never kills an unrelated process to free a port."
                    ),
                )
            )

    # -- storage ------------------------------------------------------------
    data_dir = pathlib.Path(os.environ.get("NIHARA_RUNS_DIR", "var/runs"))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        c.append(Check(name="storage", status="ok", detail=f"{data_dir} is writable"))
    except OSError as exc:
        c.append(
            Check(
                name="storage",
                status="failed",
                detail=str(exc),
                required=True,
                remedy="set NIHARA_RUNS_DIR to a writable directory",
            )
        )

    # -- actuation ----------------------------------------------------------
    actuation = os.environ.get("NIHARA_PHYSICAL_ACTUATION_ENABLED", "false").strip().lower() == "true"
    c.append(
        Check(
            name="physical_actuation",
            status="degraded" if actuation else "ok",
            detail="ENABLED - requires configured devices, a controlled test area and operator authorisation"
            if actuation
            else "disabled (default)",
            required=False,
            remedy="leave it disabled; see docs/EDGE.md before enabling anything",
        )
    )

    # -- build identity -----------------------------------------------------
    revision = _git("rev-parse", "--short", "HEAD")
    dirty = _git("status", "--porcelain")
    report.build_identity = {
        "git_revision": revision or "unavailable",
        "git_dirty": bool(dirty),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": sys.platform,
    }
    return report


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    p = sub.add_parser("doctor", help="runtime self-check: toolchain, contracts, scenarios, ports, storage")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.add_argument("--api-host", default=os.environ.get("NIHARA_API_HOST", "127.0.0.1"))
    p.add_argument("--api-port", type=int, default=int(os.environ.get("NIHARA_API_PORT", "8100")))
    p.add_argument("--web-port", type=int, default=int(os.environ.get("NIHARA_WEB_PORT", "5173")))
    return p


def run(args: argparse.Namespace) -> int:
    report = collect(api_host=args.api_host, api_port=args.api_port, web_port=args.web_port)
    if args.json:
        print(
            json.dumps(
                {
                    "collected_utc": report.collected_utc,
                    "build_identity": report.build_identity,
                    "exit_code": report.exit_code,
                    "checks": [c.as_dict() for c in report.checks],
                },
                indent=2,
            )
        )
        return report.exit_code
    print(f"NĪHĀRAMESH doctor — {report.collected_utc}")
    print(
        f"build: {report.build_identity.get('git_revision')} (dirty={report.build_identity.get('git_dirty')})"
    )
    print()
    width = max(len(c.name) for c in report.checks)
    symbols = {"ok": "ok  ", "degraded": "WARN", "unavailable": "MISS", "failed": "FAIL"}
    for c in report.checks:
        print(f"  [{symbols[c.status]}] {c.name.ljust(width)}  {c.detail}")
        if c.remedy and c.status != "ok":
            print(f"         -> {c.remedy}")
    print()
    if report.failed_required:
        print(f"{len(report.failed_required)} required capability/capabilities unavailable.")
    elif report.degraded:
        print(f"no required capability is missing; {len(report.degraded)} optional item(s) degraded.")
    else:
        print("all required capabilities available.")
    return report.exit_code
