# Flower Product Layout Demo API

Demo service for using local Codex CLI / ChatGPT-auth AI analysis to turn product transfer files, layout references, and user parameters into `product-layout` JSON for CAD-side rendering. No OpenAI API key is required for the demo path.

## Run

```bash
python -m pip install -r requirements.txt
codex login status
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
- `parameters`: optional JSON object string for programmatic callers. The web demo does not show this field because normal users should put all extra information in uploaded files or `prompt`. Example:

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

Response:

```json
{
  "schemaVersion": "1.0.0",
  "documentType": "product-layout",
  "meta": {},
  "technicalRequirements": [],
  "sizeTable": {},
  "variants": [],
  "titleBlock": {}
}
```

## Web Job API

The browser page uses an async job endpoint so long-running local Codex analysis does not keep the browser request open.

`POST /api/layouts/jobs`

Fields:

- `files`: upload files.
- `prompt`: human instructions.
- `parameters`: optional JSON object string, normally omitted by the web page.

Response:

```json
{
  "jobId": "abc123",
  "status": "queued",
  "statusUrl": "/api/layouts/jobs/abc123"
}
```

Then poll:

```text
GET /api/layouts/jobs/{jobId}
```

Until `status` becomes `completed`, then read `result`.

## Demo Scope

This demo prioritizes end-to-end AI delivery through your local Codex login:

- Web upload page.
- Multipart API for external callers and CAD-side integration.
- Best-effort text extraction from uploaded files.
- Realtime local `codex exec` analysis using your Codex/ChatGPT login state.
- Deterministic post-processing for stable CAD/PDF integration: canonical top-level key order, variant IDs, component IDs, component categories, and size-table rows.

Business rules are intentionally light. Python is only the web/API wrapper and file preprocessor; the `product-layout` result is produced by Codex CLI in `app/codex_bridge.py` and follows the schema from `API数据结构.docx`.
The final API response is normalized in `app/normalizer.py` so repeated demo runs keep stable identifiers such as `1010103855_1010103857`, `quilt-face-main`, `quilt-lining-main`, `quilt-face-lower-small-panel`, `bedsheet`, and `pillowcase-short`.

Requirements:

- `codex` CLI installed and logged in on the host machine.
- `CODEX_MODEL`: optional. Defaults to `gpt-5.5`.
- `CODEX_TIMEOUT_SECONDS`: optional. Defaults to `600`.

To expose the local demo publicly:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

## Test

```bash
python -m pytest -v
```
