# Flower Product Layout Demo API

Demo service for using realtime AI analysis to turn product transfer files, layout references, and user parameters into `product-layout` JSON for CAD-side rendering.

## Run

```bash
python -m pip install -r requirements.txt
export OPENAI_API_KEY="your_api_key"
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
- `prompt`: natural language instructions, for example `请实时分析上传的信息传递表、排版图 PDF/图片，使用 QUEEN 模板，比例 1:50，单位 cm，床单圆角`.
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
  -F "prompt=请实时分析上传的信息传递表、排版图 PDF/图片，使用 QUEEN 模板，比例 1:50，单位 cm，床单圆角" \
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

This demo prioritizes end-to-end AI delivery:

- Web upload page.
- Multipart API for external callers and CAD-side integration.
- Best-effort text extraction from uploaded files.
- Realtime OpenAI Responses API analysis with structured JSON output.

Business rules are intentionally light. Python is only the web/API wrapper and file preprocessor; the `layout` result is produced by the AI model in `app/generator.py`.

Required environment variables:

- `OPENAI_API_KEY`: required. The API returns HTTP 503 if this is missing.
- `OPENAI_MODEL`: optional. Defaults to `gpt-4.1-mini`.

## Test

```bash
python -m pytest -v
```
