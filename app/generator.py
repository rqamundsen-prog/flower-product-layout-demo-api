from __future__ import annotations

from typing import Any

from app.codex_bridge import generate_layout_via_codex
from app.normalizer import normalize_product_layout


def generate_layout(
    extracted_files: list[dict[str, Any]],
    prompt: str = "",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_parameters = parameters or {}
    payload = generate_layout_via_codex(
        extracted_files=extracted_files,
        prompt=prompt,
        parameters=active_parameters,
    )
    return normalize_product_layout(payload, active_parameters)
