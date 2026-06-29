"""Shared runtime configuration helpers."""

from __future__ import annotations

import os


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def normalize_openai_api_key() -> None:
    """Keep OpenAI API setup explicit; this app reads OPENAI_API_KEY only."""


def has_openai_api_key() -> bool:
    normalize_openai_api_key()
    return bool(os.getenv("OPENAI_API_KEY"))


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
