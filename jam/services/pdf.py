from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader

_VERSION_PATTERN = re.compile(r"_v(\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PdfInfo:
    path: Path
    page_count: int
    byte_size: int
    sha256: str
    converter: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def latest_docx(directory: Path, recorded_path: str = "") -> Path | None:
    candidates = {
        path.resolve()
        for path in directory.glob("*.docx")
        if path.is_file()
        and not path.name.startswith("~$")
        and "_submitted" not in path.stem.lower()
    }
    if recorded_path:
        recorded = Path(recorded_path)
        if (
            recorded.is_file()
            and recorded.suffix.lower() == ".docx"
            and "_submitted" not in recorded.stem.lower()
        ):
            candidates.add(recorded.resolve())
    if not candidates:
        return None

    def rank(path: Path) -> tuple[int, int, str]:
        match = _VERSION_PATTERN.search(path.stem)
        version = int(match.group(1)) if match else 0
        return version, path.stat().st_mtime_ns, path.name.casefold()

    return max(candidates, key=rank)


def find_libreoffice() -> Path | None:
    configured = os.environ.get("JAM_LIBREOFFICE_PATH", "").strip()
    candidates = [
        Path(configured) if configured else None,
        Path(shutil.which("soffice") or ""),
        Path(shutil.which("soffice.exe") or ""),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    for candidate in candidates:
        if candidate and str(candidate) not in {"", "."} and candidate.is_file():
            return candidate.resolve()
    return None


def preferred_pdf_converter() -> str:
    if find_libreoffice():
        return "LibreOffice"
    if sys.platform == "win32":
        return "Microsoft Word"
    return "Unavailable"


def _convert_with_libreoffice(
    executable: Path, source: Path, destination: Path
) -> PdfInfo:
    with TemporaryDirectory(prefix=".jam_libreoffice_", dir=destination.parent) as work:
        work_directory = Path(work)
        output_directory = work_directory / "output"
        profile_directory = work_directory / "profile"
        output_directory.mkdir()
        profile_directory.mkdir()
        command = [
            str(executable),
            f"-env:UserInstallation={profile_directory.resolve().as_uri()}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(output_directory.resolve()),
            str(source.resolve()),
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=creation_flags,
        )
        generated = output_directory / f"{source.stem}.pdf"
        if result.returncode != 0 or not generated.is_file():
            detail = (result.stderr or result.stdout or "no PDF was produced").strip()
            raise RuntimeError(
                f"LibreOffice could not export {source.name}: {detail}"
            )
        info = inspect_pdf(generated)
        generated.replace(destination)
        return replace(info, path=destination, converter="LibreOffice")


def _convert_with_word(source: Path, destination: Path) -> PdfInfo:
    if sys.platform != "win32":
        raise RuntimeError("Microsoft Word PDF export is available only on Windows.")
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise FileNotFoundError(f"DOCX source does not exist: {source}")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "Microsoft Word PDF export requires pywin32. "
            "Reinstall JAM dependencies from requirements.txt."
        ) from exc

    pythoncom.CoInitialize()
    word = None
    document = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(source.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
        )
        document.ExportAsFixedFormat(
            OutputFileName=str(destination.resolve()),
            ExportFormat=17,
            OpenAfterExport=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Microsoft Word could not export {source.name}. Close any blocked "
            f"Word dialogs and try again. Technical detail: {exc}"
        ) from exc
    finally:
        if document is not None:
            document.Close(SaveChanges=0)
        if word is not None:
            word.Quit(SaveChanges=0)
        pythoncom.CoUninitialize()
    return replace(inspect_pdf(destination), converter="Microsoft Word")


def convert_docx_to_pdf(source: Path, destination: Path) -> PdfInfo:
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise FileNotFoundError(f"DOCX source does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite PDF: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    if libreoffice := find_libreoffice():
        try:
            return _convert_with_libreoffice(libreoffice, source, destination)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            destination.unlink(missing_ok=True)
            errors.append(str(exc))
    if sys.platform == "win32":
        try:
            return _convert_with_word(source, destination)
        except (OSError, RuntimeError) as exc:
            destination.unlink(missing_ok=True)
            errors.append(str(exc))
    detail = " | ".join(errors) or "No supported local PDF converter was found."
    raise RuntimeError(f"DOCX-to-PDF conversion failed. {detail}")


def inspect_pdf(path: Path) -> PdfInfo:
    if not path.is_file():
        raise FileNotFoundError(f"Expected PDF was not created: {path}")
    if path.stat().st_size < 100 or path.read_bytes()[:5] != b"%PDF-":
        raise ValueError(f"Output is not a valid PDF file: {path}")
    try:
        page_count = len(PdfReader(path).pages)
    except Exception as exc:
        raise ValueError(f"PDF validation failed for {path.name}: {exc}") from exc
    if page_count < 1:
        raise ValueError(f"PDF contains no pages: {path}")
    return PdfInfo(
        path=path,
        page_count=page_count,
        byte_size=path.stat().st_size,
        sha256=file_sha256(path),
    )
