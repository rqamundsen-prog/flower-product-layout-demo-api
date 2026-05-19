from app.normalizer import normalize_product_layout


def test_normalizer_canonicalizes_windsor_variant_and_component_ids():
    payload = {
        "documentType": "product-layout",
        "schemaVersion": "1.0.0",
        "technicalRequirements": [{"no": 8, "text": "余料做下方小页"}, {"no": 2, "text": "面料幅宽250"}],
        "meta": {"productName": "80S天丝棉印花四件套", "unit": "cm"},
        "sizeTable": {
            "columns": ["variantId", "partId", "partName"],
            "rows": [
                {"variantId": "STD-200x230", "partId": "STD-QB-B", "partName": "被里B版"},
                {"variantId": "STD-200x230", "partId": "STD-SHEET", "partName": "床单"},
                {"variantId": "STD-200x230", "partId": "STD-LOWER-A", "partName": "被面下方小页A版下裁"},
                {"variantId": "STD-200x230", "partId": "STD-QF-A", "partName": "被面A版"},
            ],
        },
        "variants": [
            {
                "id": "STD-200x230",
                "label": "1010103855卡其 / 1010103857雾蓝 标准四件套",
                "layout": {},
                "components": [
                    {"id": "STD-SHEET", "name": "床单", "category": "flat-sheet"},
                    {"id": "STD-QB-B", "name": "被里B版", "category": "quilt-back"},
                    {"id": "STD-LOWER-A", "name": "被面下方小页", "category": "quilt-face-lower-panel"},
                    {"id": "STD-QF-A", "name": "被面A版", "category": "quilt-face"},
                ],
            }
        ],
        "titleBlock": {"fields": {"单位": ""}},
    }

    normalized = normalize_product_layout(payload, {"template": "queen-standard-a3", "scale": "1:50", "unit": "cm"})

    assert list(normalized.keys()) == [
        "schemaVersion",
        "documentType",
        "meta",
        "technicalRequirements",
        "sizeTable",
        "variants",
        "titleBlock",
    ]
    assert normalized["meta"]["scale"] == "1:50"
    assert normalized["titleBlock"]["template"] == "queen-standard-a3"
    assert normalized["titleBlock"]["fields"]["单位"] == "cm"
    assert normalized["technicalRequirements"] == [
        {"no": 1, "text": "面料幅宽250"},
        {"no": 2, "text": "余料做下方小页"},
    ]

    variant = normalized["variants"][0]
    assert variant["id"] == "1010103855_1010103857"
    assert [component["id"] for component in variant["components"]] == [
        "quilt-face-main",
        "quilt-lining-main",
        "quilt-face-lower-small-panel",
        "bedsheet",
    ]
    assert [component["category"] for component in variant["components"]] == [
        "quilt-face",
        "quilt-lining",
        "quilt-face",
        "bedsheet",
    ]
    assert [(row["variantId"], row["partId"]) for row in normalized["sizeTable"]["rows"]] == [
        ("1010103855_1010103857", "quilt-face-main"),
        ("1010103855_1010103857", "quilt-lining-main"),
        ("1010103855_1010103857", "quilt-face-lower-small-panel"),
        ("1010103855_1010103857", "bedsheet"),
    ]


def test_normalizer_uses_size_fallback_when_skus_are_missing():
    payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {},
        "technicalRequirements": [],
        "sizeTable": {"rows": [{"variantId": "PLUS", "partId": "p1", "partName": "加大被面A版"}]},
        "variants": [
            {
                "id": "PLUS",
                "label": "248×248加大四件套",
                "layout": {},
                "components": [{"id": "p1", "name": "加大被面A版", "category": "quilt-face"}],
            }
        ],
        "titleBlock": {},
    }

    normalized = normalize_product_layout(payload, {})

    assert normalized["variants"][0]["id"] == "queen-248x248"
    assert normalized["sizeTable"]["rows"][0]["variantId"] == "queen-248x248"


