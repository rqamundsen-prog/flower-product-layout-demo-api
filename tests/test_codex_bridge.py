import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.codex_bridge import CodexExecutionError, generate_layout_via_codex
from app.generator import generate_layout


def _payload(product_name="温莎城堡"):
    return {
        "layout": {
            "schemaVersion": "1.0.0",
            "documentType": "product-layout",
            "meta": {"title": "产品排版图", "productName": product_name, "scale": "1:50", "unit": "cm"},
            "technicalRequirements": [{"no": 1, "text": "Codex分析生成"}],
            "sizeTable": {"columns": ["partName", "finishedSize"], "rows": []},
            "variants": [{"id": "1010103855", "label": "1010103855", "layout": {}, "components": []}],
            "titleBlock": {"template": "queen-standard-a3", "fields": {"图名": "产品排版图"}},
        },
        "validation": {"status": "ok", "warnings": [], "missing": []},
        "sources": [{"filename": "transfer.txt", "kind": "document", "textLength": 64}],
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

    assert result["layout"]["meta"]["productName"] == "围栏输出"


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

    assert result == expected
