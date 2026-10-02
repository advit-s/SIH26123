"""``nihara`` command-line entry point.

Exit codes are meaningful so scripts and CI can act on them:

==== ==========================================================
0    success
1    a runtime error with an actionable message
2    the requested input was invalid (validation failed)
3    an input/output or path-safety problem
4    degraded: nothing required is missing, but something is optional
5    a required capability is unavailable
==== ==========================================================

Signals are handled so an interrupted run still preserves its artifacts, and
cleanup is explicit. The launcher never kills an unrelated process to free a port.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import signal
import sys
from collections.abc import Callable
from types import FrameType

from niharamesh import __version__

__all__ = [
    "EXIT_DEGRADED",
    "EXIT_ERROR",
    "EXIT_FAILED",
    "EXIT_INVALID",
    "EXIT_IO",
    "EXIT_OK",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INVALID = 2
EXIT_IO = 3
EXIT_DEGRADED = 4
EXIT_FAILED = 5

BANNER = "NĪHĀRAMESH"


def _install_signal_handlers(on_interrupt: Callable[[], None]) -> None:
    def handler(signum: int, _frame: FrameType | None) -> None:
        name = signal.Signals(signum).name
        print(f"\n{BANNER}: received {name}. Preserving artifacts and shutting down.", file=sys.stderr)
        on_interrupt()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # Not every platform exposes every signal (Windows has no SIGTERM), so a
        # refusal here must not stop `nihara` from running.
        with contextlib.suppress(ValueError, OSError, AttributeError):
            signal.signal(sig, handler)


#: Subcommand name -> (module, help text). A command is registered only when its
#: runtime module is importable on this checkout, so the CLI never offers a
#: command that cannot run. ``nihara doctor`` reports what is missing.
COMMANDS: dict[str, tuple[str, str]] = {
    "doctor": (
        "niharamesh.cli.doctor",
        "runtime self-check: toolchain, contracts, scenarios, ports, storage",
    ),
    "scenarios": ("niharamesh.cli.scenarios", "author, export, validate and inspect scenarios"),
    "run": ("niharamesh.cli.run", "launch one scenario in deterministic or process mode"),
    "benchmark": ("niharamesh.cli.bench", "run a paired benchmark suite and export raw results"),
    "replay": ("niharamesh.cli.replay", "inspect and validate a recorded run"),
    "report": ("niharamesh.cli.replay", "render a run report from exported evidence"),
    "serve": ("niharamesh.cli.serve", "serve the application API"),
    "agent": ("niharamesh.cli.agent", "run one robot agent process (used by the supervisor)"),
}


def _available() -> dict[str, tuple[str, str]]:
    import importlib

    out: dict[str, tuple[str, str]] = {}
    for name, (module_path, help_text) in COMMANDS.items():
        try:
            importlib.import_module(module_path)
        except ImportError:
            continue
        out[name] = (module_path, help_text)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nihara",
        description=(
            "NĪHĀRAMESH — freshness-aware distributed fleet coordination for warehouse AMRs. "
            "Project dossier (external reference, not a runtime dependency): "
            "https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes: 0 ok, 1 error, 2 invalid input, 3 io/path problem, "
            "4 degraded, 5 required capability unavailable."
        ),
    )
    parser.add_argument("--version", action="version", version=f"{BANNER} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    available = _available()
    for name, (module_path, _help) in available.items():
        module = importlib.import_module(module_path)
        if name == "report":
            module.add_report_parser(sub)
        else:
            module.add_parser(sub)

    missing = sorted(set(COMMANDS) - set(available))
    if missing:
        parser.epilog = (parser.epilog or "") + (
            f"\nNot available in this checkout (runtime module absent): {', '.join(missing)}."
            " Run 'nihara doctor' for details."
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    import importlib

    available = _available()
    entry = available.get(args.command)
    if entry is None:  # pragma: no cover - argparse only offers available commands
        parser.error(f"command {args.command!r} is not available in this checkout")
    module = importlib.import_module(entry[0])
    handler: Callable[[argparse.Namespace], int] | None = getattr(module, "run", None) or getattr(
        module, "run_report", None
    )
    if handler is None:  # pragma: no cover - every command module defines one
        parser.error(f"command {args.command!r} has no entry point")

    _install_signal_handlers(lambda: None)
    try:
        return int(handler(args))
    except KeyboardInterrupt:
        print(f"\n{BANNER}: interrupted.", file=sys.stderr)
        return EXIT_ERROR
    except SystemExit as exc:  # let argparse-style exits pass through
        return int(exc.code or 0)
    except Exception as exc:
        from niharamesh.cli.errors import describe

        print(f"{BANNER}: {describe(exc)}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
