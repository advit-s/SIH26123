"""Turning exceptions into actionable, honest CLI messages.

A user-facing error must say what happened, why, and what to do next. It must not
leak a traceback unless ``NIHARA_TRACEBACK=1`` is set, and it must never claim a
result it does not have.
"""

from __future__ import annotations

import os

from niharamesh.scenario.io import PathEscape, ScenarioIOError, ScenarioTooLarge

__all__ = ["describe", "show_traceback"]

#: Remedy text keyed by exception class *name*. Keyed by name rather than by class
#: so this module does not need to import every error type in the project, which
#: would create an import cycle from the CLI down into the domain layers.
_REMEDY: dict[str, str] = {
    "IncompatibleSchema": (
        "The file was authored against a different schema family. It is never auto-migrated, "
        "because a silent migration would change the meaning of an experiment. Re-author it."
    ),
    "MalformedScenario": (
        "The file is not valid JSON or failed domain validation. Fix the reported field and retry."
    ),
    "PathEscape": "Only paths inside the configured scenario root are accepted.",
    "ScenarioTooLarge": "Split the scenario or raise NIHARA_MAX_SCENARIO_BYTES deliberately.",
    "KeyError": "The named entity does not exist in this scenario. Check the ids you passed.",
    "FileNotFoundError": "Check the path. Relative paths resolve against the current directory.",
}


def show_traceback() -> bool:
    return os.environ.get("NIHARA_TRACEBACK", "").strip().lower() in ("1", "true", "yes")


def describe(exc: BaseException) -> str:
    if show_traceback():
        import traceback

        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    kind = type(exc).__name__
    remedy = _REMEDY.get(kind)
    message = str(exc) or "no further detail available"
    lines = [f"{kind}: {message}"]
    if remedy:
        lines.append(f"  -> {remedy}")
    if isinstance(exc, (ScenarioIOError, PathEscape, ScenarioTooLarge)):
        lines.append(f"  -> stable error code: {getattr(exc, 'code', 'scenario_io')}")
    cause = exc.__cause__ or exc.__context__
    if cause is not None and not isinstance(cause, type(exc)) and kind != "Exception":
        lines.append(f"  caused by {type(cause).__name__}: {cause}")
    return "\n".join(lines)
