from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from fastapi import UploadFile


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
    return extracted


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
