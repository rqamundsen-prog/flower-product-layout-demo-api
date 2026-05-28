import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.codex_bridge import CodexExecutionError, generate_layout_via_codex
from app.generator import generate_layout


def _payload(product_name="温莎城堡"):
    return {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {"title": "产品排版图", "productName": product_name, "scale": "1:50", "unit": "cm"},
        "technicalRequirements": [{"no": 1, "text": "Codex分析生成"}],
        "sizeTable": {"columns": ["partName", "finishedSize"], "rows": []},
        "variants": [{"id": "1010103855", "label": "1010103855", "layout": {}, "components": []}],
        "titleBlock": {"template": "queen-standard-a3", "fields": {"图名": "产品排版图"}},
    }


def test_codex_bridge_writes_inputs_and_reads_last_message_json(tmp_path):
    calls = []
    expected = _payload()

    def fake_runner(command, cwd, timeout, env, **kwargs):
        calls.append((command, Path(cwd), timeout, env))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(expected, ensure_ascii=False))
        assert "OPENAI_API_KEY" not in env
        assert (Path(cwd) / "inputs" / "transfer.txt").read_text() == "温莎城堡 1010103855"
        assert (Path(cwd) / "parameters.json").exists()
        return SimpleNamespace(returncode=0, stdout="noisy logs", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "transfer.txt",
                "kind": "document",
                "contentType": "text/plain",
                "text": "温莎城堡 1010103855",
                "content": "温莎城堡 1010103855".encode(),
            }
        ],
        prompt="使用 QUEEN 模板",
        parameters={"template": "queen-standard-a3"},
        runner=fake_runner,
        timeout_seconds=12,
    )

    assert result == expected
    command = calls[0][0]
    assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--skip-git-repo-check" in command
    assert "--output-last-message" in command
    assert calls[0][2] == 12


def test_codex_bridge_uses_configured_absolute_codex_binary(monkeypatch):
    calls = []
    expected = _payload("绝对路径")
    codex_bin = "/Applications/Codex.app/Contents/Resources/codex"
    monkeypatch.setenv("CODEX_BIN", codex_bin)

    def fake_runner(command, cwd, timeout, env, **kwargs):
        calls.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(expected, ensure_ascii=False))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "绝对路径"
    assert calls[0][0] == codex_bin


def test_codex_bridge_extracts_json_from_markdown_fenced_output():
    expected = _payload("围栏输出")

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("```json\n" + json.dumps(expected, ensure_ascii=False) + "\n```")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "围栏输出"


def test_codex_bridge_separates_variadic_image_arguments_from_prompt():
    expected = _payload("图片参数")

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        if "--image" in command:
            output_path.write_text(json.dumps({"imageChecks": [{"title": "图片参数"}]}, ensure_ascii=False))
            assert command[-2] == "--"
            assert "使用图片分析" in command[-1]
        else:
            output_path.write_text(json.dumps(expected, ensure_ascii=False))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "layout.png",
                "kind": "image",
                "contentType": "image/png",
                "text": "[Image uploaded for visual/layout reference: layout.png]",
                "content": b"fake image bytes",
            }
        ],
        prompt="使用图片分析",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "图片参数"


def test_codex_bridge_skips_office_rendered_images_when_text_was_extracted():
    expected = _payload("跳过Office图片")

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(expected, ensure_ascii=False))
        assert "--image" not in command
        assert command[command.index("--model") + 1] == "gpt-5.3-codex-spark"
        manifest = json.loads((Path(cwd) / "manifest.json").read_text())
        assert manifest[1]["derivedFrom"] == "transfer.doc"
        assert manifest[1]["sourcePage"] == 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "transfer.doc",
                "kind": "document",
                "contentType": "application/msword",
                "text": "花名 筝筝日上 品名 天丝棉绣花三/四件套 " * 20,
                "content": b"office bytes",
            },
            {
                "filename": "transfer.doc.page-1.png",
                "kind": "image",
                "contentType": "image/png",
                "text": "[Rendered PDF page 1 from transfer.doc]",
                "content": b"page png",
                "derivedFrom": "transfer.doc",
                "sourcePage": 1,
            },
        ],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "跳过Office图片"


def test_codex_bridge_keeps_pdf_rendered_images_for_layout_analysis():
    expected = _payload("保留PDF图片")

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        if "--image" in command:
            output_path.write_text(json.dumps({"imageChecks": [{"title": "layout"}]}, ensure_ascii=False))
            assert command[command.index("--model") + 1] == "gpt-5.4-mini"
        else:
            output_path.write_text(json.dumps(expected, ensure_ascii=False))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "layout.pdf",
                "kind": "pdf",
                "contentType": "application/pdf",
                "text": "[PDF uploaded: layout.pdf]",
                "content": b"%PDF",
            },
            {
                "filename": "layout.pdf.page-1.png",
                "kind": "image",
                "contentType": "image/png",
                "text": "[Rendered PDF page 1 from layout.pdf]",
                "content": b"page png",
                "derivedFrom": "layout.pdf",
                "sourcePage": 1,
            },
        ],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "保留PDF图片"


