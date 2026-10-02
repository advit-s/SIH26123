"""One-off maintenance helper used to apply reviewed textual fixes.

Kept in the repository so the change is auditable rather than a mystery, and so
the same fix can be re-applied after regeneration. It is not part of the runtime.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def apply(path: str, replacements: list[tuple[str, str]]) -> bool:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    original = text
    for old, new in replacements:
        if old not in text:
            print(f"  MISS {path}: {old[:60]!r}")
            continue
        text = text.replace(old, new, 1)
    if text != original:
        target.write_text(text, encoding="utf-8")
        print(f"  patched {path}")
        return True
    return False


def drop_block(path: str, start_marker: str, end_marker: str) -> bool:
    """Remove a whole top-level block by markers (dead code removal)."""
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    i = text.find(start_marker)
    if i < 0:
        print(f"  MISS block start in {path}")
        return False
    j = text.find(end_marker, i)
    if j < 0:
        print(f"  MISS block end in {path}")
        return False
    target.write_text(text[:i] + text[j + len(end_marker) :], encoding="utf-8")
    print(f"  removed block from {path}")
    return True


def main() -> int:
    changed = False
    changed |= apply(
        "src/niharamesh/cli/main.py",
        [
            (
                '        parser.error(f"command {args.command!r} is not available in this checkout")\n'
                "        return EXIT_INVALID\n",
                '        parser.error(f"command {args.command!r} is not available in this checkout")\n',
            ),
            (
                '        parser.error(f"command {args.command!r} has no entry point")\n'
                "        return EXIT_INVALID\n",
                '        parser.error(f"command {args.command!r} has no entry point")\n',
            ),
        ],
    )
    changed |= apply(
        "src/niharamesh/cli/doctor.py",
        [
            (
                "# noqa: S603, S607 - resolved via shutil.which above",
                "# noqa: S603 - resolved via shutil.which above",
            ),
        ],
    )
    changed |= drop_block(
        "src/niharamesh/scenario/library.py",
        "def _with_zones(",
        'return wm.model_copy(update={"zones": zones, "stop_lines": lines})  # type: ignore[arg-type]\n',
    )
    changed |= apply(
        "src/niharamesh/scenario/library.py",
        [
            (
                "def _stop(lid: str, zone_id: str, x0: float, x1: float, y: float):\n    from niharamesh.domain.map import StopLine\n",
                "def _stop(lid: str, zone_id: str, x0: float, x1: float, y: float) -> StopLine:\n",
            ),
            (
                "from niharamesh.domain.map import ObstacleKind, WarehouseMap, Zone",
                "from niharamesh.domain.map import ObstacleKind, StopLine, WarehouseMap, Zone",
            ),
        ],
    )
    # Remove the now-unneeded type: ignore comments left by earlier drafts.
    for rel in (
        "src/niharamesh/scenario/library.py",
        "src/niharamesh/scenario/validation.py",
    ):
        p = ROOT / rel
        t = p.read_text(encoding="utf-8")
        t2 = re.sub(r"  # type: ignore\[arg-type\]\n", "\n", t)
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            print(f"  stripped arg-type ignores from {rel}")
            changed = True
    print("changed" if changed else "no change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
