from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from fastapi import UploadFile


MAX_RENDERED_PAGES = int(os.getenv("FLOWER_MAX_RENDERED_PAGES", "8"))
RENDER_DPI = int(os.getenv("FLOWER_RENDER_DPI", "90"))
RENDER_TIMEOUT_SECONDS = int(os.getenv("FLOWER_RENDER_TIMEOUT_SECONDS", "30"))
OFFICE_TEXT_TIMEOUT_SECONDS = int(os.getenv("FLOWER_OFFICE_TEXT_TIMEOUT_SECONDS", "30"))
IMAGE_OCR_ENABLED = os.getenv("FLOWER_IMAGE_OCR", "1").lower() not in {"0", "false", "no"}
IMAGE_OCR_TIMEOUT_SECONDS = int(os.getenv("FLOWER_IMAGE_OCR_TIMEOUT_SECONDS", "60"))
AI_IMAGE_MAX_WIDTH = int(os.getenv("FLOWER_AI_IMAGE_MAX_WIDTH", "900"))
AI_IMAGE_JPEG_QUALITY = int(os.getenv("FLOWER_AI_IMAGE_JPEG_QUALITY", "82"))
OFFICE_SUFFIXES = {".doc", ".docx"}


async def extract_uploaded_files(files: list[UploadFile]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for upload in files:
        content = await upload.read()
        filename = upload.filename or "upload.bin"
        text = extract_text(filename, content, upload.content_type)
        item = {
            "filename": filename,
            "contentType": upload.content_type,
            "kind": _kind(filename, upload.content_type),
            "text": text,
            "content": content,
            "size": len(content),
        }
        ocr_text = _ocr_text_from_visual_text(text)
        if ocr_text:
            item["ocrText"] = ocr_text
        extracted.append(item)
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
        return (
            _extract_with_textutil(filename, content)
            or _extract_office_text_with_soffice(filename, content)
            or f"[Office document uploaded: {filename}; text extraction unavailable. Use rendered page images.]"
        )
    if suffix == ".pdf":
        return _extract_pdf_text(filename, content) or f"[PDF uploaded: {filename}]"
    if (content_type or "").startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return _visual_text_with_ocr(f"[Image uploaded for visual/layout reference: {filename}]", filename, content)[0]
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


def _extract_office_text_with_soffice(filename: str, content: bytes) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / _safe_filename(filename)
        source_path.write_bytes(content)
        try:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "txt", "--outdir", str(temp_path), str(source_path)],
                check=False,
                capture_output=True,
                timeout=OFFICE_TEXT_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""

        txt_path = source_path.with_suffix(".txt")
        if not txt_path.exists():
            matches = sorted(temp_path.glob("*.txt"))
            if not matches:
                return ""
            txt_path = matches[0]
        return _decode_text(txt_path.read_bytes()).strip()


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
            ai_filename, ai_content_type, ai_content = _optimize_image_for_ai(
                f"{filename}.page-{page_index}.png",
                image_content,
            )
            visual_text, ocr_text = _visual_text_with_ocr(
                f"[Rendered PDF page {page_index} from {filename} for visual/layout reference]",
                page_path.name,
                image_content,
            )
            entry = {
                "filename": ai_filename,
                "contentType": ai_content_type,
                "kind": "image",
                "text": visual_text,
                "content": ai_content,
                "size": len(ai_content),
                "originalSize": len(image_content),
                "derivedFrom": filename,
                "sourcePage": page_index,
            }
            if ocr_text:
                entry["ocrText"] = ocr_text
            rendered.append(
                entry
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


def _visual_text_with_ocr(placeholder: str, filename: str, content: bytes) -> tuple[str, str]:
    ocr_text = _extract_image_ocr(filename, content)
    if not ocr_text:
        return placeholder, ""
    return f"{placeholder}\n\nOCR text:\n{ocr_text}", ocr_text


def _ocr_text_from_visual_text(text: str) -> str:
    marker = "OCR text:"
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].strip()


def _extract_image_ocr(filename: str, content: bytes) -> str:
    if not IMAGE_OCR_ENABLED:
        return ""
    if not _looks_like_supported_image(content):
        return ""

    swift_bin = shutil.which("swift") or "/usr/bin/swift"
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "ocr_image.swift"
    if not Path(swift_bin).exists() or not script_path.exists():
        return ""

    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        suffix = ".png"

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / f"ocr-input{suffix}"
        image_path.write_bytes(content)
        try:
            result = subprocess.run(
                [swift_bin, str(script_path), str(image_path)],
                check=False,
                capture_output=True,
                timeout=IMAGE_OCR_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="ignore").strip()


def _optimize_image_for_ai(filename: str, content: bytes) -> tuple[str, str, bytes]:
    if not _looks_like_supported_image(content):
        return filename, _image_content_type(filename), content
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return filename, _image_content_type(filename), content

    try:
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            if image.width > AI_IMAGE_MAX_WIDTH:
                ratio = AI_IMAGE_MAX_WIDTH / image.width
                image = image.resize((AI_IMAGE_MAX_WIDTH, max(1, int(image.height * ratio))), Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=AI_IMAGE_JPEG_QUALITY, optimize=True)
    except (OSError, UnidentifiedImageError, ValueError):
        return filename, _image_content_type(filename), content

    optimized_name = f"{Path(filename).with_suffix('')}.ai.jpg"
    return optimized_name, "image/jpeg", output.getvalue()


def _image_content_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix in {".tif", ".tiff"}:
        return "image/tiff"
    return "image/png"


def _looks_like_supported_image(content: bytes) -> bool:
    return (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        or content.startswith(b"MM\x00*")
        or content.startswith(b"II*\x00")
    )