def test_codex_bridge_keeps_pdf_rendered_images_when_ocr_text_is_sufficient():
    ocr_text = "温莎城堡 1010103855 被里 204×234 被面下方小页 17×204 " * 8
    facts = {
        "meta": {"productName": "80S天丝棉印花四件套", "flowerName": "温莎城堡"},
        "variants": [
            {
                "id": "1010103855",
                "label": "卡其色",
                "components": [
                    {
                        "id": "quilt-face-lower-small-panel",
                        "name": "被面下方小页",
                        "category": "quilt-face",
                        "shape": {"type": "rectangle", "width": 17, "height": 204},
                    }
                ],
            }
        ],
    }

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        if "--image" in command:
            output_path.write_text(json.dumps({"imageChecks": [{"title": "Queen 产品排版图"}]}, ensure_ascii=False))
            assert command[command.index("--model") + 1] == "gpt-5.4-mini"
            assert "多模态视觉校验" in command[-1]
        else:
            output_path.write_text(json.dumps(facts, ensure_ascii=False))
            assert "只做视觉事实抽取" in command[-1]
            assert "温莎城堡" in command[-1]
            assert "17×204" in command[-1]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "layout.pdf",
                "kind": "pdf",
                "contentType": "application/pdf",
                "text": "B版 3.6cm",
                "content": b"%PDF",
            },
            {
                "filename": "layout.pdf.page-1.png",
                "kind": "image",
                "contentType": "image/png",
                "text": "[Rendered PDF page 1 from layout.pdf]\n\nOCR text:\n" + ocr_text,
                "ocrText": ocr_text,
                "content": b"page png",
                "derivedFrom": "layout.pdf",
                "sourcePage": 1,
            },
        ],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "80S天丝棉印花四件套"
    assert result["variants"][0]["components"][0]["name"] == "被面下方小页"


def test_codex_bridge_runs_compact_multimodal_pass_before_text_structuring():
    calls = []
    evidence = {
        "imageChecks": [
            {
                "sourcePage": 1,
                "title": "Queen 产品排版图",
                "visibleSkus": ["1010103855"],
                "visiblePartNames": ["被里", "被面下方小页"],
                "visibleDimensions": ["204", "17×204"],
            }
        ]
    }
    facts = {
        "meta": {"productName": "80S天丝棉印花四件套", "flowerName": "温莎城堡"},
        "variants": [
            {
                "id": "1010103855",
                "label": "卡其色",
                "components": [{"id": "quilt-lining-main", "name": "被里", "category": "quilt-lining"}],
            }
        ],
    }

    def fake_runner(command, cwd, timeout, env, **kwargs):
        calls.append(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        if "--image" in command:
            output_path.write_text(json.dumps(evidence, ensure_ascii=False))
            assert "多模态视觉校验" in command[-1]
            assert "不要生成完整结构" in command[-1]
        else:
            output_path.write_text(json.dumps(facts, ensure_ascii=False))
            assert "多模态视觉校验结果" in command[-1]
            assert "Queen 产品排版图" in command[-1]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "layout.pdf",
                "kind": "pdf",
                "contentType": "application/pdf",
                "text": "B版 3.6cm",
                "content": b"%PDF",
            },
            {
                "filename": "layout.pdf.page-1.ai.jpg",
                "kind": "image",
                "contentType": "image/jpeg",
                "text": "[Rendered PDF page 1 from layout.pdf]\n\nOCR text:\n温莎城堡 1010103855 被里 204 被面下方小页 17×204",
                "ocrText": "温莎城堡 1010103855 被里 204 被面下方小页 17×204",
                "content": b"\xff\xd8\xff fake jpeg",
                "derivedFrom": "layout.pdf",
                "sourcePage": 1,
            },
        ],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert len(calls) == 2
    assert "--image" in calls[0]
    assert "--image" not in calls[1]
    assert calls[0][calls[0].index("--model") + 1] == "gpt-5.4-mini"
    assert calls[1][calls[1].index("--model") + 1] == "gpt-5.3-codex-spark"
    assert result["meta"]["productName"] == "80S天丝棉印花四件套"


