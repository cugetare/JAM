from __future__ import annotations

from pathlib import Path

import pytest

from jam.config import Settings
from jam.persistence import ApplicationRepository, Database
from jam.services import ApplicationService


@pytest.fixture
def repository(tmp_path: Path) -> ApplicationRepository:
    database = Database(tmp_path / "jam.sqlite3")
    database.initialize()
    return ApplicationRepository(database)


@pytest.fixture
def configured_service(
    tmp_path: Path, repository: ApplicationRepository
) -> tuple[ApplicationService, dict[str, Path]]:
    masters = {
        "cv_de": tmp_path / "masters" / "CV_DE.docx",
        "cv_en": tmp_path / "masters" / "CV_EN.docx",
        "cover_de": tmp_path / "masters" / "Cover_DE.docx",
        "cover_en": tmp_path / "masters" / "Cover_EN.docx",
    }
    for name, path in masters.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fictional {name}".encode())
    settings = Settings(
        applications_root=str(tmp_path / "Applications"),
        database_path=str(tmp_path / "jam.sqlite3"),
        german_cv_master=str(masters["cv_de"]),
        english_cv_master=str(masters["cv_en"]),
        german_cover_letter_template=str(masters["cover_de"]),
        english_cover_letter_template=str(masters["cover_en"]),
        bewerbungsliste_path=str(tmp_path / "Bewerbungsliste.xlsx"),
        applicant_name="Test_Person",
    )
    return ApplicationService(settings, repository), masters
