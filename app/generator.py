from __future__ import annotations

import re
from typing import Any

from app.schemas import DEFAULT_LAYOUT, default_meta, default_title_block, validation_report


PART_CATEGORY = {
    "被套": "quilt-face",
    "加大被套": "quilt-face",
    "床单": "bedsheet",
    "加大床单": "bedsheet",
    "短枕套": "pillowcase",
}


def generate_layout(
    extracted_files: list[dict[str, Any]],
    prompt: str = "",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parameters = parameters or {}
    corpus = "\n".join(str(item.get("text", "")) for item in extracted_files)
    combined = f"{corpus}\n{prompt}"

    product_name = _product_name(combined, parameters)
    scale = str(parameters.get("scale") or _first_match(combined, r"1\s*:\s*\d+") or "1:50").replace(" ", "")
    unit = str(parameters.get("unit") or _first_match(combined, r"\b(cm|mm)\b") or "cm")
    template = str(parameters.get("template") or parameters.get("template_id") or _template_from_text(combined))

    if isinstance(parameters.get("variants"), list) and parameters["variants"]:
        variants = [_normalize_parameter_variant(variant) for variant in parameters["variants"]]
    else:
        specs = _extract_part_specs(combined)
        sku_ids = _extract_sku_ids(combined)
        variants = [_variant_from_specs(sku, specs, combined) for sku in sku_ids]

    size_rows = _size_table_rows(variants)
    layout = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": default_meta(product_name, scale, unit),
        "technicalRequirements": _technical_requirements(combined),
        "sizeTable": {
            "columns": ["partName", "finishedSize", "cuttingSizeFace", "cuttingSizeBack"],
            "rows": size_rows,
        },
        "variants": variants,
        "titleBlock": default_title_block(template, "产品排版图", scale, unit),
    }

    return {
        "layout": layout,
        "validation": validation_report(layout, _warnings(extracted_files, prompt, parameters)),
        "sources": [
            {
                "filename": item.get("filename"),
                "kind": item.get("kind", "file"),
                "textLength": len(str(item.get("text", ""))),
            }
            for item in extracted_files
        ],
    }


def _product_name(text: str, parameters: dict[str, Any]) -> str:
    if parameters.get("productName"):
        return str(parameters["productName"])
    if parameters.get("product_name"):
        return str(parameters["product_name"])
    if "温莎城堡" in text:
        return "温莎城堡"
    compact = _compact(text)
    match = re.search(r"品名([^花型号]{2,40})", compact)
    if match:
        return match.group(1).strip("：:")
    return "产品排版图"


def _template_from_text(text: str) -> str:
    return "queen-standard-a3" if re.search(r"QUEEN|Queen|queen|模板\s*QUEEN", text) else "standard-a3"


def _extract_sku_ids(text: str) -> list[str]:
    ids = sorted(set(re.findall(r"(?<!\d)(101\d{7})(?!\d)", text)))
    return ids or ["demo-variant"]


def _extract_part_specs(text: str) -> list[dict[str, Any]]:
    compact = _compact(text)
    specs: list[dict[str, Any]] = []
    pattern = re.compile(r"(加大被套|加大床单|短枕套|短枕套|被套|床单)[：:（(]*?(\d+(?:\.\d+)?)×(\d+(?:\.\d+)?)(?:\)cm|\）cm|cm)?×?(\d+)?")
    for match in pattern.finditer(compact):
        name = match.group(1).replace("短枕套", "短枕套")
        width = _number(match.group(2))
        height = _number(match.group(3))
        count = int(match.group(4) or 1)
        if width and height:
            specs.append(
                {
                    "name": name,
                    "category": PART_CATEGORY.get(name, "textile-part"),
                    "finishedSize": {"width": width, "height": height},
                    "cuttingSizeFace": _demo_cutting_size(name, width, height),
                    "quantity": {"perSet": count, "unit": "页" if count == 1 else "个"},
                }
            )
    return specs or [_fallback_component_spec()]


def _variant_from_specs(sku: str, specs: list[dict[str, Any]], text: str) -> dict[str, Any]:
    return {
        "id": sku,
        "label": sku,
        "layout": dict(DEFAULT_LAYOUT),
        "components": [
            _component_from_spec(index, spec, _is_rounded_bedsheet(text))
            for index, spec in enumerate(specs, start=1)
        ],
    }


