import json
from types import SimpleNamespace

import pytest

from app.generator import AIConfigurationError, AIGenerationError, generate_layout


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload, ensure_ascii=False))


class FakeOpenAIClient:
    def __init__(self, payload):
        self.responses = FakeResponses(payload)


def test_generate_layout_uses_ai_response_as_the_layout_source():
    ai_payload = {
        "layout": {
            "schemaVersion": "1.0.0",
            "documentType": "product-layout",
            "meta": {"title": "产品排版图", "productName": "温莎城堡", "scale": "1:50", "unit": "cm"},
            "technicalRequirements": [{"no": 1, "text": "AI根据上传资料生成"}],
            "sizeTable": {
                "columns": ["partName", "finishedSize", "cuttingSizeFace", "cuttingSizeBack"],
                "rows": [
                    {
                        "variantId": "1010103855",
                        "partId": "ai-quilt",
                        "partName": "被套",
                        "finishedSize": {"width": 200, "height": 230},
                        "cuttingSizeFace": {"width": 204, "height": 234},
                        "cuttingSizeBack": None,
                    }
                ],
            },
            "variants": [
                {
                    "id": "1010103855",
                    "label": "1010103855",
                    "layout": {"mode": "flow", "direction": "horizontal", "gap": 25, "wrap": True},
                    "components": [
                        {
                            "id": "ai-quilt",
                            "name": "被套",
                            "category": "quilt-face",
                            "quantity": {"perSet": 1, "unit": "床"},
                            "shape": {"type": "rectangle", "width": 204, "height": 234},
                            "display": {"showDimensions": True},
                            "annotations": [{"kind": "label", "text": "被套", "placement": "inside"}],
                            "dimensions": {"finishedSize": {"width": 200, "height": 230}},
                        }
                    ],
                }
            ],
            "titleBlock": {"template": "queen-standard-a3", "fields": {"图名": "产品排版图", "比例": "1:50", "单位": "cm"}},
        },
        "validation": {"status": "ok", "warnings": [], "missing": []},
        "sources": [{"filename": "transfer.txt", "kind": "document", "textLength": 28}],
    }
    client = FakeOpenAIClient(ai_payload)

    result = generate_layout(
        extracted_files=[
            {
                "filename": "transfer.txt",
                "kind": "document",
                "contentType": "text/plain",
                "text": "温莎城堡 1010103855 被套：(200×230)cm×1床",
                "content": b"ignored by fake",
            }
        ],
        prompt="使用 QUEEN 模板，比例 1:50",
        parameters={"template": "queen-standard-a3"},
        client=client,
        model="gpt-test",
    )

    assert result == ai_payload
    call = client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["text"]["format"]["type"] == "json_schema"
    assert "product_layout_response" == call["text"]["format"]["name"]
    user_content = call["input"][1]["content"]
    assert any(item["type"] == "input_text" and "温莎城堡" in item["text"] for item in user_content)


def test_generate_layout_requires_openai_api_key_when_no_client_is_injected(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(AIConfigurationError):
        generate_layout(extracted_files=[], prompt="", parameters={})


def test_generate_layout_wraps_ai_provider_failures():
    class BrokenResponses:
        def create(self, **kwargs):
            raise RuntimeError("provider quota exceeded")

    class BrokenClient:
        responses = BrokenResponses()

    with pytest.raises(AIGenerationError, match="provider quota exceeded"):
        generate_layout(
            extracted_files=[],
            prompt="",
            parameters={},
            client=BrokenClient(),
            model="gpt-test",
        )
