import asyncio
import io
import subprocess
from pathlib import Path

from fastapi import UploadFile

from app.extractor import extract_uploaded_files, extract_visual_references


def test_pdf_upload_is_rendered_into_visual_reference_images(monkeypatch):
    def fake_run(command, check, capture_output, timeout):
        assert command[:3] == ["pdftoppm", "-png", "-r"]
        output_prefix = Path(command[-1])
        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        output_prefix.with_name(output_prefix.name + "-1.png").write_bytes(b"page one png")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("app.extractor.subprocess.run", fake_run)

    visuals = extract_visual_references("layout.pdf", b"%PDF demo", "application/pdf")

    assert [item["filename"] for item in visuals] == ["layout.pdf.page-1.png"]
    assert visuals[0]["kind"] == "image"
    assert visuals[0]["derivedFrom"] == "layout.pdf"
    assert visuals[0]["content"] == b"page one png"
    assert "PDF page 1" in visuals[0]["text"]


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
