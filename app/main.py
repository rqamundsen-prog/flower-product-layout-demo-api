from __future__ import annotations

import json
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.extractor import extract_uploaded_files
from app.codex_bridge import CodexConfigurationError, CodexExecutionError
from app.generator import generate_layout
from app.jobs import layout_jobs


app = FastAPI(
    title="Flower Product Layout Demo API",
    version="0.1.0",
    description="Demo API that turns product transfer files and user parameters into product-layout JSON.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/layouts/generate")
async def generate_layout_endpoint(
    files: Annotated[list[UploadFile], File(description="Product transfer table, layout PDF, and reference images")] = [],
    prompt: Annotated[str, Form(description="Human instructions and demo parameters")] = "",
    parameters: Annotated[str, Form(description="Optional JSON object with structured parameters")] = "{}",
) -> dict:
    parsed_parameters = _parse_parameters(parameters)
    extracted = await extract_uploaded_files(files)
    try:
        return await run_in_threadpool(generate_layout, extracted, prompt, parsed_parameters)
    except CodexConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CodexExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/layouts/jobs")
async def create_layout_job_endpoint(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="Product transfer table, layout PDF, and reference images")] = [],
    prompt: Annotated[str, Form(description="Human instructions and demo parameters")] = "",
    parameters: Annotated[str, Form(description="Optional JSON object with structured parameters")] = "{}",
) -> dict:
    parsed_parameters = _parse_parameters(parameters)
    extracted = await extract_uploaded_files(files)
    job_id = layout_jobs.create()

    def worker() -> dict:
        return generate_layout(extracted_files=extracted, prompt=prompt, parameters=parsed_parameters)

    background_tasks.add_task(layout_jobs.run, job_id, worker)
    return {"jobId": job_id, "status": "queued", "statusUrl": f"/api/layouts/jobs/{job_id}"}


@app.get("/api/layouts/jobs/{job_id}")
async def get_layout_job_endpoint(job_id: str) -> dict:
    job = layout_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _parse_parameters(parameters: str) -> dict:
    try:
        parsed_parameters = json.loads(parameters) if parameters.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"parameters must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed_parameters, dict):
        raise HTTPException(status_code=400, detail="parameters must be a JSON object")
    return parsed_parameters
