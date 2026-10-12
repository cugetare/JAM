from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jam.domain.models import ApplicationInput
from jam.persistence.repositories import ApplicationRepository


@dataclass(slots=True)
class ImportCandidate:
    company: str
    job_title: str
    job_id: str
    directory: Path
    cv_file: str = ""
    cover_letter_file: str = ""


def scan_existing(root: str | Path) -> list[ImportCandidate]:
    root_path = Path(root)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Import root is not a directory: {root_path}")
    candidates: list[ImportCandidate] = []
    for company_dir in sorted(path for path in root_path.iterdir() if path.is_dir()):
        for job_dir in sorted(path for path in company_dir.iterdir() if path.is_dir()):
            parts = job_dir.name.split("_", 1)
            is_month_prefix = bool(re.fullmatch(r"\d{4}-\d{2}", parts[0]))
            job_id = parts[0] if len(parts) == 2 and not is_month_prefix else ""
            title = parts[1] if job_id else job_dir.name
            docx_files = list(job_dir.rglob("*.docx"))
            cv = next((path for path in docx_files if "cv" in path.name.lower()), None)
            cover = next(
                (
                    path
                    for path in docx_files
                    if "cover" in path.name.lower() or "anschreiben" in path.name.lower()
                ),
                None,
            )
            candidates.append(
                ImportCandidate(
                    company=company_dir.name.replace("_", " "),
                    job_title=title.replace("_", " "),
                    job_id=job_id,
                    directory=job_dir.resolve(),
                    cv_file=str(cv) if cv else "",
                    cover_letter_file=str(cover) if cover else "",
                )
            )
    return candidates


def import_candidate(
    candidate: ImportCandidate,
    repository: ApplicationRepository,
    *,
    language: str = "DE",
) -> int:
    directory = str(candidate.directory.resolve())
    duplicate = repository.find_duplicate(candidate.company, candidate.job_id, directory)
    if duplicate:
        raise ValueError(f"Application is already imported as record {duplicate.id}.")
    app = repository.create(
        ApplicationInput(
            company=candidate.company,
            job_title=candidate.job_title,
            job_id=candidate.job_id,
            application_language=language,
            personal_notes="Imported from an existing directory; files were not modified.",
        ),
        application_directory=directory,
        cv_file=candidate.cv_file,
        cover_letter_file=candidate.cover_letter_file,
    )
    repository.log_filesystem(
        "import_existing_read_only", destination=directory, application_id=app.id
    )
    return app.id
