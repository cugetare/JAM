from pathlib import Path

from openpyxl import Workbook, load_workbook

from jam.domain.models import Application
from jam.services.excel import export_bewerbungsliste


def _application(job_id: str = "FS-100") -> Application:
    return Application(
        id=1,
        company="Fictional Systems GmbH",
        job_title="Senior Platform Engineer",
        job_id=job_id,
        location="Berlin",
        source="Company website",
        contact_name="Erika Beispiel",
        application_language="DE",
        application_date="2026-07-24",
        status="Applied",
        application_directory="C:/fictional",
    )


def test_excel_export_preserves_other_sheets_and_skips_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "Bewerbungsliste.xlsx"
    workbook = Workbook()
    workbook.active.title = "Notes"
    workbook["Notes"]["A1"] = "Do not modify"
    workbook.save(path)

    assert export_bewerbungsliste(path, [_application()]) == (1, 0)
    assert export_bewerbungsliste(path, [_application()]) == (0, 1)

    result = load_workbook(path)
    assert result["Notes"]["A1"].value == "Do not modify"
    assert result["Bewerbungsliste"].max_row == 2
