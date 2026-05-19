from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


CODEX_MODEL = os.getenv("CODEX_MODEL", "gpt-5.5")
CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "240"))


class CodexConfigurationError(RuntimeError):
    """Raised when Codex CLI is not available."""


class CodexExecutionError(RuntimeError):
    """Raised when Codex CLI fails or returns invalid JSON."""


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

Runner = Callable[..., subprocess.CompletedProcess[str]]


def generate_layout_via_codex(
    extracted_files: list[dict[str, Any]],
    prompt: str,
    parameters: dict[str, Any],
    *,
    runner: Runner | None = None,
    timeout_seconds: int = CODEX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if runner is None and shutil.which("codex") is None:
        raise CodexConfigurationError("codex CLI is not installed or not on PATH")

    with tempfile.TemporaryDirectory(prefix="flower-codex-") as workdir:
        workdir_path = Path(workdir)
        inputs_dir = workdir_path / "inputs"
        inputs_dir.mkdir()

        manifest = _write_inputs(inputs_dir, extracted_files)
        (workdir_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (workdir_path / "parameters.json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2), encoding="utf-8")
        (workdir_path / "extracted_text.md").write_text(_extracted_text_markdown(extracted_files), encoding="utf-8")

        output_path = workdir_path / "codex_output.json"
        prompt_path = workdir_path / "prompt.md"
        prompt_path.write_text(_codex_prompt(prompt, parameters, manifest), encoding="utf-8")

        command = _codex_command(workdir_path, output_path, prompt_path, manifest)
        completed = _run(command, workdir_path, timeout_seconds, runner)
        if completed.returncode != 0:
            raise CodexExecutionError(_failure_message(completed))
        if not output_path.exists():
            raise CodexExecutionError("Codex did not write an output JSON file")

        payload = _loads_codex_json(output_path.read_text(encoding="utf-8"))
        _validate_payload(payload)
        return payload


def _codex_command(
    workdir: Path,
    output_path: Path,
    prompt_path: Path,
    manifest: list[dict[str, Any]],
) -> list[str]:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--skip-git-repo-check",
        "--cd",
        str(workdir),
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-last-message",
        str(output_path),
        "--model",
        CODEX_MODEL,
    ]
    for item in manifest:
        if item.get("kind") == "image":
            command.extend(["--image", item["path"]])
    command.append(prompt_path.read_text(encoding="utf-8"))
    return command


def _run(command: list[str], cwd: Path, timeout_seconds: int, runner: Runner | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Force Codex to use its local ChatGPT/Codex auth instead of an API key inherited from .env.
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_BASE_URL", None)
    active_runner = runner or subprocess.run
    return active_runner(
        command,
        cwd=str(cwd),
        timeout=timeout_seconds,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_inputs(inputs_dir: Path, extracted_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = []
    for index, item in enumerate(extracted_files, start=1):
        filename = _safe_filename(str(item.get("filename") or f"upload-{index}"))
        path = inputs_dir / filename
        content = item.get("content")
        if isinstance(content, (bytes, bytearray)):
            path.write_bytes(bytes(content))
        else:
            path.write_text(str(item.get("text") or ""), encoding="utf-8")
        manifest.append(
            {
                "filename": item.get("filename") or filename,
                "storedName": filename,
                "path": str(path),
                "kind": item.get("kind") or "file",
                "contentType": item.get("contentType"),
                "size": path.stat().st_size,
                "textLength": len(str(item.get("text") or "")),
            }
        )
    return manifest


def _codex_prompt(prompt: str, parameters: dict[str, Any], manifest: list[dict[str, Any]]) -> str:
    return f"""你是床品产品排版图结构化数据专家。

任务：读取当前工作目录中的上传资料，实时分析并输出 CAD 可渲染的 product-layout JSON。

输入文件位置：
- 原始上传文件在 ./inputs/
- 文件清单在 ./manifest.json
- 已提取文本在 ./extracted_text.md
- 用户结构化参数在 ./parameters.json

用户补充说明：
{prompt or "(无)"}

结构化参数：
{json.dumps(parameters, ensure_ascii=False, indent=2)}

文件清单：
{json.dumps(manifest, ensure_ascii=False, indent=2)}

输出硬性要求：
1. 只输出 JSON，不要 Markdown，不要解释文字。
2. 顶层必须包含 layout、validation、sources。
3. layout.schemaVersion 固定为 "1.0.0"。
4. layout.documentType 固定为 "product-layout"。
5. layout.technicalRequirements 必须是数组，每项形如 {{"no": 1, "text": "..."}}。
6. layout.sizeTable 必须是对象，形如 {{"columns": [...], "rows": [...]}}，不要输出数组。
7. layout.variants 必须是数组，每个 variant 必须包含 id、label、layout、components；不要使用 pieces 字段。
8. component 必须包含 id、name、category、quantity、shape、display、annotations、dimensions。
9. 尽量从信息传递表、排版图、图片和用户说明中提取 SKU、品名、花名、规格、A/B 版、裁片、尺寸、标注、图框信息。
10. 不确定的内容不要编造，在 validation.warnings 或 validation.missing 中标出。
11. demo 阶段可以根据用户 prompt/parameters 补充模板、比例、圆角、特殊裁片等信息。

必须遵守这个结构示例，只替换其中的具体内容：
{{
  "layout": {{
    "schemaVersion": "1.0.0",
    "documentType": "product-layout",
    "meta": {{
      "title": "产品排版图",
      "productName": "产品名",
      "scale": "1:50",
      "unit": "cm"
    }},
    "technicalRequirements": [
      {{ "no": 1, "text": "技术要求" }}
    ],
    "sizeTable": {{
      "columns": ["partName", "finishedSize", "cuttingSizeFace", "cuttingSizeBack"],
      "rows": [
        {{
          "variantId": "型号",
          "partId": "裁片ID",
          "partName": "裁片名称",
          "finishedSize": {{ "width": 0, "height": 0 }},
          "cuttingSizeFace": null,
          "cuttingSizeBack": null
        }}
      ]
    }},
    "variants": [
      {{
        "id": "型号",
        "label": "型号",
        "layout": {{ "mode": "flow", "direction": "horizontal", "gap": 25, "wrap": true }},
        "components": [
          {{
            "id": "裁片ID",
            "name": "裁片名称",
            "category": "quilt-face",
            "quantity": {{ "perSet": 1, "unit": "床", "note": "" }},
            "shape": {{ "type": "rectangle", "width": 0, "height": 0 }},
            "display": {{ "showDimensions": true, "dimensionSides": ["width", "height"], "grainDirection": "up" }},
            "annotations": [
              {{ "kind": "label", "text": "裁片名称", "placement": "inside" }}
            ],
            "dimensions": {{
              "finishedSize": {{ "width": 0, "height": 0 }},
              "cuttingSizeFace": null,
              "cuttingSizeBack": null
            }}
          }}
        ]
      }}
    ],
    "titleBlock": {{
      "template": "queen-standard-a3",
      "fields": {{
        "图名": "产品排版图",
        "比例": "1:50",
        "单位": "cm"
      }}
    }}
  }},
  "validation": {{
    "status": "ok",
    "warnings": [],
    "missing": []
  }},
  "sources": [
    {{ "filename": "文件名", "kind": "document", "textLength": 0 }}
  ]
}}
"""


def _extracted_text_markdown(extracted_files: list[dict[str, Any]]) -> str:
    sections = []
    for item in extracted_files:
        filename = item.get("filename") or "upload"
        kind = item.get("kind") or "file"
        text = str(item.get("text") or "").strip()
        if not text:
            text = "(无可提取文本，请结合原始文件或图片分析)"
        sections.append(f"## {filename} [{kind}]\n\n{text[:20000]}")
    return "\n\n".join(sections) if sections else "(未上传文件)"


def _loads_codex_json(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    elif not cleaned.startswith("{"):
        match = re.search(r"(\{.*\})", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(1)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise CodexExecutionError(f"Codex output was not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CodexExecutionError("Codex output JSON must be an object")
    return payload


def _validate_payload(payload: dict[str, Any]) -> None:
    layout = payload.get("layout")
    if not isinstance(layout, dict):
        raise CodexExecutionError("Codex output missing layout object")
    if layout.get("schemaVersion") != "1.0.0":
        raise CodexExecutionError("layout.schemaVersion must be 1.0.0")
    if layout.get("documentType") != "product-layout":
        raise CodexExecutionError("layout.documentType must be product-layout")
    if not isinstance(layout.get("meta"), dict):
        raise CodexExecutionError("layout.meta must be an object")
    if not isinstance(layout.get("technicalRequirements"), list):
        raise CodexExecutionError("layout.technicalRequirements must be an array")
    if not isinstance(layout.get("sizeTable"), dict):
        raise CodexExecutionError("layout.sizeTable must be an object")
    if not isinstance(layout.get("variants"), list):
        raise CodexExecutionError("layout.variants must be an array")
    if not isinstance(layout.get("titleBlock"), dict):
        raise CodexExecutionError("layout.titleBlock must be an object")
    if not isinstance(payload.get("validation"), dict):
        raise CodexExecutionError("Codex output missing validation object")
    if not isinstance(payload.get("sources"), list):
        raise CodexExecutionError("Codex output missing sources array")


def _failure_message(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    detail = stderr or stdout or f"exit code {completed.returncode}"
    return f"Codex CLI failed: {detail[-2000:]}"


def _safe_filename(filename: str) -> str:
    basename = Path(filename).name or "upload"
    return re.sub(r"[^A-Za-z0-9._()#\\-\\u4e00-\\u9fff]+", "_", basename)[:160]
