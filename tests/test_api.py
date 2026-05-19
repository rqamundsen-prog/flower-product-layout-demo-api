from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_page_serves_upload_interface():
    response = client.get("/")

    assert response.status_code == 200
    assert "产品排版图 JSON Demo" in response.text
    assert "/api/layouts/jobs" in response.text
    assert "结构化参数 JSON" not in response.text


def test_generate_layout_api_accepts_files_and_returns_ai_layout_json(monkeypatch):
    ai_payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {"title": "产品排版图", "productName": "温莎城堡", "scale": "1:50", "unit": "cm"},
        "technicalRequirements": [{"no": 1, "text": "AI实时分析生成"}],
        "sizeTable": {"columns": ["partName", "finishedSize"], "rows": []},
        "variants": [{"id": "1010103855", "label": "1010103855", "layout": {}, "components": []}],
        "titleBlock": {"template": "queen-standard-a3", "fields": {"图名": "产品排版图"}},
    }

    def fake_generate_layout(extracted_files, prompt, parameters):
        assert prompt == "使用 QUEEN 模板，比例 1:50，床单圆角"
        assert parameters == {"template": "queen-standard-a3"}
        assert {item["filename"] for item in extracted_files} == {"transfer.txt", "layout.png"}
        assert all("content" in item for item in extracted_files)
        return ai_payload

    monkeypatch.setattr("app.main.generate_layout", fake_generate_layout)

    transfer_text = """
    品名 80S天丝棉印花四件套
    花名 温莎城堡(卡其色)
    1010103855/1010103857
    被套：(200×230)cm×1床
    床单：(245×245)cm×1床
    短枕套：(52×72)cm×2个
    """

    response = client.post(
        "/api/layouts/generate",
        data={
            "prompt": "使用 QUEEN 模板，比例 1:50，床单圆角",
            "parameters": '{"template": "queen-standard-a3"}',
        },
        files=[
            ("files", ("transfer.txt", transfer_text.encode("utf-8"), "text/plain")),
            ("files", ("layout.png", b"fake image bytes", "image/png")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert "layout" not in body
    assert body["schemaVersion"] == "1.0.0"
    assert body["documentType"] == "product-layout"
    assert body["meta"]["productName"] == "温莎城堡"
    assert body["titleBlock"]["template"] == "queen-standard-a3"
    assert body["variants"]


def test_generate_layout_api_accepts_missing_parameters(monkeypatch):
    ai_payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {"title": "产品排版图", "productName": "温莎城堡", "scale": "1:50", "unit": "cm"},
        "technicalRequirements": [],
        "sizeTable": {"columns": [], "rows": []},
        "variants": [{"id": "1010103855", "label": "1010103855", "layout": {}, "components": []}],
        "titleBlock": {"template": "standard-a3", "fields": {"图名": "产品排版图"}},
    }

    def fake_generate_layout(extracted_files, prompt, parameters):
        assert parameters == {}
        return ai_payload

    monkeypatch.setattr("app.main.generate_layout", fake_generate_layout)

    response = client.post(
        "/api/layouts/generate",
        data={"prompt": "所有参数从附件和说明中提取"},
        files=[("files", ("transfer.txt", b"demo", "text/plain"))],
    )

    assert response.status_code == 200
    assert response.json()["documentType"] == "product-layout"


def test_layout_job_api_returns_job_and_exposes_completed_result(monkeypatch):
    ai_payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {"title": "产品排版图", "productName": "温莎城堡", "scale": "1:50", "unit": "cm"},
        "technicalRequirements": [],
        "sizeTable": {"columns": [], "rows": []},
        "variants": [{"id": "1010103855", "label": "1010103855", "layout": {}, "components": []}],
        "titleBlock": {"template": "standard-a3", "fields": {"图名": "产品排版图"}},
    }

    def fake_generate_layout(extracted_files, prompt, parameters):
        assert prompt == "只用附件和人工说明"
        assert parameters == {}
        return ai_payload

    monkeypatch.setattr("app.main.generate_layout", fake_generate_layout)

    response = client.post(
        "/api/layouts/jobs",
        data={"prompt": "只用附件和人工说明"},
        files=[("files", ("transfer.txt", b"demo", "text/plain"))],
    )

    assert response.status_code == 200
    created = response.json()
    assert created["jobId"]
    assert created["statusUrl"] == f"/api/layouts/jobs/{created['jobId']}"

    for _ in range(20):
        status_response = client.get(created["statusUrl"])
        body = status_response.json()
        if body["status"] == "completed":
            break

    assert status_response.status_code == 200
    assert body["status"] == "completed"
    assert body["result"]["documentType"] == "product-layout"


def test_generate_layout_api_rejects_invalid_parameters_json():
    response = client.post(
        "/api/layouts/generate",
        data={"prompt": "", "parameters": "{not-json"},
        files=[("files", ("transfer.txt", b"demo", "text/plain"))],
    )

    assert response.status_code == 400
    assert "parameters" in response.json()["detail"]


def test_generate_layout_api_reports_missing_codex_configuration(monkeypatch):
    def fake_generate_layout(extracted_files, prompt, parameters):
        from app.codex_bridge import CodexConfigurationError

        raise CodexConfigurationError("codex CLI is not installed or not on PATH")

    monkeypatch.setattr("app.main.generate_layout", fake_generate_layout)

    response = client.post(
        "/api/layouts/generate",
        data={"prompt": "", "parameters": "{}"},
        files=[("files", ("transfer.txt", b"demo", "text/plain"))],
    )

    assert response.status_code == 503
    assert "codex CLI" in response.json()["detail"]
