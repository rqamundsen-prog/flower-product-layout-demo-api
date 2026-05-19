# Docx API Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/api/layouts/generate` return the top-level `product-layout` JSON structure defined in `API数据结构.docx`.

**Architecture:** Keep FastAPI and the local Codex CLI bridge unchanged as the execution path. Change the Codex prompt, response validation, tests, UI status handling, and README examples so the contract is the document schema itself, not an envelope with `layout`.

**Tech Stack:** FastAPI, pytest, local Codex CLI, vanilla HTML/JS.

---

### Task 1: Contract Tests

**Files:**
- Modify: `/Users/mac/Documents/flower/tests/test_api.py`
- Modify: `/Users/mac/Documents/flower/tests/test_codex_bridge.py`

- [ ] **Step 1: Update API test fixture to return top-level product-layout JSON.**

Use a payload with `schemaVersion`, `documentType`, `meta`, `technicalRequirements`, `sizeTable`, `variants`, and `titleBlock` at the top level.

- [ ] **Step 2: Run focused tests and confirm they fail against the old envelope expectations.**

Run: `python -m pytest tests/test_api.py tests/test_codex_bridge.py -v`

Expected before implementation: failures referencing missing `layout` or missing top-level schema handling.

### Task 2: Codex Bridge Contract

**Files:**
- Modify: `/Users/mac/Documents/flower/app/codex_bridge.py`

- [ ] **Step 1: Update the prompt to say the top-level object must be the docx schema.**

The example must start with `schemaVersion` and must not wrap the result in `layout`.

- [ ] **Step 2: Update `_validate_payload` to validate top-level docx schema keys.**

Require `schemaVersion == "1.0.0"`, `documentType == "product-layout"`, `meta` object, `technicalRequirements` array, `sizeTable` object, `variants` array, and `titleBlock` object.

- [ ] **Step 3: Run focused tests and confirm they pass.**

Run: `python -m pytest tests/test_api.py tests/test_codex_bridge.py -v`

### Task 3: Web And Docs

**Files:**
- Modify: `/Users/mac/Documents/flower/app/static/app.js`
- Modify: `/Users/mac/Documents/flower/README.md`

- [ ] **Step 1: Update the browser status badge to read top-level `documentType` or fallback to `ok`.**

- [ ] **Step 2: Replace README response envelope with the docx top-level response contract.**

- [ ] **Step 3: Run full tests.**

Run: `python -m pytest -v`

### Task 4: Runtime Verification

**Files:**
- No production file edits.

- [ ] **Step 1: Restart local uvicorn if an old process is still bound to port 8000.**

Run: `kill $(lsof -ti tcp:8000)` if needed, then `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.

- [ ] **Step 2: Call `/api/health`.**

Expected: `{"status":"ok"}`

- [ ] **Step 3: Call `/api/layouts/generate` with the 温莎城堡 input files.**

Expected: HTTP 200 with top-level `schemaVersion: "1.0.0"` and `documentType: "product-layout"`.
