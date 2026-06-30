"""Small stdlib-only observability helpers.

The module intentionally keeps logging opt-in by environment and avoids
capturing user finance text unless OBSERVE_PAYLOADS=1.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Protocol


_DISABLED_VALUES = {"0", "false", "no", "off"}
_PAYLOAD_KEYS = {
    "args",
    "arguments",
    "content",
    "finance_agent_output",
    "input",
    "message",
    "messages",
    "payload",
    "prompt",
    "reply",
    "task",
    "text",
    "user_message",
}

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "observability_context",
    default={},
)


@dataclass(frozen=True)
class ObservabilityConfig:
    enabled: bool
    observe_payloads: bool
    log_format: str
    log_level: int

    @classmethod
    def from_env(cls) -> "ObservabilityConfig":
        return cls(
            enabled=_env_enabled("OBSERVABILITY_ENABLED", default="1"),
            observe_payloads=_env_enabled("OBSERVE_PAYLOADS", default="0"),
            log_format=_env_log_format(),
            log_level=_env_log_level(),
        )


class EventSink(Protocol):
    def emit(
        self,
        logger: logging.Logger,
        level: int,
        record: dict[str, Any],
        config: ObservabilityConfig,
    ) -> None:
        ...


@dataclass
class OperationEvent:
    start: float
    fields: dict[str, Any]

    def add_fields(self, **fields: Any) -> None:
        self.fields.update(fields)

    def elapsed_ms(self) -> int:
        return elapsed_ms(self.start)

    def timed_fields(self, status: str, exc: Exception | None = None) -> dict[str, Any]:
        return _timed_fields(self.start, status, self.fields, exc)


class LoggingEventSink:
    def emit(
        self,
        logger: logging.Logger,
        level: int,
        record: dict[str, Any],
        config: ObservabilityConfig,
    ) -> None:
        if config.log_format == "json":
            logger.log(level, json.dumps(record, sort_keys=True, separators=(",", ":")))
        else:
            logger.log(level, _plain_message(record))


_event_sink: EventSink = LoggingEventSink()


def set_event_sink(sink: EventSink) -> None:
    global _event_sink
    _event_sink = sink


def enabled() -> bool:
    return ObservabilityConfig.from_env().enabled


def observe_payloads() -> bool:
    return ObservabilityConfig.from_env().observe_payloads


def log_format() -> str:
    return ObservabilityConfig.from_env().log_format


def log_level() -> int:
    return ObservabilityConfig.from_env().log_level


def configure_logging(config: ObservabilityConfig | None = None) -> None:
    config = config or ObservabilityConfig.from_env()
    root = logging.getLogger()
    root.setLevel(config.log_level)
    if not root.handlers:
        logging.basicConfig(
            level=config.log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def current_context() -> dict[str, Any]:
    return dict(_context.get())


def current_request_id() -> str | None:
    value = _context.get().get("request_id")
    return str(value) if value else None


@contextmanager
def scoped_context(**fields: Any) -> Iterator[dict[str, Any]]:
    clean = {key: value for key, value in fields.items() if value is not None}
    merged = {**_context.get(), **clean}
    token = _context.set(merged)
    try:
        yield merged
    finally:
        _context.reset(token)


def elapsed_ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    payloads_allowed = ObservabilityConfig.from_env().observe_payloads
    for key, value in fields.items():
        if value is None:
            continue
        if not payloads_allowed and _is_payload_key(key):
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = json_safe(value)
    return cleaned


def payload(value: Any) -> Any:
    if observe_payloads():
        return json_safe(value)
    return "[redacted]"


def log_event(
    logger: logging.Logger | str,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> dict[str, Any] | None:
    config = ObservabilityConfig.from_env()
    if not config.enabled:
        return None

    record = {
        "event": event,
        **clean_fields(current_context()),
        **clean_fields(fields),
    }
    resolved_logger = logging.getLogger(logger) if isinstance(logger, str) else logger
    _event_sink.emit(resolved_logger, level, record, config)
    return record


@contextmanager
def operation(
    logger: logging.Logger | str,
    event: str,
    *,
    success_status: str = "ok",
    error_status: str = "error",
    level: int = logging.INFO,
    error_level: int = logging.ERROR,
    **fields: Any,
) -> Iterator[OperationEvent]:
    event_record = OperationEvent(start=time.perf_counter(), fields=dict(fields))
    try:
        yield event_record
    except Exception as exc:
        log_event(
            logger,
            event,
            level=error_level,
            **event_record.timed_fields(error_status, exc),
        )
        raise
    else:
        log_event(
            logger,
            event,
            level=level,
            **event_record.timed_fields(success_status),
        )


def timed_event(
    logger: logging.Logger | str,
    event: str,
    *,
    success_status: str = "ok",
    error_status: str = "error",
    level: int = logging.INFO,
    error_level: int = logging.ERROR,
    **fields: Any,
) -> Any:
    return operation(
        logger,
        event,
        success_status=success_status,
        error_status=error_status,
        level=level,
        error_level=error_level,
        **fields,
    )


@contextmanager
def timed_stage(
    stage_durations_ms: dict[str, int],
    stage: str,
    logger: logging.Logger | str | None = None,
    event: str | None = None,
    **fields: Any,
) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        event_fields = _timed_fields(start, "error", {"stage": stage, **fields}, exc)
        stage_durations_ms[stage] = int(event_fields["duration_ms"])
        if logger and event:
            log_event(logger, event, level=logging.ERROR, **event_fields)
        raise
    else:
        event_fields = _timed_fields(start, "ok", {"stage": stage, **fields})
        stage_durations_ms[stage] = int(event_fields["duration_ms"])
        if logger and event:
            log_event(logger, event, **event_fields)


def _env_enabled(name: str, *, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in _DISABLED_VALUES


def _env_log_format() -> str:
    value = os.getenv("LOG_FORMAT", "plain").strip().lower()
    return "json" if value == "json" else "plain"


def _env_log_level() -> int:
    name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, name, logging.INFO)


def _timed_fields(
    start: float,
    status: str,
    fields: dict[str, Any],
    exc: Exception | None = None,
) -> dict[str, Any]:
    timed = {
        **fields,
        "status": status,
        "duration_ms": elapsed_ms(start),
    }
    if exc is not None:
        timed["error_type"] = type(exc).__name__
    return timed


def _is_payload_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _PAYLOAD_KEYS or normalized.endswith("_payload")


def _plain_message(record: dict[str, Any]) -> str:
    event = str(record.get("event", "event"))
    parts = []
    for key in sorted(k for k in record if k != "event"):
        value = record[key]
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " ".join([event, *parts])