def test_normalizer_does_not_backfill_fixed_windsor_placeholders():
    payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {},
        "technicalRequirements": [],
        "sizeTable": {
            "rows": [
                {"variantId": "1010103856_1010103858", "partId": "large-quilt-cover-cut", "partName": "加大被套"},
                {"variantId": "1010103856_1010103858", "partId": "short-pillowcase-a", "partName": "短枕大页"},
                {"variantId": "1010103856_1010103858", "partId": "short-pillowcase-b", "partName": "短枕里"},
            ]
        },
        "variants": [
            {
                "id": "1010103856_1010103858",
                "label": "加大款：248×248被套 / 270×260床单 / 52×72短枕套",
                "layout": {},
                "components": [
                    {"id": "large-quilt-cover-cut", "name": "加大被套", "category": "quilt-cover"},
                    {"id": "short-pillowcase-a", "name": "短枕大页", "category": "pillowcase"},
                    {"id": "short-pillowcase-b", "name": "短枕里", "category": "pillowcase"},
                ],
            }
        ],
        "titleBlock": {},
    }

    normalized = normalize_product_layout(payload, {})
    variant = normalized["variants"][0]

    assert [component["id"] for component in variant["components"]] == [
        "quilt-face-main",
        "pillowcase-short",
    ]
    assert [component["category"] for component in variant["components"]] == [
        "quilt-face",
        "pillowcase",
    ]
    assert [(row["variantId"], row["partId"]) for row in normalized["sizeTable"]["rows"]] == [
        ("1010103856_1010103858", "quilt-face-main"),
        ("1010103856_1010103858", "pillowcase-short"),
    ]
    assert "AI输出缺少" not in str(normalized)


def test_normalizer_does_not_treat_other_product_with_same_sizes_as_windsor():
    payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {"productName": "天丝棉绣花三/四件套", "flowerName": "筝筝日上"},
        "technicalRequirements": [],
        "sizeTable": {
            "rows": [
                {"variantId": "1030100823", "partId": "border", "partName": "被面三方拼边用"},
                {"variantId": "1030100823", "partId": "bedsheet", "partName": "床单"},
            ]
        },
        "variants": [
            {
                "id": "1030100823",
                "label": "1030100823 150×215被套 / 200×230床单",
                "layout": {},
                "components": [
                    {"id": "border", "name": "被面三方拼边用", "category": "quilt-face"},
                    {"id": "bedsheet", "name": "床单", "category": "bedsheet"},
                ],
            }
        ],
        "titleBlock": {},
    }

    normalized = normalize_product_layout(payload, {})

    assert normalized["variants"][0]["id"] == "1030100823"
    assert [component["id"] for component in normalized["variants"][0]["components"]] == [
        "quilt-face-main",
        "bedsheet",
    ]
    assert [(row["variantId"], row["partId"]) for row in normalized["sizeTable"]["rows"]] == [
        ("1030100823", "quilt-face-main"),
        ("1030100823", "bedsheet"),
    ]
    assert "pillowcase-short" not in str(normalized)


def test_normalizer_classifies_pillow_small_page_as_pillowcase_not_quilt_panel():
    payload = {
        "schemaVersion": "1.0.0",
        "documentType": "product-layout",
        "meta": {},
        "technicalRequirements": [],
        "sizeTable": {"rows": []},
        "variants": [
            {
                "id": "1010103855_1010103857",
                "label": "标准款 200×230",
                "layout": {},
                "components": [
                    {"id": "pillow-small", "name": "短枕小页", "category": "pillowcase"},
                    {"id": "quilt-small", "name": "被面下方小页", "category": "quilt-face-small-panel"},
                ],
            }
        ],
        "titleBlock": {},
    }

    normalized = normalize_product_layout(payload, {})
    components = {component["id"]: component for component in normalized["variants"][0]["components"]}

    assert components["pillowcase-short"]["category"] == "pillowcase"
    assert components["quilt-face-lower-small-panel"]["category"] == "quilt-face"
