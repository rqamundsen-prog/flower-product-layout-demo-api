from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_home_page_serves_upload_interface():
    response = client.get("/")

    assert response.status_code == 200
    assert "产品排版图 JSON Demo" in response.text
    assert "/api/layouts/generate" in response.text


def test_generate_layout_api_accepts_files_and_returns_layout_json():
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
    assert body["layout"]["schemaVersion"] == "1.0.0"
    assert body["layout"]["documentType"] == "product-layout"
    assert body["layout"]["meta"]["productName"] == "温莎城堡"
    assert body["layout"]["titleBlock"]["template"] == "queen-standard-a3"
    assert body["layout"]["variants"]
    assert body["validation"]["status"] == "ok"
    assert {source["filename"] for source in body["sources"]} == {"transfer.txt", "layout.png"}


def test_generate_layout_api_rejects_invalid_parameters_json():
    response = client.post(
        "/api/layouts/generate",
        data={"prompt": "", "parameters": "{not-json"},
        files=[("files", ("transfer.txt", b"demo", "text/plain"))],
    )

    assert response.status_code == 400
    assert "parameters" in response.json()["detail"]
