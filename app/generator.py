from __future__ import annotations

from typing import Any

from app.codex_bridge import generate_layout_via_codex


def generate_layout(
    extracted_files: list[dict[str, Any]],
    prompt: str = "",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return generate_layout_via_codex(
        extracted_files=extracted_files,
        prompt=prompt,
        parameters=parameters or {},
    )
