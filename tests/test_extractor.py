import asyncio
import io
import subprocess
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from app.extractor import extract_text, extract_uploaded_files, extract_visual_references


def test_pdf_upload_is_rendered_into_visual_reference_images(monkeypatch):
    def fake_run(command, check, capture_output, timeout):
        assert command[:3] == ["pdftoppm", "-png", "-r"]
        output_prefix = Path(command[-1])
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_prefix.with_name(output_prefix.name + "-1.png").write_bytes(b"page one png")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)
    monkeypatch.setattr("app.extractor._extract_image_ocr", lambda filename, content: "")

    visuals = extract_visual_references("layout.pdf", b"%PDF demo", "application/pdf")

    assert [item["filename"] for item in visuals] == ["layout.pdf.page-1.png"]
    assert visuals[0]["kind"] == "image"
    assert visuals[0]["derivedFrom"] == "layout.pdf"
    assert visuals[0]["content"] == b"page one png"
    assert "PDF page 1" in visuals[0]["text"]


def test_pdf_rendered_visual_text_includes_ocr_when_available(monkeypatch):
    def fake_run(command, check, capture_output, timeout):
        output_prefix = Path(command[-1])
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_prefix.with_name(output_prefix.name + "-1.png").write_bytes(b"page one png")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)
    monkeypatch.setattr("app.extractor._extract_image_ocr", lambda filename, content: "温莎城堡\n204×234\n被里")

    visuals = extract_visual_references("layout.pdf", b"%PDF demo", "application/pdf")

    assert visuals[0]["ocrText"] == "温莎城堡\n204×234\n被里"
    assert "OCR text" in visuals[0]["text"]
    assert "204×234" in visuals[0]["text"]


def test_pdf_rendered_visual_reference_is_optimized_for_ai(monkeypatch):
    image = Image.new("RGB", (1600, 1000), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    def fake_run(command, check, capture_output, timeout):
        output_prefix = Path(command[-1])
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_prefix.with_name(output_prefix.name + "-1.png").write_bytes(buffer.getvalue())
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)
    monkeypatch.setattr("app.extractor._extract_image_ocr", lambda filename, content: "温莎城堡")

    visuals = extract_visual_references("layout.pdf", b"%PDF demo", "application/pdf")

    assert visuals[0]["filename"] == "layout.pdf.page-1.ai.jpg"
    assert visuals[0]["contentType"] == "image/jpeg"
    assert visuals[0]["content"].startswith(b"\xff\xd8\xff")
    assert visuals[0]["originalSize"] == len(buffer.getvalue())


def test_office_upload_is_converted_to_pdf_then_rendered(monkeypatch):
    calls = []

    def fake_run(command, check, capture_output, timeout):
        calls.append(command)
        if command[0] == "soffice":
            outdir = Path(command[command.index("--outdir") + 1])
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "transfer.pdf").write_bytes(b"%PDF converted")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if command[0] == "pdftoppm":
            output_prefix = Path(command[-1])
            output_prefix.with_name(output_prefix.name + "-1.png").write_bytes(b"doc page png")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError(command)

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)
    monkeypatch.setattr("app.extractor._extract_image_ocr", lambda filename, content: "")

    visuals = extract_visual_references("transfer.docx", b"docx bytes", None)

    assert calls[0][0] == "soffice"
    assert calls[1][0] == "pdftoppm"
    assert visuals[0]["filename"] == "transfer.docx.page-1.png"
    assert visuals[0]["derivedFrom"] == "transfer.docx"


def test_uploaded_files_include_originals_and_derived_visuals(monkeypatch):
    def fake_visuals(filename, content, content_type):
        return [
            {
                "filename": f"{filename}.page-1.png",
                "contentType": "image/png",
                "kind": "image",
                "text": f"[Rendered page image from {filename}]",
                "content": b"page png",
                "size": 8,
                "derivedFrom": filename,
            }
        ]

    monkeypatch.setattr("app.extractor.extract_visual_references", fake_visuals)

    upload = UploadFile(file=io.BytesIO(b"%PDF demo"), filename="layout.pdf")
    extracted = asyncio.run(extract_uploaded_files([upload]))

    assert [item["filename"] for item in extracted] == ["layout.pdf", "layout.pdf.page-1.png"]
    assert extracted[0]["kind"] == "pdf"
    assert extracted[1]["kind"] == "image"


def test_doc_text_extraction_uses_soffice_when_textutil_returns_empty(monkeypatch):
    def fake_run(command, check, capture_output, timeout):
        if command[0] == "textutil":
            return subprocess.CompletedProcess(command, 0, b"", b"not a textutil-readable doc")
        if command[0] == "soffice":
            source = Path(command[-1])
            source.with_suffix(".txt").write_text("花名\t筝筝日上\n品名\t天丝棉绣花三/四件套", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise AssertionError(command)

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)

    text = extract_text("transfer.doc", b"binary office bytes", None)

    assert "筝筝日上" in text
    assert "天丝棉绣花" in text


def test_doc_text_extraction_does_not_decode_binary_when_extractors_fail(monkeypatch):
    def fake_run(command, check, capture_output, timeout):
        if command[0] == "textutil":
            return subprocess.CompletedProcess(command, 0, b"", b"not a textutil-readable doc")
        if command[0] == "soffice":
            return subprocess.CompletedProcess(command, 1, b"", b"conversion failed")
        raise AssertionError(command)

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)

    text = extract_text("transfer.doc", b"\xd0\xcf\x11\xe0" + (b"\x00" * 100), None)

    assert "text extraction unavailable" in text
    assert "\xd0\xcf" not in text


def test_image_ocr_is_skipped_for_non_image_bytes(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("OCR subprocess should not run for invalid image bytes")

    monkeypatch.setattr("app.extractor.subprocess.run", fail_run)

    text = extract_text("layout.png", b"fake image bytes", "image/png")

    assert "Image uploaded" in text
    assert "OCR text" not in text
