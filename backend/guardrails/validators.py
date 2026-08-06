"""Schema validation for LLM output.

An LLM asked for JSON returns JSON *usually*. Every parsed model output goes through
`validate_json` so a malformed response degrades to a safe default instead of raising
somewhere three layers up.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from observability.telemetry import log

T = TypeVar("T", bound=BaseModel)


def validate_json(raw: object, model: Type[T], default: T | None = None) -> T:
    """Coerce a parsed JSON blob into a Pydantic model, or fall back."""
    fallback = default if default is not None else model()
    if raw is None:
        return fallback
    if isinstance(raw, list):  # a model asked for an object sometimes returns [obj]
        raw = raw[0] if raw and isinstance(raw[0], dict) else None
    if not isinstance(raw, dict):
        return fallback
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        log.warning("%s validation failed: %s", model.__name__, exc.errors()[:2])
        return fallback


def check_response_shape(answer: str, min_chars: int = 2) -> tuple[bool, str]:
    """Cheap sanity checks on a free-text answer before it reaches the user.

    Catches the common local-model failure modes: empty output, a leaked prompt
    fragment, or the model narrating its own instructions.
    """
    text = (answer or "").strip()
    if len(text) < min_chars:
        return False, "empty response"

    lowered = text.lower()
    # [PLACEHOLDER: add domain-specific banned phrasings]
    for marker in ("as an ai language model", "system prompt:", "you are an enterprise assistant"):
        if marker in lowered:
            return False, "response leaked instruction text"

    return True, ""
