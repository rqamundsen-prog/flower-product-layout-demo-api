from __future__ import annotations

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from fastapi import UploadFile


MAX_RENDERED_PAGES = int(os.getenv("FLOWER_MAX_RENDERED_PAGES", "8"))
RENDER_DPI = int(os.getenv("FLOWER_RENDER_DPI", "180"))
RENDER_TIMEOUT_SECONDS = int(os.getenv("FLOWER_RENDER_TIMEOUT_SECONDS", "30"))
OFFICE_SUFFIXES = {".doc", ".docx"}


async def extract_uploaded_files(files: list[UploadFile]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for upload in files:
        content = await upload.read()
        filename = upload.filename or "upload.bin"
        extracted.append(
            {
                "filename": filename,
                "contentType": upload.content_type,
                "kind": _kind(filename, upload.content_type),
                "text": extract_text(filename, content, upload.content_type),
                "content": content,
                "size": len(content),
            }
        )
        extracted.extend(extract_visual_references(filename, content, upload.content_type))
    return extracted


def extract_visual_references(filename: str, content: bytes, content_type: str | None = None) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        return _render_pdf_pages(filename, content)
    if suffix in OFFICE_SUFFIXES:
        return _render_office_pages(filename, content)
    return []


def extract_text(filename: str, content: bytes, content_type: str | None = None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".csv", ".md", ".json"}:
        return _decode_text(content)
    if suffix == ".docx":
        return _extract_docx_text(content)
    if suffix == ".doc":
        return _extract_with_textutil(filename, content) or _decode_text(content)
    if suffix == ".pdf":
        return _extract_pdf_text(filename, content) or f"[PDF uploaded: {filename}]"
    if (content_type or "").startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return f"[Image uploaded for visual/layout reference: {filename}]"
    return _decode_text(content)


def _kind(filename: str, content_type: str | None) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".doc", ".docx", ".txt", ".csv", ".md", ".json"}:
        return "document"
    if suffix == ".pdf":
        return "pdf"
    if (content_type or "").startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    return "file"


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _extract_docx_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".docx") as temp:
        temp.write(content)
        temp.flush()
        with zipfile.ZipFile(temp.name) as archive:
            xml = archive.read("word/document.xml")

    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_with_textutil(filename: str, content: bytes) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / filename
        path.write_bytes(content)
        try:
            result = subprocess.run(
                ["textutil", "-convert", "txt", "-stdout", str(path)],
                check=False,
                capture_output=True,
                timeout=8,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return result.stdout.decode("utf-8", errors="ignore").strip()


def _extract_pdf_text(filename: str, content: bytes) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / filename
        path.write_bytes(content)
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=False,
                capture_output=True,
                timeout=8,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return result.stdout.decode("utf-8", errors="ignore").strip()


def _render_office_pages(filename: str, content: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / _safe_filename(filename)
        source_path.write_bytes(content)
        try:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(temp_path), str(source_path)],
                check=False,
                capture_output=True,
                timeout=RENDER_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []

        pdf_path = source_path.with_suffix(".pdf")
        if not pdf_path.exists():
            matches = sorted(temp_path.glob("*.pdf"))
            if not matches:
                return []
            pdf_path = matches[0]
        return _render_pdf_pages(filename, pdf_path.read_bytes())


def _render_pdf_pages(filename: str, content: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / _safe_filename(filename)
        source_path.write_bytes(content)
        output_prefix = temp_path / "page"
        command = [
            "pdftoppm",
            "-png",
            "-r",
            str(RENDER_DPI),
            "-f",
            "1",
            "-l",
            str(MAX_RENDERED_PAGES),
            str(source_path),
            str(output_prefix),
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, timeout=RENDER_TIMEOUT_SECONDS)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []

        rendered = []
        for page_index, page_path in enumerate(_rendered_page_paths(output_prefix), start=1):
            image_content = page_path.read_bytes()
            rendered.append(
                {
                    "filename": f"{filename}.page-{page_index}.png",
                    "contentType": "image/png",
                    "kind": "image",
                    "text": f"[Rendered PDF page {page_index} from {filename} for visual/layout reference]",
                    "content": image_content,
                    "size": len(image_content),
                    "derivedFrom": filename,
                    "sourcePage": page_index,
                }
            )
        return rendered


def _rendered_page_paths(output_prefix: Path) -> list[Path]:
    return sorted(output_prefix.parent.glob(f"{output_prefix.name}-*.png"), key=_page_sort_key)


def _page_sort_key(path: Path) -> int:
    try:
        return int(path.stem.rsplit("-", 1)[-1])
    except ValueError:
        return 10_000


def _safe_filename(filename: str) -> str:
    return Path(filename).name.replace("/", "_").replace(":", "_") or "upload"
