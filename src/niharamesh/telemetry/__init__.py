"""Telemetry: the observer's recording surface and its gap bookkeeping.

This package imports only :mod:`niharamesh.domain` and :mod:`niharamesh.clocks`.
It has no concrete persistence dependency - the recorder is written against the
narrow :class:`~niharamesh.telemetry.recorder.RecorderSink` protocol - and
nothing in it holds authority. A lost recorder leaves every agent's decisions
exactly as they were and only removes evidence, which is then reported as an
explicit gap rather than quietly missing.
"""

from __future__ import annotations

from niharamesh.telemetry.gaps import GapSummary, RecordingGapTracker
from niharamesh.telemetry.recorder import Recorder, RecorderSink

__all__ = [
    "GapSummary",
    "Recorder",
    "RecorderSink",
    "RecordingGapTracker",
]
