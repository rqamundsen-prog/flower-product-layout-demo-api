from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


CODEX_MODEL = os.getenv("CODEX_MODEL", "auto")
CODEX_TIMEOUT_SECONDS = int(os.getenv("CODEX_TIMEOUT_SECONDS", "600"))
CODEX_BIN = os.getenv("CODEX_BIN", "codex")
VISUAL_OCR_TEXT_THRESHOLD = int(os.getenv("FLOWER_VISUAL_OCR_TEXT_THRESHOLD", "160"))


class CodexConfigurationError(RuntimeError):
    """Raised when Codex CLI is not available."""


class CodexExecutionError(RuntimeError):
    """Raised when Codex CLI fails or returns invalid JSON."""


PRODUCT_LAYOUT_RESPONSE_SCHEMA: dict[str, Any] = {
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
    codex_bin = os.getenv("CODEX_BIN", CODEX_BIN)
    if runner is None and shutil.which(codex_bin) is None:
        raise CodexConfigurationError(f"codex CLI is not installed or not executable: {codex_bin}")

    with tempfile.TemporaryDirectory(prefix="flower-codex-") as workdir:
        workdir_path = Path(workdir)
        inputs_dir = workdir_path / "inputs"
        inputs_dir.mkdir()

        manifest = _write_inputs(inputs_dir, extracted_files)
        extracted_text = _extracted_text_markdown(extracted_files)
        (workdir_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (workdir_path / "parameters.json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2), encoding="utf-8")
        (workdir_path / "extracted_text.md").write_text(extracted_text, encoding="utf-8")

        output_path = workdir_path / "codex_output.json"
        prompt_path = workdir_path / "prompt.md"
        attached_images = _attached_image_paths(manifest)
        if attached_images:
            visual_evidence_path = workdir_path / "visual_evidence.json"
            visual_prompt_path = workdir_path / "visual_prompt.md"
            visual_prompt_path.write_text(
                _visual_evidence_prompt(prompt, parameters, manifest, extracted_text),
                encoding="utf-8",
            )
            visual_command = _codex_command(workdir_path, visual_evidence_path, visual_prompt_path, manifest, codex_bin)
            completed = _run(visual_command, workdir_path, timeout_seconds, runner)
            if completed.returncode != 0:
                raise CodexExecutionError(_failure_message(completed))
            if not visual_evidence_path.exists():
                raise CodexExecutionError("Codex did not write visual evidence JSON")
            visual_evidence = _loads_codex_json(visual_evidence_path.read_text(encoding="utf-8"))
            enriched_text = _with_visual_evidence(extracted_text, visual_evidence)
            prompt_path.write_text(
                _visual_facts_prompt(prompt, parameters, manifest, enriched_text),
                encoding="utf-8",
            )
            command = _codex_command(workdir_path, output_path, prompt_path, [], codex_bin)
            completed = _run(command, workdir_path, timeout_seconds, runner)
            if completed.returncode != 0:
                raise CodexExecutionError(_failure_message(completed))
            if not output_path.exists():
                raise CodexExecutionError("Codex did not write an output JSON file")
            response = _loads_codex_json(output_path.read_text(encoding="utf-8"))
            payload = _layout_from_visual_response(response, prompt, parameters, manifest)
            _validate_payload(payload)
            return payload

        if _has_visual_ocr_text(manifest):
            prompt_path.write_text(
                _visual_facts_prompt(prompt, parameters, manifest, extracted_text),
                encoding="utf-8",
            )
            command = _codex_command(workdir_path, output_path, prompt_path, manifest, codex_bin)
            completed = _run(command, workdir_path, timeout_seconds, runner)
            if completed.returncode != 0:
                raise CodexExecutionError(_failure_message(completed))
            if not output_path.exists():
                raise CodexExecutionError("Codex did not write an output JSON file")
            response = _loads_codex_json(output_path.read_text(encoding="utf-8"))
            payload = _layout_from_visual_response(response, prompt, parameters, manifest)
            _validate_payload(payload)
            return payload

        if runner is None and not attached_images:
            prompt_path.write_text(
                _facts_prompt(prompt, parameters, _source_manifest(manifest), _source_text_markdown(extracted_files)),
                encoding="utf-8",
            )
            command = _codex_command(workdir_path, output_path, prompt_path, [], codex_bin)
            completed = _run(command, workdir_path, timeout_seconds, runner)
            if completed.returncode != 0:
                raise CodexExecutionError(_failure_message(completed))
            if not output_path.exists():
                raise CodexExecutionError("Codex did not write an output JSON file")
            facts = _loads_codex_json(output_path.read_text(encoding="utf-8"))
            payload = _layout_from_facts(facts, prompt, parameters, manifest)
            _validate_payload(payload)
            return payload

        prompt_path.write_text(_codex_prompt(prompt, parameters, manifest, extracted_text), encoding="utf-8")

        command = _codex_command(workdir_path, output_path, prompt_path, manifest, codex_bin)
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
    codex_bin: str = CODEX_BIN,
) -> list[str]:
    attached_images = _attached_image_paths(manifest)
    command = [
        codex_bin,
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
        _select_model(attached_images),
    ]
    for image_path in attached_images:
        command.extend(["--image", image_path])
    # `--image <FILE>...` is variadic in Codex CLI, so `--` is required before
    # the prompt or the prompt can be consumed as another image path.
    command.extend(["--", prompt_path.read_text(encoding="utf-8")])
    return command


def _attached_image_paths(manifest: list[dict[str, Any]]) -> list[str]:
    return [
        str(item["path"])
        for item in manifest
        if item.get("kind") == "image" and _should_attach_image(item, manifest)
    ]


def _has_visual_ocr_text(manifest: list[dict[str, Any]]) -> bool:
    return any(
        item.get("kind") == "image" and int(item.get("ocrTextLength") or 0) >= VISUAL_OCR_TEXT_THRESHOLD
        for item in manifest
    )


def _select_model(attached_images: list[str]) -> str:
    configured_model = os.getenv("CODEX_MODEL", CODEX_MODEL)
    if configured_model and configured_model != "auto":
        return configured_model
    return "gpt-5.4-mini" if attached_images else "gpt-5.3-codex-spark"


def _run(command: list[str], cwd: Path, timeout_seconds: int, runner: Runner | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Force Codex to use its local ChatGPT/Codex auth instead of an API key inherited from .env.
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_BASE_URL", None)
    active_runner = runner or subprocess.run
    try:
        return active_runner(
            command,
            cwd=str(cwd),
            timeout=timeout_seconds,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CodexExecutionError(f"Codex CLI timed out after {timeout_seconds} seconds") from exc


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
        entry = {
            "filename": item.get("filename") or filename,
            "storedName": filename,
            "path": str(path),
            "kind": item.get("kind") or "file",
            "contentType": item.get("contentType"),
            "size": path.stat().st_size,
            "textLength": len(str(item.get("text") or "")),
        }
        if item.get("derivedFrom"):
            entry["derivedFrom"] = item["derivedFrom"]
        if item.get("sourcePage"):
            entry["sourcePage"] = item["sourcePage"]
        ocr_text = str(item.get("ocrText") or _ocr_text_from_visual_text(str(item.get("text") or ""))).strip()
        if ocr_text:
            entry["ocrTextLength"] = len(ocr_text)
        manifest.append(entry)
    return manifest


def _should_attach_image(item: dict[str, Any], manifest: list[dict[str, Any]]) -> bool:
    derived_from = str(item.get("derivedFrom") or "")
    if not derived_from:
        return True

    suffix = Path(derived_from).suffix.lower()
    if suffix == ".pdf":
        return True

    if suffix in {".doc", ".docx"}:
        source_text_length = next(
            (
                int(source.get("textLength") or 0)
                for source in manifest
                if source.get("filename") == derived_from and source.get("kind") == "document"
            ),
            0,
        )
        return source_text_length < 200

    return True


def _codex_prompt(
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
    extracted_text: str,
) -> str:
    return f"""你是床品产品排版图结构化数据专家。

任务：读取当前工作目录中的上传资料，实时分析并输出 CAD/PDF 可渲染的 product-layout JSON。

输入文件位置：
- 原始上传文件在 ./inputs/
- 文件清单在 ./manifest.json
- 已提取文本在 ./extracted_text.md
- 用户结构化参数在 ./parameters.json

处理约束：
- 优先使用 extracted_text.md 和通过 --image 提供的页面/截图图片。
- 对 .doc/.docx/.pdf 这类原始二进制文件，不要自行尝试破解或长时间转换；如果文本不可提取，就直接依据已渲染页面图片和用户说明分析。
- 如果文件清单里某个原始文件很大，只把它作为来源名称和附件证据，不要反复读取二进制内容。
- 不要调用 shell，不要遍历目录，不要再转换文件；当前消息已经包含可用文本，图片也已作为视觉输入附加。
- 直接推理并输出最终 JSON。

用户补充说明：
{prompt or "(无)"}

结构化参数：
{json.dumps(parameters, ensure_ascii=False, indent=2)}

文件清单：
{json.dumps(manifest, ensure_ascii=False, indent=2)}

已提取文本内容：
{extracted_text[:60000]}

分析 Skill：
{_product_layout_skill_text()}

输出硬性要求：
1. 只输出 JSON，不要 Markdown，不要解释文字。
2. 顶层必须直接包含 schemaVersion、documentType、meta、technicalRequirements、sizeTable、variants、titleBlock。
3. 不要把结果包在 layout、data、result、response 等外层字段里。
4. schemaVersion 固定为 "1.0.0"。
5. documentType 固定为 "product-layout"。
6. technicalRequirements 必须是数组，每项形如 {{"no": 1, "text": "..."}}。
7. sizeTable 必须是对象，形如 {{"columns": [...], "rows": [...]}}，不要输出数组。
8. variants 必须是数组，每个 variant 必须包含 id、label、layout、components；不要使用 pieces 字段。
9. component 必须包含 id、name、category、quantity、shape、display、annotations、dimensions。
10. 尽量从信息传递表、排版图、图片和用户说明中提取 SKU、品名、花名、规格、A/B 版、裁片、尺寸、标注、图框信息。
11. 不确定的内容不要编造，在 meta.notes 或 titleBlock.fields["未确定项"] 中用字符串数组或文本标出。
12. demo 阶段可以根据用户 prompt/parameters 补充模板、比例、圆角、特殊裁片等信息。

必须遵守这个结构示例，只替换其中的具体内容：
{{
  "schemaVersion": "1.0.0",
  "documentType": "product-layout",
  "meta": {{
    "title": "产品排版图",
    "productName": "产品名",
    "scale": "1:50",
    "unit": "cm",
    "drawingNo": "",
    "page": "1/1",
    "notes": []
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
          "partCode": "",
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
      "单位": "cm",
      "未确定项": []
    }}
  }}
}}
"""


def _product_layout_skill_text() -> str:
    skill_path = Path(__file__).parent / "ai_skills" / "product_layout.md"
    return skill_path.read_text(encoding="utf-8")


def _facts_prompt(prompt: str, parameters: dict[str, Any], manifest: list[dict[str, Any]], extracted_text: str) -> str:
    return f"""你是床品资料结构化抽取助手。只做事实抽取，不生成完整 CAD schema。

只返回 JSON，不要 Markdown，不要解释文字。
字段：
- productName: 品名
- flowerName: 花名
- style: 风格
- fabric: 面料
- materialCodes: A版/B版/C版等编码对象
- yarnDensity: 纱支密度对象或字符串
- fabricWidth: 幅宽，优先数字 cm
- releaseDate: 上市/推广日期
- orderDate: 下单日期
- designer: 设计师
- batchQuantity: 首批量
- notes: 不确定项数组

用户补充说明：
{prompt or "(无)"}

结构化参数：
{json.dumps(parameters, ensure_ascii=False, indent=2)}

文件清单：
{json.dumps(manifest, ensure_ascii=False, indent=2)}

已提取文本：
{extracted_text[:20000]}
"""


def _visual_evidence_prompt(
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
    extracted_text: str,
) -> str:
    return f"""你在执行多模态视觉校验。必须看随命令附加的图片，OCR 文本只做辅助。

任务：从图片里快速确认图纸事实，不要生成完整结构，不要输出 product-layout。

只返回 JSON 对象：
{{
  "imageChecks": [
    {{
      "sourcePage": 1,
      "title": "图中标题",
      "visibleSkus": ["图中可见型号"],
      "visiblePartNames": ["图中可见裁片名"],
      "visibleDimensions": ["图中可见尺寸"],
      "visualNotes": ["图片证据或疑点"]
    }}
  ]
}}

用户补充说明：{prompt or "(无)"}

文件清单：
{json.dumps(_source_manifest_for_visual_facts(manifest), ensure_ascii=False, indent=2)}

OCR/文本摘要：
{extracted_text[:5000]}
"""


def _with_visual_evidence(extracted_text: str, visual_evidence: dict[str, Any]) -> str:
    return (
        f"{extracted_text[:12000]}\n\n"
        "## 多模态视觉校验结果\n\n"
        f"{json.dumps(visual_evidence, ensure_ascii=False, indent=2)}"
    )


def _visual_facts_prompt(
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
    extracted_text: str,
) -> str:
    return f"""你是床品 CAD/PDF 排版图视觉信息抽取助手。只做视觉事实抽取，不要生成完整 product-layout schema。

目标：逐页查看随命令附加的图片，结合已提取文本和用户补充说明，抽取能支撑后端生成 CAD/PDF JSON 的事实。

处理约束：
- 重点看排版图图片中的标题栏、型号、品名、花名、颜色、A/B版编码、面料幅宽、裁片名称、尺寸线、数量、技术要求。
- 不要调用 shell，不要读取或转换原始 PDF/Office 二进制文件。
- 不确定的内容写入 notes，不要用历史样例硬补。
- 输出尽量短，裁片按图面可见信息抽取；不要重复解释。
- 不要生成完整 product-layout schema；后端会把事实包装成最终结构。

用户补充说明：
{prompt or "(无)"}

结构化参数：
{json.dumps(parameters, ensure_ascii=False, indent=2)}

文件清单：
{json.dumps(_source_manifest_for_visual_facts(manifest), ensure_ascii=False, indent=2)}

已提取文本：
{extracted_text[:12000]}

领域规则摘要：
- 排版图图片是最高优先级来源；OCR 文本只做辅助，冲突时以图面为准。
- 重点抽取标题栏、型号、颜色、A/B 版编码、面料幅宽、裁片名、尺寸线、数量、技术要求。
- 尺寸必须区分成品尺寸、下裁尺寸（面）、下裁尺寸（里）。
- 不确定的字段写入 notes，不要用历史样例补齐。
- variant.id 优先使用图面真实型号，面料编码放入 partCode 或 materialCodes。

只返回 JSON 对象，推荐字段：
{{
  "meta": {{
    "title": "图名",
    "productName": "品名",
    "flowerName": "花名",
    "style": "风格",
    "scale": "比例",
    "unit": "单位",
    "fabric": "面料",
    "yarnDensity": "纱支密度",
    "fabricWidth": 250,
    "promotionDate": "推广时间",
    "notes": ["不确定项"]
  }},
  "technicalRequirements": ["技术要求"],
  "titleBlockFields": {{"图名": "产品排版图"}},
  "variants": [
    {{
      "id": "型号",
      "label": "型号/颜色/规格",
      "color": "颜色",
      "materialCodes": {{"A版": "编码", "B版": "编码"}},
      "layout": {{"mode": "fabric-roll", "direction": "horizontal", "fabricWidth": 250, "scale": "1:50"}},
      "components": [
        {{
          "id": "裁片ID",
          "partCode": "面料编码",
          "name": "裁片名称",
          "category": "quilt-face|quilt-lining|bedsheet|pillowcase|text",
          "quantity": {{"perSet": 1, "unit": "页", "note": "图面标注"}},
          "shape": {{"type": "rectangle", "width": 204, "height": 234}},
          "display": {{"showDimensions": true, "dimensionSides": ["width", "height"], "grainDirection": "up"}},
          "annotations": [{{"kind": "label", "text": "图面文字", "placement": "inside"}}],
          "dimensions": {{"finishedSize": {{"width": 200, "height": 230}}, "cuttingSizeFace": null, "cuttingSizeBack": null}}
        }}
      ]
    }}
  ],
  "sizeRows": [
    {{"variantId": "型号", "partId": "裁片ID", "partName": "裁片名称", "note": "来源说明"}}
  ],
  "notes": ["整体不确定项"]
}}
"""


def _source_manifest_for_visual_facts(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for item in manifest:
        entry = {
            key: item.get(key)
            for key in ("filename", "kind", "contentType", "size", "textLength", "derivedFrom", "sourcePage")
            if key in item
        }
        compact.append(entry)
    return compact


def _layout_from_visual_response(
    response: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    if _is_product_layout_payload(response):
        return response
    return _layout_from_visual_facts(response, prompt, parameters, manifest)


def _is_product_layout_payload(value: dict[str, Any]) -> bool:
    return value.get("schemaVersion") == "1.0.0" and value.get("documentType") == "product-layout"


def _layout_from_visual_facts(
    facts: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_meta = facts.get("meta") if isinstance(facts.get("meta"), dict) else {}
    meta = dict(raw_meta)
    meta["title"] = _first_text(meta.get("title") or facts.get("title"), "产品排版图")
    meta["productName"] = _first_text(meta.get("productName") or facts.get("productName"), "")
    meta["flowerName"] = _first_text(meta.get("flowerName") or facts.get("flowerName"), "")
    meta["style"] = _first_text(meta.get("style") or facts.get("style") or parameters.get("style"), "QUEEN")
    meta["scale"] = _first_text(parameters.get("scale") or meta.get("scale"), "1:50")
    meta["unit"] = _first_text(parameters.get("unit") or meta.get("unit"), "cm")
    meta["sourceFiles"] = [str(item.get("filename")) for item in manifest if item.get("kind") != "image"]

    visual_notes = _notes_from_unknown(meta.get("notes")) + _notes_from_unknown(facts.get("notes"))
    if prompt:
        visual_notes.append(f"用户补充说明：{prompt}")
    meta["notes"] = _dedupe_strings(visual_notes)

    variants = _visual_variants(facts, parameters, meta)
    size_table = _visual_size_table(facts, variants)
    title_block_fields = _visual_title_block_fields(facts, meta)

    return {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": meta,
        "technicalRequirements": _visual_technical_requirements(facts.get("technicalRequirements")),
        "sizeTable": size_table,
        "variants": variants,
        "titleBlock": {
            "template": _first_text(parameters.get("template"), "queen-standard-a3"),
            "fields": title_block_fields,
        },
    }


def _visual_variants(facts: dict[str, Any], parameters: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    raw_variants = facts.get("variants") if isinstance(facts.get("variants"), list) else []
    if not raw_variants and isinstance(facts.get("components"), list):
        raw_variants = [{"id": "default", "label": meta.get("flowerName") or meta.get("productName") or "default", "components": facts["components"]}]

    variants = []
    for index, item in enumerate(raw_variants, start=1):
        if not isinstance(item, dict):
            continue
        variant_id = _first_text(item.get("id") or item.get("variantId"), f"variant-{index}")
        components = [
            _visual_component(component, component_index)
            for component_index, component in enumerate(item.get("components") if isinstance(item.get("components"), list) else [], start=1)
            if isinstance(component, dict)
        ]
        variants.append(
            {
                **item,
                "id": variant_id,
                "label": _first_text(item.get("label"), variant_id),
                "layout": _visual_layout(item.get("layout"), parameters, meta),
                "components": components,
            }
        )

    if variants:
        return variants

    return [
        {
            "id": "default",
            "label": meta.get("flowerName") or meta.get("productName") or "default",
            "layout": _visual_layout({}, parameters, meta),
            "components": [],
        }
    ]


def _visual_layout(value: Any, parameters: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    layout = dict(value) if isinstance(value, dict) else {}
    layout.setdefault("mode", "fabric-roll")
    layout.setdefault("direction", "horizontal")
    if "fabricWidth" not in layout and meta.get("fabricWidth") is not None:
        layout["fabricWidth"] = meta.get("fabricWidth")
    layout.setdefault("gap", 25)
    layout.setdefault("wrap", True)
    layout.setdefault("scale", _first_text(parameters.get("scale") or meta.get("scale"), "1:50"))
    return layout


def _visual_component(component: dict[str, Any], index: int) -> dict[str, Any]:
    name = _first_text(component.get("name") or component.get("partName") or component.get("id"), f"裁片{index}")
    component_id = _first_text(component.get("id") or component.get("partId"), f"component-{index}")
    return {
        **component,
        "id": component_id,
        "name": name,
        "category": _first_text(component.get("category"), "text"),
        "quantity": component.get("quantity") if isinstance(component.get("quantity"), dict) else {},
        "shape": component.get("shape") if isinstance(component.get("shape"), dict) else {},
        "display": component.get("display") if isinstance(component.get("display"), dict) else {},
        "annotations": component.get("annotations") if isinstance(component.get("annotations"), list) else [],
        "dimensions": component.get("dimensions") if isinstance(component.get("dimensions"), dict) else {},
    }


def _visual_size_table(facts: dict[str, Any], variants: list[dict[str, Any]]) -> dict[str, Any]:
    table = facts.get("sizeTable") if isinstance(facts.get("sizeTable"), dict) else {}
    raw_rows = table.get("rows") if isinstance(table.get("rows"), list) else facts.get("sizeRows")
    rows = [dict(row) for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    if not rows:
        rows = [
            _size_row_from_component(variant, component)
            for variant in variants
            for component in variant.get("components", [])
            if isinstance(component, dict)
        ]
    return {
        "columns": list(table.get("columns") or [
            "variantId",
            "partId",
            "partName",
            "finishedSize",
            "cuttingSizeFace",
            "cuttingSizeBack",
            "quantity",
            "note",
        ]),
        "rows": rows,
    }


def _size_row_from_component(variant: dict[str, Any], component: dict[str, Any]) -> dict[str, Any]:
    dimensions = component.get("dimensions") if isinstance(component.get("dimensions"), dict) else {}
    return {
        "variantId": variant.get("id"),
        "partId": component.get("id"),
        "partName": component.get("name"),
        "finishedSize": dimensions.get("finishedSize"),
        "cuttingSizeFace": dimensions.get("cuttingSizeFace"),
        "cuttingSizeBack": dimensions.get("cuttingSizeBack"),
        "quantity": component.get("quantity"),
        "note": "",
    }


def _visual_technical_requirements(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    requirements = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            text = _first_text(item.get("text"), "")
            number = item.get("no") or index
        else:
            text = _first_text(item, "")
            number = index
        if text:
            requirements.append({"no": number, "text": text})
    return requirements


def _visual_title_block_fields(facts: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    fields = facts.get("titleBlockFields")
    if not isinstance(fields, dict):
        title_block = facts.get("titleBlock") if isinstance(facts.get("titleBlock"), dict) else {}
        fields = title_block.get("fields") if isinstance(title_block.get("fields"), dict) else {}
    normalized = dict(fields)
    normalized.setdefault("图名", meta.get("title") or "产品排版图")
    normalized.setdefault("品名", meta.get("productName") or "")
    normalized.setdefault("花名", meta.get("flowerName") or "")
    normalized.setdefault("风格", meta.get("style") or "")
    normalized.setdefault("比例", meta.get("scale") or "1:50")
    normalized.setdefault("单位", meta.get("unit") or "cm")
    normalized.setdefault("未确定项", meta.get("notes") or [])
    return normalized


def _notes_from_unknown(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = _first_text(value, "")
    return [text] if text else []


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _source_manifest(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: item.get(key) for key in ("filename", "kind", "contentType", "size", "textLength") if key in item}
        for item in manifest
        if item.get("kind") != "image"
    ]


def _source_text_markdown(extracted_files: list[dict[str, Any]]) -> str:
    sections = []
    for item in extracted_files:
        if item.get("kind") == "image" and not _has_useful_image_text(item):
            continue
        filename = item.get("filename") or "upload"
        kind = item.get("kind") or "file"
        text = str(item.get("text") or "").strip()
        if text:
            sections.append(f"## {filename} [{kind}]\n\n{text[:12000]}")
    return "\n\n".join(sections) if sections else "(未提取到文字)"


def _has_useful_image_text(item: dict[str, Any]) -> bool:
    if str(item.get("ocrText") or "").strip():
        return True
    return bool(_ocr_text_from_visual_text(str(item.get("text") or "")))


def _ocr_text_from_visual_text(text: str) -> str:
    marker = "OCR text:"
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].strip()


def _layout_from_facts(
    facts: dict[str, Any],
    prompt: str,
    parameters: dict[str, Any],
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    product_name = _first_text(facts.get("productName"), "产品名未确定")
    flower_name = _first_text(facts.get("flowerName"), "")
    style = _first_text(facts.get("style"), parameters.get("style") or "QUEEN")
    fabric = _first_text(facts.get("fabric"), "")
    fabric_width = _fabric_width_value(facts.get("fabricWidth"))
    scale = _first_text(parameters.get("scale"), "1:50")
    unit = _first_text(parameters.get("unit"), "cm")
    material_codes = facts.get("materialCodes") if isinstance(facts.get("materialCodes"), dict) else {}
    source_files = [str(item.get("filename")) for item in manifest if item.get("kind") != "image"]
    notes = _notes_from_facts(facts)
    notes.append("当前请求未附可直接识别的 PDF/CAD 排版图图片，裁片尺寸和版面坐标需下游或技术员复核。")
    if prompt:
        notes.append(f"用户补充说明：{prompt}")

    variants = []
    for version, code in material_codes.items():
        code_text = str(code)
        variants.append(
            {
                "id": code_text,
                "label": f"{flower_name or product_name}{version}",
                "materialCodes": {str(version): code_text},
                "layout": {
                    "mode": "flow",
                    "direction": "horizontal",
                    "fabricWidth": fabric_width,
                    "gap": 25,
                    "wrap": True,
                    "scale": scale,
                },
                "components": [
                    {
                        "id": f"material-panel-{_safe_component_id(version)}",
                        "partCode": code_text,
                        "name": f"{version}面料信息",
                        "category": "fabric-panel",
                        "quantity": {"perSet": 1, "unit": "项", "note": "AI从配置表抽取，非最终裁片"},
                        "shape": {"type": "rectangle"},
                        "display": {"showDimensions": False, "dimensionSides": [], "grainDirection": "up"},
                        "annotations": [
                            {"kind": "label", "text": f"{version}：{code_text}", "placement": "inside"},
                            {"kind": "note", "text": "缺少排版图裁片尺寸，需复核", "placement": "below"},
                        ],
                        "dimensions": {},
                    }
                ],
            }
        )
    if not variants:
        variants.append(
            {
                "id": "default",
                "label": flower_name or product_name,
                "layout": {"mode": "flow", "direction": "horizontal", "fabricWidth": fabric_width, "gap": 25, "wrap": True, "scale": scale},
                "components": [],
            }
        )

    rows = [
        {
            "variantId": variant["id"],
            "partId": component["id"],
            "partName": component["name"],
            "finishedSize": None,
            "cuttingSizeFace": None,
            "cuttingSizeBack": None,
            "quantity": component["quantity"],
            "note": "配置表仅提供基础资料，未提供最终裁片尺寸。",
        }
        for variant in variants
        for component in variant.get("components", [])
    ]

    return {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {
            "title": f"{product_name}{flower_name}产品排版图" if flower_name else f"{product_name}产品排版图",
            "productName": product_name,
            "flowerName": flower_name,
            "style": style,
            "scale": scale,
            "unit": unit,
            "fabric": fabric,
            "yarnDensity": facts.get("yarnDensity") or "",
            "fabricWidth": fabric_width,
            "promotionDate": _first_text(facts.get("releaseDate"), ""),
            "sourceFiles": source_files,
            "notes": notes,
        },
        "technicalRequirements": [
            {"no": 1, "text": "AI已从上传配置表抽取基础资料。"},
            {"no": 2, "text": "缺少明确排版图裁片尺寸时，输出为可渲染占位结构，需结合PDF/CAD复核。"},
        ],
        "sizeTable": {
            "columns": ["variantId", "partId", "partName", "finishedSize", "cuttingSizeFace", "cuttingSizeBack", "quantity", "note"],
            "rows": rows,
        },
        "variants": variants,
        "titleBlock": {
            "template": _first_text(parameters.get("template"), "queen-standard-a3"),
            "fields": {
                "图名": "产品排版图",
                "品名": product_name,
                "花名": flower_name,
                "风格": style,
                "面料": fabric,
                "花号": material_codes,
                "纱支密度": facts.get("yarnDensity") or "",
                "幅宽": f"{fabric_width}cm" if isinstance(fabric_width, (int, float)) else fabric_width,
                "比例": scale,
                "单位": unit,
                "推广时间": _first_text(facts.get("releaseDate"), ""),
                "下单时间": _first_text(facts.get("orderDate"), ""),
                "设计师": _first_text(facts.get("designer"), ""),
                "首批量": _first_text(facts.get("batchQuantity"), ""),
                "未确定项": notes,
            },
        },
    }


def _first_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return fallback
    text = str(value).strip()
    return text or fallback


def _fabric_width_value(value: Any) -> Any:
    if isinstance(value, dict):
        for item in value.values():
            parsed = _fabric_width_value(item)
            if parsed:
                return parsed
        return None
    text = _first_text(value, "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*cm", text, flags=re.IGNORECASE)
    if match:
        number = float(match.group(1))
        return int(number) if number.is_integer() else number
    return text or None


def _notes_from_facts(facts: dict[str, Any]) -> list[str]:
    raw_notes = facts.get("notes")
    if isinstance(raw_notes, list):
        return [str(note) for note in raw_notes if str(note).strip()]
    if raw_notes:
        return [str(raw_notes)]
    return []


def _safe_component_id(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9\-_]+", "-", str(value)).strip("-")
    return text.lower() or "part"


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
    if "layout" in payload:
        raise CodexExecutionError("Codex output must not wrap the docx schema in a layout object")
    if payload.get("schemaVersion") != "1.0.0":
        raise CodexExecutionError("schemaVersion must be 1.0.0")
    if payload.get("documentType") != "product-layout":
        raise CodexExecutionError("documentType must be product-layout")
    if not isinstance(payload.get("meta"), dict):
        raise CodexExecutionError("meta must be an object")
    if not isinstance(payload.get("technicalRequirements"), list):
        raise CodexExecutionError("technicalRequirements must be an array")
    if not isinstance(payload.get("sizeTable"), dict):
        raise CodexExecutionError("sizeTable must be an object")
    if not isinstance(payload.get("variants"), list):
        raise CodexExecutionError("variants must be an array")
    if not isinstance(payload.get("titleBlock"), dict):
        raise CodexExecutionError("titleBlock must be an object")


def _failure_message(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    detail = stderr or stdout or f"exit code {completed.returncode}"
    return f"Codex CLI failed: {detail[-2000:]}"


def _safe_filename(filename: str) -> str:
    basename = Path(filename).name or "upload"
    return re.sub(r"[^A-Za-z0-9._()#\\-\\u4e00-\\u9fff]+", "_", basename)[:160]