def _component_from_spec(index: int, spec: dict[str, Any], rounded_bedsheet: bool) -> dict[str, Any]:
    name = spec["name"]
    finished = spec["finishedSize"]
    shape: dict[str, Any] = {
        "type": "roundedRectangle" if rounded_bedsheet and spec["category"] == "bedsheet" else "rectangle",
        "width": finished["width"],
        "height": finished["height"],
    }
    if shape["type"] == "roundedRectangle":
        shape["corners"] = {
            "bottomLeft": {"template": "round-corner"},
            "bottomRight": {"template": "round-corner"},
        }

    return {
        "id": f"part-{index}-{_ascii_slug(name)}",
        "name": name,
        "category": spec["category"],
        "quantity": spec["quantity"],
        "shape": shape,
        "display": {"showDimensions": True, "dimensionSides": ["width", "height"], "grainDirection": "up"},
        "annotations": [{"kind": "label", "text": f"{name}\n({spec['quantity']['perSet']}套)", "placement": "inside"}],
        "dimensions": {"finishedSize": finished, "cuttingSizeFace": spec.get("cuttingSizeFace")},
    }


def _normalize_parameter_variant(variant: dict[str, Any]) -> dict[str, Any]:
    components = variant.get("components") or []
    return {
        "id": str(variant.get("id") or variant.get("label") or "demo-variant"),
        "label": str(variant.get("label") or variant.get("id") or "demo-variant"),
        "layout": variant.get("layout") or dict(DEFAULT_LAYOUT),
        "components": components,
    }


def _size_table_rows(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for variant in variants:
        for component in variant.get("components", []):
            key = (variant["id"], component.get("id", component.get("name", "")))
            if key in seen:
                continue
            seen.add(key)
            shape = component.get("shape", {})
            dimensions = component.get("dimensions", {})
            finished = dimensions.get("finishedSize") or {
                "width": shape.get("width"),
                "height": shape.get("height"),
            }
            rows.append(
                {
                    "variantId": variant["id"],
                    "partId": component.get("id"),
                    "partName": component.get("name"),
                    "finishedSize": finished,
                    "cuttingSizeFace": dimensions.get("cuttingSizeFace"),
                    "cuttingSizeBack": dimensions.get("cuttingSizeBack"),
                }
            )
    return rows


def _technical_requirements(text: str) -> list[dict[str, Any]]:
    requirements = [
        "Demo输出用于CAD渲染前的数据交接，具体工艺规则需由技术员复核",
        "被套、床单、枕套尺寸按上传资料和用户参数生成",
    ]
    if "圆角" in text:
        requirements.append("床单圆角按用户参数或模板默认值处理")
    return [{"no": index, "text": value} for index, value in enumerate(requirements, start=1)]


def _warnings(extracted_files: list[dict[str, Any]], prompt: str, parameters: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not extracted_files:
        warnings.append("未上传文件，结果仅基于用户参数生成")
    if not prompt and not parameters:
        warnings.append("未提供补充参数，demo将使用默认模板和默认比例")
    return warnings


def _demo_cutting_size(name: str, width: float | int, height: float | int) -> dict[str, Any]:
    if "枕" in name:
        return {"width": _clean_number(width + 2), "height": _clean_number(height + 2)}
    if "床单" in name:
        return {"width": _clean_number(width + 3), "height": _clean_number(height + 5)}
    return {"width": _clean_number(width + 4), "height": _clean_number(height + 4)}


def _fallback_component_spec() -> dict[str, Any]:
    return {
        "name": "演示裁片",
        "category": "textile-part",
        "finishedSize": {"width": 100, "height": 100},
        "cuttingSizeFace": {"width": 100, "height": 100},
        "quantity": {"perSet": 1, "unit": "页"},
    }


def _is_rounded_bedsheet(text: str) -> bool:
    return "圆角" in text


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _number(value: str) -> int | float:
    parsed = float(value)
    return _clean_number(parsed)


def _clean_number(value: float | int) -> int | float:
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _ascii_slug(value: str) -> str:
    known = {"被套": "quilt", "加大被套": "large-quilt", "床单": "bedsheet", "加大床单": "large-bedsheet", "短枕套": "pillowcase"}
    return known.get(value, "component")
