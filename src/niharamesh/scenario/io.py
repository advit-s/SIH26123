"""Scenario load / save with path-safety and structural validation.

Security posture for imports (see ``docs/SECURITY.md``):

* A scenario path is resolved and must stay inside the configured scenario root.
  ``..`` traversal and absolute paths outside the root are refused.
* File size is bounded before parsing.
* Only JSON is parsed. No ``pickle``, no ``yaml.load``, no untrusted object
  deserialisation anywhere in this project.
* The parsed document is validated against the Pydantic domain models with
  ``extra="forbid"``, so unknown fields are errors rather than silent data loss.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from niharamesh.domain.scenario import Scenario
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "MAX_SCENARIO_BYTES",
    "PathEscape",
    "ScenarioIOError",
    "ScenarioTooLarge",
    "assert_known_schema",
    "list_scenario_files",
    "load_scenario",
    "load_scenario_json",
    "resolve_scenario_path",
    "save_scenario",
    "scenario_filename",
]

MAX_SCENARIO_BYTES = 4 * 1024 * 1024


class ScenarioIOError(Exception):
    """Base class for scenario IO problems. Carries a stable code."""


class PathEscape(ScenarioIOError):
    code = "scenario_path_outside_root"


class ScenarioTooLarge(ScenarioIOError):
    code = "scenario_too_large"


class MalformedScenario(ScenarioIOError):
    code = "scenario_malformed"


class IncompatibleSchema(ScenarioIOError):
    code = "scenario_schema_incompatible"


def resolve_scenario_path(root: pathlib.Path, candidate: str | pathlib.Path) -> pathlib.Path:
    """Resolve *candidate* to a path inside *root*, refusing any escape.

    Accepts an absolute path, a path relative to the current directory, or a path
    relative to *root* - whichever lands inside the root. Symlinks are resolved
    before the containment check, so a link inside the root cannot point out of it.
    """
    root_resolved = root.resolve()
    raw = pathlib.Path(candidate)
    options: list[pathlib.Path] = []
    if raw.is_absolute():
        options.append(raw)
    else:
        options.append(pathlib.Path.cwd() / raw)
        options.append(root_resolved / raw)
    first_error: PathEscape | None = None
    for option in options:
        resolved = option.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            first_error = PathEscape(
                f"scenario path {str(candidate)!r} resolves to {resolved}, "
                f"outside the scenario root {root_resolved}"
            )
            del exc
            continue
        return resolved
    raise first_error or PathEscape(
        f"scenario path {str(candidate)!r} could not be resolved under {root_resolved}"
    )


def assert_known_schema(document: dict[str, object]) -> None:
    """Refuse a scenario written against an incompatible schema family.

    We refuse rather than silently migrating: a silently-migrated scenario would
    change the meaning of an experiment without anybody noticing.
    """
    found = document.get("schema_version")
    if found is None:
        raise IncompatibleSchema("scenario document has no schema_version")
    if not isinstance(found, str):
        raise IncompatibleSchema("schema_version must be a string")
    if found.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        raise IncompatibleSchema(
            f"scenario schema_version {found!r} is not compatible with {SCHEMA_VERSION!r}; "
            "authored scenarios are not silently migrated"
        )


def load_scenario_json(raw: str | bytes) -> Scenario:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedScenario(f"scenario is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise MalformedScenario("scenario document must be a JSON object")
    assert_known_schema(document)
    try:
        return Scenario.model_validate(document)
    except Exception as exc:
        raise MalformedScenario(f"scenario failed domain validation: {exc}") from exc


def load_scenario(path: str | pathlib.Path, *, root: pathlib.Path | None = None) -> Scenario:
    base = root or pathlib.Path("scenarios")
    resolved = resolve_scenario_path(base, path)
    if not resolved.is_file():
        raise ScenarioIOError(f"scenario file not found: {resolved}")
    size = resolved.stat().st_size
    if size > MAX_SCENARIO_BYTES:
        raise ScenarioTooLarge(
            f"scenario file is {size} bytes, above the {MAX_SCENARIO_BYTES} byte limit"
        )
    return load_scenario_json(resolved.read_bytes())


def scenario_filename(scenario: Scenario) -> str:
    return f"{scenario.scenario_id}.r{scenario.revision}.json"


def save_scenario(scenario: Scenario, *, root: pathlib.Path | None = None) -> pathlib.Path:
    base = root or pathlib.Path("scenarios")
    base.mkdir(parents=True, exist_ok=True)
    target = resolve_scenario_path(base, scenario_filename(scenario))
    document = json.loads(scenario.canonical_json())
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > MAX_SCENARIO_BYTES:
        raise ScenarioTooLarge("serialised scenario exceeds the size limit")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target


@dataclass(frozen=True, slots=True)
class ScenarioFile:
    path: pathlib.Path
    scenario_id: str
    revision: int
    bytes: int

    def load(self, root: pathlib.Path | None = None) -> Scenario:
        return load_scenario(self.path, root=root)


def list_scenario_files(root: pathlib.Path | None = None) -> list[ScenarioFile]:
    base = root or pathlib.Path("scenarios")
    if not base.is_dir():
        return []
    out: list[ScenarioFile] = []
    for path in sorted(base.rglob("*.json")):
        if path.name.endswith(".tmp"):
            continue
        try:
            resolved = resolve_scenario_path(base, path)
            scenario = load_scenario(resolved, root=base)
        except ScenarioIOError:
            continue
        out.append(
            ScenarioFile(
                path=resolved,
                scenario_id=scenario.scenario_id,
                revision=scenario.revision,
                bytes=resolved.stat().st_size,
            )
        )
    return out
