"""Utilities for retaining generated safety artifacts locally."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Iterable


DEFAULT_SAFETY_ARTIFACT_ROOT = Path("artifacts/safety-runs")
DEFAULT_RETENTION_HOURS = 24.0


def safety_artifact_retention_hours() -> float:
    value = os.getenv("SAFETY_ARTIFACT_RETENTION_HOURS", "").strip()
    if not value:
        return DEFAULT_RETENTION_HOURS
    try:
        parsed = float(value)
    except ValueError:
        return DEFAULT_RETENTION_HOURS
    return parsed if parsed > 0 else DEFAULT_RETENTION_HOURS


def cleanup_old_safety_artifacts(
    root: Path | str = DEFAULT_SAFETY_ARTIFACT_ROOT,
    *,
    retention_hours: float | None = None,
    now: float | None = None,
) -> list[Path]:
    """Remove old per-run safety artifact directories and return removed paths."""

    root_path = Path(root)
    retention = safety_artifact_retention_hours() if retention_hours is None else retention_hours
    if retention <= 0 or not root_path.exists():
        return []

    cutoff = (time.time() if now is None else now) - retention * 60 * 60
    removed: list[Path] = []
    for child in _artifact_dirs(root_path):
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(child)
            removed.append(child)
        except FileNotFoundError:
            continue
    return removed


def _artifact_dirs(root: Path) -> Iterable[Path]:
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        yield child
