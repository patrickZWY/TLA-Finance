"""TLC runner for generated finance safety specs."""

from __future__ import annotations

import os
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import observability
from config import safety_subprocess_timeout_seconds

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TlcResult:
    status: str
    command: list[str]
    returncode: int | None
    output: str

    @property
    def verified(self) -> bool:
        return self.status == "passed"

    @property
    def has_violation(self) -> bool:
        return self.status == "failed"

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "command": self.command,
            "returncode": self.returncode,
            "output": self.output,
        }


@dataclass(frozen=True)
class PlusCalResult:
    status: str
    command: list[str]
    returncode: int | None
    output: str

    @property
    def translated(self) -> bool:
        return self.status == "translated"

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "command": self.command,
            "returncode": self.returncode,
            "output": self.output,
        }


def find_tla_tools_jar() -> Path | None:
    explicit = os.getenv("TLAPLUS_JAR")
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path

    tla_home = os.getenv("TLA_HOME")
    if tla_home:
        path = Path(tla_home).expanduser() / "tla2tools.jar"
        if path.exists():
            return path

    for candidate in (
        Path.home() / "tools" / "tla2tools.jar",
        Path("/opt/tlaplus/tla2tools.jar"),
        Path("/usr/local/lib/tla2tools.jar"),
    ):
        if candidate.exists():
            return candidate

    return None


def translate_pluscal(tla_path: Path, timeout_seconds: int | None = None) -> PlusCalResult:
    timeout_seconds = timeout_seconds or safety_subprocess_timeout_seconds("pluscal")
    start = time.perf_counter()
    jar = find_tla_tools_jar()
    if jar is None:
        _log_subprocess(start, "pluscal", timeout_seconds, "not_configured", None)
        return PlusCalResult(
            status="not_configured",
            command=[],
            returncode=None,
            output=(
                "TLA+ tools are not configured. Set TLAPLUS_JAR to tla2tools.jar "
                "or set TLA_HOME to a directory containing tla2tools.jar."
            ),
        )

    command = [
        "java",
        "-cp",
        str(jar),
        "pcal.trans",
        "-nocfg",
        "-unixEOL",
        tla_path.name,
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=tla_path.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        _log_subprocess(start, "pluscal", timeout_seconds, "not_configured", None)
        return PlusCalResult(
            status="not_configured",
            command=command,
            returncode=None,
            output=f"Java is not available: {exc}",
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        _log_subprocess(start, "pluscal", timeout_seconds, "timeout", None)
        return PlusCalResult(
            status="timeout",
            command=command,
            returncode=None,
            output=output or f"PlusCal translation timed out after {timeout_seconds} seconds.",
        )

    output = completed.stdout + completed.stderr
    status = "translated" if completed.returncode == 0 else "failed"
    _log_subprocess(start, "pluscal", timeout_seconds, status, completed.returncode)
    return PlusCalResult(
        status=status,
        command=command,
        returncode=completed.returncode,
        output=output,
    )


def run_tlc(
    tla_path: Path,
    cfg_path: Path,
    timeout_seconds: int | None = None,
    dot_path: Path | None = None,
) -> TlcResult:
    timeout_seconds = timeout_seconds or safety_subprocess_timeout_seconds("tlc")
    start = time.perf_counter()
    jar = find_tla_tools_jar()
    if jar is None:
        _log_subprocess(start, "tlc", timeout_seconds, "not_configured", None)
        return TlcResult(
            status="not_configured",
            command=[],
            returncode=None,
            output=(
                "TLA+ tools are not configured. Set TLAPLUS_JAR to tla2tools.jar "
                "or set TLA_HOME to a directory containing tla2tools.jar."
            ),
        )

    command = [
        "java",
        "-cp",
        str(jar),
        "tlc2.TLC",
    ]
    if dot_path is not None:
        command.extend(["-dump", "dot,actionlabels,colorize", dot_path.name])
    command.extend([
        "-config",
        cfg_path.name,
        tla_path.name,
    ])

    try:
        completed = subprocess.run(
            command,
            cwd=tla_path.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        _log_subprocess(start, "tlc", timeout_seconds, "not_configured", None)
        return TlcResult(
            status="not_configured",
            command=command,
            returncode=None,
            output=f"Java is not available: {exc}",
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        _log_subprocess(start, "tlc", timeout_seconds, "timeout", None)
        return TlcResult(
            status="timeout",
            command=command,
            returncode=None,
            output=output or f"TLC timed out after {timeout_seconds} seconds.",
        )

    output = completed.stdout + completed.stderr
    if completed.returncode == 0 and "No error has been found" in output:
        status = "passed"
    else:
        status = "failed"

    _log_subprocess(start, "tlc", timeout_seconds, status, completed.returncode)
    return TlcResult(
        status=status,
        command=command,
        returncode=completed.returncode,
        output=output,
    )


def _log_subprocess(
    start: float,
    command_kind: str,
    timeout_seconds: int,
    status: str,
    returncode: int | None,
) -> None:
    observability.log_event(
        logger,
        "safety.subprocess",
        command_kind=command_kind,
        timeout_seconds=timeout_seconds,
        status=status,
        returncode=returncode,
        duration_ms=observability.elapsed_ms(start),
    )
