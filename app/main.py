from __future__ import annotations

import json
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.extractor import extract_uploaded_files
from app.generator import AIConfigurationError, AIGenerationError, generate_layout


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
    try:
        parsed_parameters = json.loads(parameters) if parameters.strip() else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"parameters must be valid JSON: {exc.msg}") from exc

    if not isinstance(parsed_parameters, dict):
        raise HTTPException(status_code=400, detail="parameters must be a JSON object")

    extracted = await extract_uploaded_files(files)
    try:
        return generate_layout(extracted_files=extracted, prompt=prompt, parameters=parsed_parameters)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AIGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
