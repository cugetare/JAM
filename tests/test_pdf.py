from __future__ import annotations

import subprocess
from pathlib import Path

from pypdf import PdfWriter

from jam.services.pdf import PdfInfo, convert_docx_to_pdf


def test_libreoffice_conversion_uses_isolated_profile_and_validates_pdf(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "working document.docx"
    destination = tmp_path / "final" / "application.pdf"
    executable = tmp_path / "soffice.exe"
    source.write_bytes(b"docx fixture")
    executable.write_bytes(b"executable fixture")
    captured: list[str] = []

    def fake_run(command, **_kwargs):
        captured.extend(command)
        output_directory = Path(command[command.index("--outdir") + 1])
        generated = output_directory / f"{source.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with generated.open("wb") as handle:
            writer.write(handle)
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr("jam.services.pdf.find_libreoffice", lambda: executable)
    monkeypatch.setattr("jam.services.pdf.subprocess.run", fake_run)

    info = convert_docx_to_pdf(source, destination)

    assert info.converter == "LibreOffice"
    assert info.page_count == 1
    assert destination.is_file()
    assert "--headless" in captured
    assert any(value.startswith("-env:UserInstallation=file:") for value in captured)


def test_word_is_used_if_libreoffice_conversion_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.docx"
    destination = tmp_path / "destination.pdf"
    source.write_bytes(b"docx fixture")
    expected = PdfInfo(destination, 1, 100, "hash", "Microsoft Word")

    monkeypatch.setattr(
        "jam.services.pdf.find_libreoffice", lambda: tmp_path / "soffice.exe"
    )
    monkeypatch.setattr(
        "jam.services.pdf._convert_with_libreoffice",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("LibreOffice failed")),
    )
    monkeypatch.setattr(
        "jam.services.pdf._convert_with_word", lambda *_args: expected
    )

    assert convert_docx_to_pdf(source, destination) == expected
