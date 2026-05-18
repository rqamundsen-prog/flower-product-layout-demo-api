# Flower Product Layout Demo API

Demo service for turning product transfer files, layout references, and user parameters into `product-layout` JSON for CAD-side rendering.

## Run

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

## API

`POST /api/layouts/generate`

Content type: `multipart/form-data`

Fields:

- `files`: one or more `.doc`, `.docx`, `.pdf`, `.png`, `.jpg`, `.txt`, or `.json` files.
- `prompt`: natural language instructions, for example `使用 QUEEN 模板，比例 1:50，单位 cm，床单圆角`.
- `parameters`: JSON object string. Example:

```json
{
  "template": "queen-standard-a3",
  "scale": "1:50",
  "unit": "cm"
}
```

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/layouts/generate \
  -F "prompt=使用 QUEEN 模板，比例 1:50，单位 cm，床单圆角" \
  -F 'parameters={"template":"queen-standard-a3"}' \
  -F "files=@/path/to/信息传递表.doc" \
  -F "files=@/path/to/排版.pdf"
```

Response envelope:

```json
{
  "layout": {
    "schemaVersion": "1.0.0",
    "documentType": "product-layout",
    "meta": {},
    "technicalRequirements": [],
    "sizeTable": {},
    "variants": [],
    "titleBlock": {}
  },
  "validation": {
    "status": "ok",
    "warnings": [],
    "missing": []
  },
  "sources": []
}
```

## Demo Scope

This demo prioritizes end-to-end delivery:

- Web upload page.
- Multipart API for external callers and CAD-side integration.
- Best-effort text extraction from uploaded files.
- Deterministic JSON generation without requiring external AI credentials.

Business rules are intentionally light. Later production work can replace `app/generator.py` with a stricter rules engine or an AI structured-output pipeline while keeping the same API contract.

## Test

```bash
python -m pytest -v
```
