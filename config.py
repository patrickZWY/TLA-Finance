"""Shared runtime configuration helpers."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_API_KEY = "local-demo-key"
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:8000", "http://localhost:8000")
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "testserver")
PUBLIC_HOSTNAME_ENV_KEYS = ("PUBLIC_HOSTNAME", "PUBLIC_DEMO_HOSTNAME", "CLOUDFLARE_HOSTNAME", "CF_HOSTNAME")


def normalize_openai_api_key() -> None:
    """Compatibility hook for older callers; LLM config is read lazily."""


def has_openai_api_key() -> bool:
    """Return true when either OpenAI or an OpenAI-compatible local LLM is configured."""

    return bool(os.getenv("OPENAI_API_KEY") or openai_base_url())


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)


def openai_base_url() -> str | None:
    value = os.getenv("OPENAI_BASE_URL") or os.getenv("LOCAL_LLM_BASE_URL")
    return value.strip() if value and value.strip() else None


def openai_api_key() -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    if key:
        return key
    if openai_base_url():
        return DEFAULT_LOCAL_API_KEY
    return None


def openai_json_mode_enabled() -> bool:
    value = os.getenv("OPENAI_JSON_MODE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def openai_reasoning_effort() -> str | None:
    value = os.getenv("OPENAI_REASONING_EFFORT")
    return value.strip() if value and value.strip() else None


def openai_chat_options(**kwargs: Any) -> dict[str, Any]:
    options = dict(kwargs)
    if openai_json_mode_enabled():
        options["response_format"] = {"type": "json_object"}
    reasoning_effort = openai_reasoning_effort()
    if reasoning_effort:
        options["reasoning_effort"] = reasoning_effort
    return options


def allowed_origins() -> list[str]:
    configured = _csv_env("ALLOWED_ORIGINS")
    if configured:
        return configured
    hostnames = public_hostnames()
    if hostnames:
        return [f"https://{hostname}" for hostname in hostnames] + list(DEFAULT_ALLOWED_ORIGINS)
    return list(DEFAULT_ALLOWED_ORIGINS)


def trusted_hosts() -> list[str]:
    configured = _csv_env("ALLOWED_HOSTS")
    if configured:
        return [_host_value(item) for item in configured]

    hosts = set(DEFAULT_ALLOWED_HOSTS)
    for origin in allowed_origins():
        host = _host_value(origin)
        if host:
            hosts.add(host)
    for hostname in public_hostnames():
        hosts.add(hostname)
    return sorted(hosts)


def public_hostname() -> str | None:
    hostnames = public_hostnames()
    return hostnames[0] if hostnames else None


def public_hostnames() -> list[str]:
    hostnames: list[str] = []
    seen: set[str] = set()
    for key in PUBLIC_HOSTNAME_ENV_KEYS:
        value = os.getenv(key)
        if value and value.strip():
            host = _host_value(value.strip())
            if host and host not in seen:
                hostnames.append(host)
                seen.add(host)
    return hostnames


def safety_subprocess_timeout_seconds(kind: str | None = None) -> int:
    if kind:
        per_kind = _positive_int_env(f"SAFETY_{kind.upper()}_TIMEOUT_SECONDS", 0)
        if per_kind:
            return per_kind
    return _positive_int_env(
        "SAFETY_TLA_TIMEOUT_SECONDS",
        _positive_int_env("SAFETY_SUBPROCESS_TIMEOUT_SECONDS", 60),
    )


def openai_client():
    from openai import OpenAI

    kwargs: dict[str, str] = {}
    api_key = openai_api_key()
    base_url = openai_base_url()
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _host_value(value: str) -> str:
    if value == "*":
        return value
    parsed = urlparse(value if "://" in value else f"//{value}", scheme="https")
    return (parsed.hostname or value).strip()


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
