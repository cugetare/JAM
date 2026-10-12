from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

LOGGER = logging.getLogger(__name__)
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_component(value: str, fallback: str = "Unknown", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:max_length].rstrip(" .")


def application_path(
    root: Path,
    company: str,
    title: str,
    job_id: str = "",
    location: str = "",
    today: date | None = None,
) -> Path:
    company_part = sanitize_component(company, "Unknown_Company")
    title_part = sanitize_component(title, "Unknown_Role")
    if job_id.strip():
        leaf = f"{sanitize_component(job_id)}_{title_part}"
    else:
        month = (today or datetime.now().astimezone().date()).strftime("%Y-%m")
        location_part = sanitize_component(location, "Unknown_Location")
        leaf = f"{month}_{title_part}_{location_part}"
    return root / company_part / leaf


def create_directory_tree(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Application directory already exists: {path}")
    for relative in (
        "00_JD",
        "01_Application/CV",
        "01_Application/Cover_Letter",
        "02_Submission/confirmation",
        "03_Communication",
        "04_Interview",
    ):
        (path / relative).mkdir(parents=True, exist_ok=False)


def write_new_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def write_new_json(path: Path, data: dict[str, object]) -> None:
    write_new_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def copy_new(source: Path, destination: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Master document does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite: {destination}")
    shutil.copy2(source, destination)
    return destination


def next_version_path(directory: Path, stem: str, suffix: str) -> Path:
    for version in range(1, 100):
        candidate = directory / f"{stem}_v{version:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"No available document version for {stem}.")


def open_path(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")
    if sys.platform == "win32":
        import os

        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    LOGGER.info("Opened path: %s", target)
