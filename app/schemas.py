from __future__ import annotations

from typing import Any


DEFAULT_LAYOUT = {
    "mode": "flow",
    "direction": "horizontal",
    "gap": 25,
    "wrap": True,
    "padding": {"top": 10, "right": 10, "bottom": 10, "left": 10},
}


def default_title_block(template: str, title: str, scale: str, unit: str) -> dict[str, Any]:
    return {
        "template": template,
        "fields": {
            "图名": title,
            "比例": scale,
            "单位": unit,
        },
    }


def default_meta(product_name: str, scale: str, unit: str) -> dict[str, Any]:
    return {
        "title": "产品排版图",
        "productName": product_name,
        "scale": scale,
        "unit": unit,
    }


def validation_report(layout: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    missing: list[str] = []
    if not layout.get("variants"):
        missing.append("variants")
    if not layout.get("sizeTable", {}).get("rows"):
        missing.append("sizeTable.rows")

    return {
        "status": "needs_review" if missing else "ok",
        "warnings": warnings or [],
        "missing": missing,
    }
