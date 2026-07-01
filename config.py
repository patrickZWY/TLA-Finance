"""Shared runtime configuration helpers."""

from __future__ import annotations

import os
from typing import Any


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_API_KEY = "local-demo-key"


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
