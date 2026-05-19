from __future__ import annotations

import copy
import re
from typing import Any


TOP_LEVEL_KEYS = [
    "schemaVersion",
    "documentType",
    "meta",
    "technicalRequirements",
    "sizeTable",
    "variants",
    "titleBlock",
]

SIZE_TABLE_COLUMNS = [
    "variantId",
    "sku",
    "color",
    "partId",
    "partName",
    "quantity",
    "finishedSize",
    "cuttingSizeFace",
    "cuttingSizeBack",
    "source",
]

PART_ORDER = {
    "quilt-face-main": 10,
    "quilt-lining-main": 20,
    "quilt-face-lower-small-panel": 30,
    "bedsheet": 40,
    "pillowcase-short": 50,
    "pillowcase": 55,
}

CORE_COMPONENTS = [
    ("quilt-face-main", "被面A版", "quilt-face"),
    ("quilt-lining-main", "被里B版", "quilt-lining"),
    ("quilt-face-lower-small-panel", "被面下方小页", "quilt-face"),
    ("bedsheet", "床单", "bedsheet"),
    ("pillowcase-short", "短枕套", "pillowcase"),
]
CORE_COMPONENT_IDS = {component_id for component_id, _name, _category in CORE_COMPONENTS}
KNOWN_WINDSOR_VARIANT_IDS = {
    "1010103855_1010103857",
    "1010103856_1010103858",
    "queen-200x230",
    "queen-248x248",
}


