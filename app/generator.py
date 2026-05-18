from __future__ import annotations

import base64
import json
import mimetypes
import os
from typing import Any


DEFAULT_MODEL = "gpt-4.1-mini"
MAX_INLINE_FILE_BYTES = 15 * 1024 * 1024


class AIConfigurationError(RuntimeError):
    """Raised when the AI provider is not configured."""


class AIGenerationError(RuntimeError):
    """Raised when the AI provider returns an invalid response."""


PRODUCT_LAYOUT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["layout", "validation", "sources"],
    "additionalProperties": False,
    "properties": {
        "layout": {
            "type": "object",
            "required": [
                "schemaVersion",
                "documentType",
                "meta",
                "technicalRequirements",
                "sizeTable",
                "variants",
                "titleBlock",
            ],
            "additionalProperties": True,
            "properties": {
                "schemaVersion": {"type": "string"},
                "documentType": {"type": "string"},
                "meta": {"type": "object", "additionalProperties": True},
                "technicalRequirements": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "sizeTable": {"type": "object", "additionalProperties": True},
                "variants": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "titleBlock": {"type": "object", "additionalProperties": True},
            },
        },
        "validation": {
            "type": "object",
            "required": ["status", "warnings", "missing"],
            "additionalProperties": True,
            "properties": {
                "status": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "missing": {"type": "array", "items": {"type": "string"}},
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["filename", "kind", "textLength"],
                "additionalProperties": True,
                "properties": {
                    "filename": {"type": "string"},
                    "kind": {"type": "string"},
                    "textLength": {"type": "integer"},
                },
            },
        },
    },
}


SYSTEM_PROMPT = """你是床品产品排版图结构化数据专家。
你的任务是实时分析用户上传的信息传递表、排版图 PDF/图片、文字提示和结构化参数，输出 CAD 渲染可用的 product-layout JSON。

硬性要求：
1. 必须输出 JSON，不要输出解释性文字。
2. JSON 必须包含 layout、validation、sources 三个顶层字段。
3. layout.schemaVersion 固定为 "1.0.0"。
4. layout.documentType 固定为 "product-layout"。
5. 尽量从上传资料中提取 SKU、品名、花名、规格、A/B 版、裁片、尺寸、标注、图框信息。
6. 如果无法确定规则，不要编造确定性结论；可以在 validation.warnings 或 validation.missing 中标出。
7. demo 阶段允许根据用户 prompt/parameters 补充模板、比例、圆角、特殊裁片等信息。
8. 输出结构应贴合 CAD 渲染：variants 下放 components；components 下放 shape、display、annotations、dimensions。
"""


def generate_layout(
    extracted_files: list[dict[str, Any]],
    prompt: str = "",
    parameters: dict[str, Any] | None = None,
    *,
    client: Any | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Generate product-layout JSON by calling a realtime AI model."""

    parameters = parameters or {}
    ai_client = client or _openai_client()
    selected_model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

    response = ai_client.responses.create(
        model=selected_model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_content(extracted_files, prompt, parameters)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "product_layout_response",
                "strict": False,
                "schema": PRODUCT_LAYOUT_RESPONSE_SCHEMA,
            }
        },
    )
    payload = _parse_response_json(response)
    _validate_ai_payload(payload)
    return payload


def _openai_client() -> Any:
    if not os.getenv("OPENAI_API_KEY"):
        raise AIConfigurationError("OPENAI_API_KEY is required for realtime AI generation")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIConfigurationError("openai package is not installed; run `python -m pip install -r requirements.txt`") from exc
    return OpenAI()


def _build_user_content(
    extracted_files: list[dict[str, Any]],
    prompt: str,
    parameters: dict[str, Any],
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "请根据下面上传资料实时生成 product-layout JSON。\n\n"
                f"用户补充说明：\n{prompt or '(无)'}\n\n"
                f"结构化参数 JSON：\n{json.dumps(parameters, ensure_ascii=False, indent=2)}\n\n"
                "已提取文本资料：\n"
                f"{_combined_extracted_text(extracted_files)}"
            ),
        }
    ]

    for item in extracted_files:
        filename = str(item.get("filename") or "upload")
        kind = str(item.get("kind") or "file")
        content_bytes = item.get("content")
        if not isinstance(content_bytes, (bytes, bytearray)) or len(content_bytes) > MAX_INLINE_FILE_BYTES:
            continue

        mime_type = _mime_type(filename, item.get("contentType"))
        if kind == "image" and mime_type.startswith("image/"):
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{_b64(content_bytes)}",
                }
            )
        elif kind == "pdf" or mime_type == "application/pdf":
            content.append(
                {
                    "type": "input_file",
                    "filename": filename,
                    "file_data": _b64(content_bytes),
                }
            )

    return content


def _combined_extracted_text(extracted_files: list[dict[str, Any]]) -> str:
    blocks = []
    for item in extracted_files:
        filename = item.get("filename") or "upload"
        kind = item.get("kind") or "file"
        text = str(item.get("text") or "").strip()
        if not text:
            text = "(无可提取文本，需结合文件视觉内容分析)"
        blocks.append(f"--- {filename} [{kind}] ---\n{text[:12000]}")
    return "\n\n".join(blocks) if blocks else "(未上传文件)"


def _parse_response_json(response: Any) -> dict[str, Any]:
    text = getattr(response, "output_text", None) or _extract_output_text(response)
    if not text:
        raise AIGenerationError("AI response did not include output_text")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIGenerationError(f"AI response was not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AIGenerationError("AI response JSON must be an object")
    return payload


def _extract_output_text(response: Any) -> str:
    parts: list[str] = []
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    return "".join(parts)


def _validate_ai_payload(payload: dict[str, Any]) -> None:
    layout = payload.get("layout")
    if not isinstance(layout, dict):
        raise AIGenerationError("AI response missing layout object")
    if layout.get("schemaVersion") != "1.0.0":
        raise AIGenerationError("AI response layout.schemaVersion must be 1.0.0")
    if layout.get("documentType") != "product-layout":
        raise AIGenerationError("AI response layout.documentType must be product-layout")
    if not isinstance(payload.get("validation"), dict):
        raise AIGenerationError("AI response missing validation object")
    if not isinstance(payload.get("sources"), list):
        raise AIGenerationError("AI response missing sources array")


def _mime_type(filename: str, content_type: Any) -> str:
    if isinstance(content_type, str) and content_type:
        return content_type
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _b64(content: bytes | bytearray) -> str:
    return base64.b64encode(bytes(content)).decode("ascii")