def test_codex_bridge_uses_compact_visual_facts_for_image_layout_analysis():
    facts = {
        "meta": {
            "title": "80S天丝棉印花四件套温莎城堡产品排版图",
            "productName": "80S天丝棉印花四件套",
            "flowerName": "温莎城堡",
            "scale": "1:50",
            "unit": "cm",
            "fabricWidth": 250,
        },
        "technicalRequirements": ["被套和床单常规抛4cm"],
        "variants": [
            {
                "id": "1010103855",
                "label": "卡其色常规四件套",
                "components": [
                    {
                        "id": "quilt-lining-main",
                        "name": "被里主片",
                        "category": "quilt-lining",
                        "quantity": {"perSet": 1, "unit": "页"},
                        "shape": {"type": "rectangle", "width": 204, "height": 234},
                        "display": {"showDimensions": True},
                        "annotations": [{"kind": "label", "text": "被里（1套1页）", "placement": "inside"}],
                        "dimensions": {"finishedSize": {"width": 200, "height": 230}},
                    }
                ],
            }
        ],
    }

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        prompt = command[-1]
        if "--image" in command:
            output_path.write_text(json.dumps({"imageChecks": [{"title": "Queen 产品排版图"}]}, ensure_ascii=False))
            assert "多模态视觉校验" in prompt
            assert "不要生成完整结构" in prompt
        else:
            output_path.write_text(json.dumps(facts, ensure_ascii=False))
            assert "只做视觉事实抽取" in prompt
            assert "不要生成完整 product-layout schema" in prompt
            assert '"schemaVersion"' not in prompt
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[
            {
                "filename": "layout.pdf",
                "kind": "pdf",
                "contentType": "application/pdf",
                "text": "B版 3.6cm",
                "content": b"%PDF",
            },
            {
                "filename": "layout.pdf.page-1.png",
                "kind": "image",
                "contentType": "image/png",
                "text": "[Rendered PDF page 1 from layout.pdf]",
                "content": b"page png",
                "derivedFrom": "layout.pdf",
                "sourcePage": 1,
            },
        ],
        prompt="",
        parameters={},
        runner=fake_runner,
    )

    assert result["schemaVersion"] == "1.0.0"
    assert result["documentType"] == "product-layout"
    assert result["meta"]["productName"] == "80S天丝棉印花四件套"
    assert result["technicalRequirements"] == [{"no": 1, "text": "被套和床单常规抛4cm"}]
    assert result["variants"][0]["components"][0]["name"] == "被里主片"


def test_codex_bridge_includes_domain_skill_in_prompt():
    expected = _payload("排版图技能")

    def fake_runner(command, cwd, timeout, env, **kwargs):
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(expected, ensure_ascii=False))
        prompt = command[-1]
        assert "床品产品排版图分析 Skill" in prompt
        assert "已提取文本内容" in prompt
        assert "不要调用 shell" in prompt
        assert "不要自行尝试破解或长时间转换" in prompt
        assert "CAD/PDF 渲染优先" in prompt
        assert "不要把洗涤注意事项当作排版图技术要求" in prompt
        assert "不要使用固定产品样例补齐缺失数据" in prompt
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = generate_layout_via_codex(
        extracted_files=[],
        prompt="按附件分析",
        parameters={},
        runner=fake_runner,
    )

    assert result["meta"]["productName"] == "排版图技能"


def test_codex_bridge_raises_on_cli_failure():
    def fake_runner(command, cwd, timeout, env, **kwargs):
        return SimpleNamespace(returncode=1, stdout="failed stdout", stderr="failed stderr")

    with pytest.raises(CodexExecutionError, match="failed stderr"):
        generate_layout_via_codex(
            extracted_files=[],
            prompt="",
            parameters={},
            runner=fake_runner,
        )


def test_codex_bridge_raises_clear_error_on_cli_timeout():
    def fake_runner(command, cwd, timeout, env, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout)

    with pytest.raises(CodexExecutionError, match="timed out after 9 seconds"):
        generate_layout_via_codex(
            extracted_files=[],
            prompt="",
            parameters={},
            runner=fake_runner,
            timeout_seconds=9,
        )


def test_generate_layout_uses_codex_bridge(monkeypatch):
    expected = _payload("生成器转发")

    def fake_bridge(extracted_files, prompt, parameters):
        assert prompt == "用户说明"
        assert parameters == {"template": "queen-standard-a3"}
        return expected

    monkeypatch.setattr("app.generator.generate_layout_via_codex", fake_bridge)

    result = generate_layout(
        extracted_files=[{"filename": "transfer.txt", "text": "demo"}],
        prompt="用户说明",
        parameters={"template": "queen-standard-a3"},
    )

    assert result["meta"]["productName"] == "生成器转发"
    assert result["titleBlock"]["template"] == "queen-standard-a3"
    assert result["titleBlock"]["fields"]["比例"] == "1:50"
    assert result["titleBlock"]["fields"]["单位"] == "cm"
