from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from jam.domain.models import Application

DEFAULT_COLUMNS = {
    "Bewerbungsdatum": "application_date",
    "Unternehmen": "company",
    "Position": "job_title",
    "Job-ID": "job_id",
    "Standort": "location",
    "Quelle": "source",
    "Ansprechpartner": "contact_name",
    "Bewerbungsart / Sprache": "application_language",
    "Status": "status",
    "Ergebnis": "final_application_notes",
    "Notizen": "personal_notes",
}


def preview_rows(
    applications: Iterable[Application],
    mapping: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    columns = mapping or DEFAULT_COLUMNS
    return [
        {heading: str(getattr(app, field, "") or "") for heading, field in columns.items()}
        for app in applications
    ]


def export_bewerbungsliste(
    path: str | Path,
    applications: Iterable[Application],
    *,
    mapping: dict[str, str] | None = None,
    sheet_name: str = "Bewerbungsliste",
) -> tuple[int, int]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    columns = mapping or DEFAULT_COLUMNS
    if target.exists():
        workbook = load_workbook(target)
    else:
        workbook = Workbook()
        workbook.active.title = sheet_name
    sheet = (
        workbook[sheet_name]
        if sheet_name in workbook.sheetnames
        else workbook.create_sheet(sheet_name)
    )

    headers = [cell.value for cell in sheet[1]] if sheet.max_row else []
    if not any(headers):
        headers = list(columns)
        for column_index, heading in enumerate(headers, start=1):
            sheet.cell(1, column_index, heading)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{sheet.cell(1, len(headers)).coordinate}"
    else:
        for heading in columns:
            if heading not in headers:
                headers.append(heading)
                sheet.cell(1, len(headers), heading)

    job_id_column = headers.index("Job-ID") + 1 if "Job-ID" in headers else 0
    existing_job_ids = (
        {
            str(sheet.cell(row, job_id_column).value or "").strip()
            for row in range(2, sheet.max_row + 1)
        }
        if job_id_column
        else set()
    )
    company_idx = headers.index("Unternehmen") + 1 if "Unternehmen" in headers else 0
    position_idx = headers.index("Position") + 1 if "Position" in headers else 0
    existing_fallback = (
        {
            (
                str(sheet.cell(row, company_idx).value or "").casefold(),
                str(sheet.cell(row, position_idx).value or "").casefold(),
            )
            for row in range(2, sheet.max_row + 1)
        }
        if company_idx and position_idx
        else set()
    )

    added = skipped = 0
    for row in preview_rows(applications, columns):
        job_id = row.get("Job-ID", "").strip()
        fallback = (
            row.get("Unternehmen", "").casefold(),
            row.get("Position", "").casefold(),
        )
        if (job_id and job_id in existing_job_ids) or (
            not job_id and fallback in existing_fallback
        ):
            skipped += 1
            continue
        sheet.append([row.get(header, "") for header in headers])
        if job_id:
            existing_job_ids.add(job_id)
        existing_fallback.add(fallback)
        added += 1

    workbook.save(target)
    return added, skipped
