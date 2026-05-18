from app.generator import generate_layout


def test_generate_layout_extracts_product_specs_from_transfer_table_text():
    text = """
    品名 80S天丝棉印花四件套
    花名 温莎城堡(卡其色) 温莎城堡(雾蓝色)
    1010103855/1010103857
    被  套：(200×230)cm×1床
    床  单：(245×245)cm×1床
    短枕套：(52×72)cm×2个
    1010103856/1010103858
    加大被套：(248×248)cm×1床
    加大床单：(270×260)cm×1床
    短 枕 套：(52×72)cm×2个
    """

    result = generate_layout(
        extracted_files=[{"filename": "transfer.doc", "text": text, "kind": "document"}],
        prompt="模板 QUEEN，比例 1:50，单位 cm，床单圆角",
        parameters={},
    )

    layout = result["layout"]
    assert layout["schemaVersion"] == "1.0.0"
    assert layout["documentType"] == "product-layout"
    assert layout["meta"]["productName"] == "温莎城堡"
    assert layout["meta"]["scale"] == "1:50"
    assert layout["meta"]["unit"] == "cm"
    assert layout["titleBlock"]["template"] == "queen-standard-a3"

    variant_ids = {variant["id"] for variant in layout["variants"]}
    assert {"1010103855", "1010103856", "1010103857", "1010103858"} <= variant_ids

    part_names = {row["partName"] for row in layout["sizeTable"]["rows"]}
    assert {"被套", "床单", "短枕套", "加大被套", "加大床单"} <= part_names

    bedsheet_components = [
        component
        for variant in layout["variants"]
        for component in variant["components"]
        if component["name"] in {"床单", "加大床单"}
    ]
    assert bedsheet_components
    assert all(component["shape"].get("corners") for component in bedsheet_components)


def test_generate_layout_honors_structured_parameters_over_extracted_defaults():
    result = generate_layout(
        extracted_files=[],
        prompt="",
        parameters={
            "productName": "参数化产品",
            "template": "custom-demo-template",
            "scale": "1:25",
            "unit": "mm",
            "variants": [
                {
                    "id": "DEMO-001",
                    "label": "演示型号",
                    "components": [
                        {
                            "id": "demo-panel",
                            "name": "演示裁片",
                            "category": "quilt-face",
                            "quantity": {"perSet": 1, "unit": "页"},
                            "shape": {"type": "rectangle", "width": 12, "height": 34},
                            "annotations": [{"kind": "label", "text": "演示裁片", "placement": "inside"}],
                        }
                    ],
                }
            ],
        },
    )

    layout = result["layout"]
    assert layout["meta"]["productName"] == "参数化产品"
    assert layout["meta"]["scale"] == "1:25"
    assert layout["meta"]["unit"] == "mm"
    assert layout["titleBlock"]["template"] == "custom-demo-template"
    assert layout["variants"][0]["id"] == "DEMO-001"
    assert layout["variants"][0]["components"][0]["id"] == "demo-panel"
    assert result["validation"]["status"] == "ok"
