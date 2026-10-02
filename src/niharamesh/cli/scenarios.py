"""``nihara scenarios`` - export, list, validate and inspect the scenario library.

Import/export is a round trip through the same Pydantic models that the runtime
uses, so an exported file is exactly what a launched run would have consumed.
Nothing is silently repaired: an invalid draft is preserved on disk and reported
with an actionable list.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import TYPE_CHECKING

from niharamesh.scenario import (
    ScenarioIOError,
    list_scenario_files,
    load_scenario,
    save_scenario,
    validate_scenario,
)
from niharamesh.scenario.library import build_all, scenario_ids

if TYPE_CHECKING:
    from niharamesh.scenario.validation import ValidationReport

__all__ = ["add_parser", "run"]

EXIT_OK = 0
EXIT_INVALID_SCENARIO = 2
EXIT_SCENARIO_IO = 3


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    p = sub.add_parser("scenarios", help="author, export, validate and inspect scenarios")
    p.add_argument(
        "--root", default="scenarios", help="scenario root directory (default: scenarios)"
    )
    a = p.add_subparsers(dest="action", required=True)

    a.add_parser("export", help="write the built-in scenario library to the scenario root")

    lp = a.add_parser("list", help="list scenario files found under the root")
    lp.add_argument("--json", action="store_true", help="emit JSON instead of a table")

    vp = a.add_parser("validate", help="validate scenario files")
    vp.add_argument(
        "path", nargs="?", help="a scenario file; omit to validate everything under the root"
    )
    vp.add_argument("--json", action="store_true", help="emit JSON instead of text")
    vp.add_argument(
        "--structural-only",
        action="store_true",
        help="exit non-zero on structural problems only, ignoring workload-level ones",
    )

    sp = a.add_parser("show", help="print one scenario as JSON")
    sp.add_argument("scenario_id", help="built-in scenario id, e.g. headon-aisle")
    sp.add_argument("--file", help="instead of a built-in id, a path under the root")

    return p


def _print_report(sid: str, report: ValidationReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        return
    status = (
        "launchable"
        if report.launchable
        else ("diagnostic-only" if report.diagnostic_allowed else "INVALID")
    )
    print(f"{sid}  revision={report.revision}  {status}")
    for issue in report.issues:
        tag = {"structural": "BLOCK", "workload": "WORK ", "warning": "warn "}[issue.severity.value]
        print(f"  [{tag}] {issue.code}: {issue.message}")
        if issue.remedy:
            print(f"          -> {issue.remedy}")
    for limit in report.checks_not_performed:
        print(f"  [limit] not checked: {limit}")


def run(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root)

    if args.action == "export":
        written: list[str] = []
        for sid, scenario in build_all().items():
            path = save_scenario(scenario, root=root)
            written.append(
                f"{sid} -> {path} ({scenario.revision}, digest {scenario.digest()[:12]})"
            )
        print(f"exported {len(written)} scenarios to {root}")
        for line in written:
            print(f"  {line}")
        return EXIT_OK

    if args.action == "list":
        files = list_scenario_files(root)
        if args.json:
            print(
                json.dumps(
                    [
                        f.__dict__
                        if hasattr(f, "__dict__")
                        else {
                            "path": str(f.path),
                            "scenario_id": f.scenario_id,
                            "revision": f.revision,
                            "bytes": f.bytes,
                        }
                        for f in files
                    ],
                    indent=2,
                )
            )
            return EXIT_OK
        if not files:
            print(f"no scenario files under {root}. Run 'nihara scenarios export' first.")
            return EXIT_OK
        print(f"{'scenario_id':26s} {'rev':>4s} {'bytes':>8s}  path")
        for f in files:
            print(f"{f.scenario_id:26s} {f.revision:>4d} {f.bytes:>8d}  {f.path}")
        return EXIT_OK

    if args.action == "validate":
        if getattr(args, "path", None):
            try:
                scenario = load_scenario(args.path, root=root)
            except ScenarioIOError as exc:
                print(f"{exc}", file=sys.stderr)
                return EXIT_SCENARIO_IO
            targets = [(scenario.scenario_id, scenario)]
        else:
            targets = []
            for f in list_scenario_files(root):
                try:
                    targets.append((f.scenario_id, f.load(root)))
                except ScenarioIOError as exc:
                    print(f"{exc}", file=sys.stderr)
                    return EXIT_SCENARIO_IO
        failed_structural = False
        failed_workload = False
        for sid, scenario in targets:
            report = validate_scenario(scenario)
            _print_report(sid, report, as_json=args.json)
            if report.structural_issues:
                failed_structural = True
            if report.workload_issues:
                failed_workload = True
        if failed_structural:
            return EXIT_INVALID_SCENARIO
        if failed_workload and not args.structural_only:
            return EXIT_INVALID_SCENARIO
        return EXIT_OK

    if args.action == "show":
        if args.file:
            try:
                scenario = load_scenario(args.file, root=root)
            except ScenarioIOError as exc:
                print(f"{exc}", file=sys.stderr)
                return EXIT_SCENARIO_IO
        else:
            try:
                scenario = build_all()[args.scenario_id]
            except KeyError as exc:
                print(str(exc), file=sys.stderr)
                print(f"known scenarios: {', '.join(scenario_ids())}", file=sys.stderr)
                return EXIT_SCENARIO_IO
        print(scenario.canonical_json())
        return EXIT_OK

    raise AssertionError(f"unhandled scenarios action {args.action!r}")