def normalize_product_layout(payload: dict[str, Any], parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    params = parameters or {}
    source = copy.deepcopy(payload)

    meta = _normalize_meta(source.get("meta"), params)
    title_block = _normalize_title_block(source.get("titleBlock"), params, meta)
    technical_requirements = _normalize_technical_requirements(source.get("technicalRequirements"))
    variants, id_maps = _normalize_variants(source.get("variants"))
    size_table = _normalize_size_table(source.get("sizeTable"), variants, id_maps)

    return {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": meta,
        "technicalRequirements": technical_requirements,
        "sizeTable": size_table,
        "variants": variants,
        "titleBlock": title_block,
    }


def _normalize_meta(value: Any, parameters: dict[str, Any]) -> dict[str, Any]:
    meta = value if isinstance(value, dict) else {}
    normalized = dict(meta)
    normalized.setdefault("title", "产品排版图")
    normalized["scale"] = str(parameters.get("scale") or normalized.get("scale") or "1:50")
    normalized["unit"] = str(parameters.get("unit") or normalized.get("unit") or "cm")
    return normalized


def _normalize_title_block(value: Any, parameters: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    block = value if isinstance(value, dict) else {}
    fields = block.get("fields") if isinstance(block.get("fields"), dict) else {}
    normalized_fields = dict(fields)
    normalized_fields["图名"] = str(normalized_fields.get("图名") or meta.get("title") or "产品排版图")
    normalized_fields["比例"] = str(parameters.get("scale") or normalized_fields.get("比例") or meta.get("scale") or "1:50")
    normalized_fields["单位"] = str(parameters.get("unit") or normalized_fields.get("单位") or meta.get("unit") or "cm")
    if "未确定项" not in normalized_fields:
        normalized_fields["未确定项"] = []
    return {
        "template": str(parameters.get("template") or block.get("template") or "standard-a3"),
        "fields": normalized_fields,
    }


def _normalize_technical_requirements(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = [item for item in value if isinstance(item, dict) and str(item.get("text") or "").strip()]
    items.sort(key=lambda item: _number_or_large(item.get("no")))
    return [{"no": index, "text": str(item.get("text")).strip()} for index, item in enumerate(items, start=1)]


def _normalize_variants(value: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    variants = value if isinstance(value, list) else []
    normalized_variants: list[dict[str, Any]] = []
    id_maps: dict[str, dict[str, str]] = {}

    for index, item in enumerate(variants, start=1):
        if not isinstance(item, dict):
            continue
        old_variant_id = str(item.get("id") or f"variant-{index}")
        variant_text = _json_text(item)
        new_variant_id = _canonical_variant_id(item, variant_text, index)
        component_map: dict[str, str] = {}
        components = []
        for component_index, component in enumerate(item.get("components") if isinstance(item.get("components"), list) else [], start=1):
            if not isinstance(component, dict):
                continue
            old_component_id = str(component.get("id") or f"component-{component_index}")
            normalized_component = _normalize_component(component, component_index)
            component_map[old_component_id] = normalized_component["id"]
            components.append(normalized_component)

        components = _dedupe_components(components)
        if _is_known_windsor_variant(new_variant_id, variant_text):
            components = _ensure_core_components(components)
        components.sort(key=lambda component: (PART_ORDER.get(component.get("id"), 1000), str(component.get("id"))))
        normalized_variant = dict(item)
        normalized_variant["id"] = new_variant_id
        normalized_variant["label"] = str(item.get("label") or new_variant_id)
        normalized_variant["layout"] = item.get("layout") if isinstance(item.get("layout"), dict) else {}
        normalized_variant["components"] = components
        normalized_variants.append(normalized_variant)
        id_maps[old_variant_id] = {"variantId": new_variant_id, **component_map}

    normalized_variants.sort(key=lambda variant: _variant_sort_key(variant))
    return normalized_variants, id_maps


def _normalize_component(component: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(component.get("name") or component.get("id") or f"裁片{index}")
    original_category = str(component.get("category") or "")
    category = _canonical_category(name, original_category)
    component_id = _canonical_component_id(name, original_category, category, component.get("id"), index)
    normalized = dict(component)
    normalized["id"] = component_id
    normalized["name"] = name
    normalized["category"] = category
    normalized["quantity"] = component.get("quantity") if isinstance(component.get("quantity"), dict) else {}
    normalized["shape"] = component.get("shape") if isinstance(component.get("shape"), dict) else {}
    normalized["display"] = component.get("display") if isinstance(component.get("display"), dict) else {}
    normalized["annotations"] = component.get("annotations") if isinstance(component.get("annotations"), list) else []
    normalized["dimensions"] = component.get("dimensions") if isinstance(component.get("dimensions"), dict) else {}
    return normalized


def _normalize_size_table(
    value: Any,
    variants: list[dict[str, Any]],
    id_maps: dict[str, dict[str, str]],
) -> dict[str, Any]:
    table = value if isinstance(value, dict) else {}
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    variant_index = {variant["id"]: index for index, variant in enumerate(variants)}
    normalized_rows = []

    known_variant_ids = {
        variant["id"]
        for variant in variants
        if _is_known_windsor_variant(str(variant.get("id") or ""), _json_text(variant))
    }

    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        old_variant_id = str(row.get("variantId") or "")
        old_part_id = str(row.get("partId") or "")
        id_map = id_maps.get(old_variant_id, {})
        normalized["variantId"] = id_map.get("variantId", _canonical_variant_id(row, _json_text(row), len(normalized_rows) + 1))
        normalized["partId"] = id_map.get(old_part_id, _canonical_part_id_from_row(row))
        if normalized["variantId"] in known_variant_ids and normalized["partId"] not in CORE_COMPONENT_IDS:
            continue
        normalized_rows.append(normalized)

    normalized_rows = _dedupe_size_rows(normalized_rows)
    normalized_rows = _ensure_core_size_rows(normalized_rows, known_variant_ids)
    normalized_rows.sort(
        key=lambda row: (
            variant_index.get(row.get("variantId"), 1000),
            PART_ORDER.get(row.get("partId"), 1000),
            str(row.get("partId") or ""),
        )
    )
    return {"columns": list(table.get("columns") or SIZE_TABLE_COLUMNS), "rows": normalized_rows}


def _canonical_variant_id(item: dict[str, Any], text: str, index: int) -> str:
    skus = _sku_values(text)
    if skus:
        return "_".join(skus[:2])
    normalized_text = text.replace("×", "x").replace("*", "x")
    if "248x248" in normalized_text or "250x250" in normalized_text or "加大" in text:
        return "queen-248x248"
    if "200x230" in normalized_text or "标准" in text or "STD" in text.upper():
        return "queen-200x230"
    raw = str(item.get("id") or item.get("variantId") or item.get("label") or f"variant-{index}")
    return _slug(raw) or f"variant-{index}"


def _canonical_category(name: str, category: str) -> str:
    text = f"{name} {category}".lower()
    if "床单" in name or "flat-sheet" in text or "bedsheet" in text:
        return "bedsheet"
    if "枕" in name or "pillow" in text:
        return "pillowcase"
    if "被里" in name or "quilt-back" in text or "lining" in text:
        return "quilt-lining"
    if "被面" in name or "被套" in name or "quilt-face" in text or "quilt-cover" in text:
        return "quilt-face"
    return category or "text"


def _canonical_component_id(name: str, original_category: str, category: str, raw_id: Any, index: int) -> str:
    text = f"{name} {original_category} {raw_id}".lower()
    if category == "pillowcase":
        return "pillowcase-short" if "短" in name or "short" in text else "pillowcase"
    if "下方小页" in name or "small-panel" in text or "lower" in text:
        return "quilt-face-lower-small-panel"
    if category == "bedsheet":
        return "bedsheet"
    if category == "quilt-lining":
        return "quilt-lining-main"
    if category == "quilt-face":
        return "quilt-face-main"
    return _slug(str(raw_id or name)) or f"component-{index}"


def _canonical_part_id_from_row(row: dict[str, Any]) -> str:
    name = str(row.get("partName") or row.get("partId") or "")
    category = _canonical_category(name, str(row.get("category") or row.get("partId") or ""))
    return _canonical_component_id(name, str(row.get("partId") or ""), category, row.get("partId"), 1)


def _sku_values(text: str) -> list[str]:
    seen = set()
    values = []
    for match in re.findall(r"(?<!\d)\d{8,12}(?!\d)", text):
        if match not in seen:
            seen.add(match)
            values.append(match)
    return values


def _variant_sort_key(variant: dict[str, Any]) -> tuple[int, str]:
    text = _json_text(variant).replace("×", "x").replace("*", "x")
    if "200x230" in text or "3855" in text or "3857" in text or "standard" in text.lower() or "标准" in text:
        return (10, str(variant.get("id")))
    if "248x248" in text or "3856" in text or "3858" in text or "加大" in text:
        return (20, str(variant.get("id")))
    return (100, str(variant.get("id")))


def _dedupe_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for component in components:
        component_id = str(component.get("id") or "")
        if not component_id:
            continue
        if component_id not in deduped:
            deduped[component_id] = component
            continue
        deduped[component_id] = _merge_component(deduped[component_id], component)
    return list(deduped.values())


def _merge_component(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key in ("quantity", "shape", "display", "dimensions"):
        if not merged.get(key) and right.get(key):
            merged[key] = right[key]
    if isinstance(left.get("annotations"), list) or isinstance(right.get("annotations"), list):
        merged["annotations"] = list(left.get("annotations") or []) + list(right.get("annotations") or [])
    if len(str(right.get("name") or "")) > len(str(left.get("name") or "")):
        merged["name"] = right["name"]
    return merged


def _ensure_core_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(component.get("id")): component for component in components if component.get("id") in CORE_COMPONENT_IDS}
    return [by_id.get(component_id) or _placeholder_component(component_id, name, category) for component_id, name, category in CORE_COMPONENTS]


def _placeholder_component(component_id: str, name: str, category: str) -> dict[str, Any]:
    return {
        "id": component_id,
        "name": name,
        "category": category,
        "quantity": {},
        "shape": {},
        "display": {},
        "annotations": [
            {
                "kind": "note",
                "text": "AI输出缺少该核心裁片，已由后置规范化补齐占位，尺寸需复核。",
                "placement": "below",
            }
        ],
        "dimensions": {},
    }


def _dedupe_size_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("variantId") or ""), str(row.get("partId") or ""))
        if key not in deduped:
            deduped[key] = row
            continue
        deduped[key] = _merge_size_row(deduped[key], row)
    return list(deduped.values())


def _merge_size_row(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if not merged.get(key) and value:
            merged[key] = value
    return merged


def _ensure_core_size_rows(rows: list[dict[str, Any]], known_variant_ids: set[str]) -> list[dict[str, Any]]:
    by_key = {(str(row.get("variantId") or ""), str(row.get("partId") or "")): row for row in rows}
    for variant_id in known_variant_ids:
        for component_id, name, _category in CORE_COMPONENTS:
            key = (variant_id, component_id)
            if key not in by_key:
                by_key[key] = {"variantId": variant_id, "partId": component_id, "partName": name}
    return list(by_key.values())


def _is_known_windsor_variant(variant_id: str, text: str) -> bool:
    normalized_text = text.replace("×", "x").replace("*", "x")
    return (
        variant_id in KNOWN_WINDSOR_VARIANT_IDS
        or "1010103855" in text
        or "1010103856" in text
        or "1010103857" in text
        or "1010103858" in text
        or "200x230" in normalized_text
        or "248x248" in normalized_text
    )


def _number_or_large(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10_000


def _json_text(value: Any) -> str:
    return str(value) if isinstance(value, str) else __import__("json").dumps(value, ensure_ascii=False)


def _slug(value: str) -> str:
    lowered = value.lower().strip()
    lowered = lowered.replace("×", "x").replace("*", "x")
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-")
