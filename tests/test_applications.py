import json
from datetime import datetime
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter

from jam.domain.models import ApplicationInput
from jam.persistence import ApplicationRepository
from jam.services import ApplicationService
from jam.services.pdf import inspect_pdf


def _input(**changes: str) -> ApplicationInput:
    values = {
        "company": "Fictional Systems GmbH",
        "job_title": "Senior Platform Engineer",
        "job_id": "FS-100",
        "location": "Berlin",
        "application_language": "DE",
        "job_description_text": "Aufgaben: Build reliable local systems.",
    }
    values.update(changes)
    return ApplicationInput(**values)


def test_application_creation_builds_tree_and_copies_masters(
    configured_service: tuple[ApplicationService, dict[str, Path]],
) -> None:
    service, masters = configured_service
    app = service.create(_input())
    root = Path(app.application_directory)
    assert (root / "00_JD" / "JD_original.txt").read_text(encoding="utf-8").startswith("Aufgaben")
    assert (root / "00_JD" / "JD_metadata.json").exists()
    assert (root / "02_Submission" / "confirmation").is_dir()
    assert (root / "03_Communication").is_dir()
    assert Path(app.cv_file).read_bytes() == masters["cv_de"].read_bytes()
    assert Path(app.cover_letter_file).read_bytes() == masters["cover_de"].read_bytes()
    assert masters["cv_de"].read_bytes() == b"fictional cv_de"
    assert "_v01.docx" in app.cv_file


def test_duplicate_application_is_prevented(
    configured_service: tuple[ApplicationService, dict[str, Path]],
) -> None:
    service, _ = configured_service
    first = service.create(_input())
    with pytest.raises(ValueError, match="already exists"):
        service.create(_input())
    assert service.repository.get(first.id) is not None


def test_status_changes_keep_history(
    configured_service: tuple[ApplicationService, dict[str, Path]],
    repository: ApplicationRepository,
) -> None:
    service, _ = configured_service
    app = service.create(_input())
    repository.update(app.id, {"status": "Applied"}, status_note="Submitted in portal")
    history = repository.status_history(app.id)
    assert [entry.new_status for entry in history] == ["Applied", "Identified"]
    assert history[0].old_status == "Identified"
    assert history[0].note == "Submitted in portal"
    updated = repository.get(app.id)
    assert updated is not None
    assert updated.application_date == datetime.now().astimezone().date().isoformat()


def test_pre_submission_status_does_not_set_application_date(
    configured_service: tuple[ApplicationService, dict[str, Path]],
    repository: ApplicationRepository,
) -> None:
    service, _ = configured_service
    app = service.create(_input())
    updated = repository.update(app.id, {"status": "Preparing"})
    assert updated.application_date == ""


def test_working_document_version_is_copy_only(
    configured_service: tuple[ApplicationService, dict[str, Path]],
) -> None:
    service, _ = configured_service
    app = service.create(_input())
    original = Path(app.cv_file)
    new_version = service.create_working_document_version(app.id, "cv")
    assert original.exists()
    assert original.read_bytes() == new_version.read_bytes()
    assert new_version.name.endswith("_v02.docx")


def test_job_description_update_syncs_database_file_and_snapshot(
    configured_service: tuple[ApplicationService, dict[str, Path]],
) -> None:
    service, _ = configured_service
    app = service.create(_input())
    root = Path(app.application_directory)
    original = root / "00_JD" / "JD_original.txt"

    updated = service.update_job_description(
        app.id, "Updated responsibilities and requirements."
    )

    assert updated.job_description_text == "Updated responsibilities and requirements."
    assert original.read_text(encoding="utf-8").strip() == updated.job_description_text
    assert (root / "00_JD" / "JD_original_v01.txt").read_text(
        encoding="utf-8"
    ).startswith("Aufgaben")
    snapshot = (root / "02_Submission" / "application_data.json").read_text(
        encoding="utf-8"
    )
    assert "Updated responsibilities and requirements." in snapshot


def test_finalize_application_uses_latest_docx_and_records_evidence(
    configured_service: tuple[ApplicationService, dict[str, Path]],
    repository: ApplicationRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = configured_service
    app = service.create(_input())
    latest_cv = service.create_working_document_version(app.id, "cv")
    latest_cover = service.create_working_document_version(app.id, "cover_letter")

    def fake_convert(source: Path, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with destination.open("wb") as handle:
            writer.write(handle)
        return inspect_pdf(destination)

    monkeypatch.setattr(
        "jam.services.applications.convert_docx_to_pdf", fake_convert
    )
    result = service.finalize_application(app.id)

    assert result.cv_source == latest_cv
    assert result.cover_letter_source == latest_cover
    assert result.cv_pdf.is_file()
    assert result.cover_letter_pdf.is_file()
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["sources"]["cv"]["sha256"]
    assert manifest["outputs"]["cv"]["page_count"] == 1
    updated = repository.get(app.id)
    assert updated is not None
    assert updated.status == "Ready to Apply"
    assert updated.application_date == ""
    assert updated.finalized_cv_pdf == str(result.cv_pdf)
    assert updated.finalized_cover_letter_source == str(latest_cover)
    history = repository.status_history(app.id)
    assert history[0].note == "Final PDF application package created"


def test_cover_letter_generation_uses_explicit_tokens_and_new_version(
    configured_service: tuple[ApplicationService, dict[str, Path]],
    repository: ApplicationRepository,
) -> None:
    service, masters = configured_service
    template = Document()
    template.add_paragraph("WORKING TEMPLATE - remove me")
    for token in (
        "COMPANY_NAME",
        "CONTACT_LINE",
        "COMPANY_ADDRESS_LINE_1",
        "COMPANY_ADDRESS_LINE_2",
        "DATE",
        "SUBJECT_LINE",
        "SALUTATION",
        "MOTIVATION_PARAGRAPH",
        "RELEVANT_EXPERIENCE_PARAGRAPH",
        "VALUE_PROPOSITION_PARAGRAPH",
        "OPTIONAL_CONTEXT_PARAGRAPH",
        "CLOSING_PARAGRAPH",
    ):
        template.add_paragraph(f"{{{{{token}}}}}")
    template.save(masters["cover_de"])
    master_bytes = masters["cover_de"].read_bytes()

    app = service.create(_input(), copy_cv=False)
    repository.update(
        app.id,
        {
            "cover_motivation": "Meine Motivation.",
            "cover_relevant_experience": "Meine Erfahrung.",
            "cover_value_proposition": "Mein Mehrwert.",
            "cover_closing": "Ich freue mich auf das Gespräch.",
        },
    )
    generated = service.generate_cover_letter(app.id)

    assert generated.name.endswith("_v02.docx")
    assert masters["cover_de"].read_bytes() == master_bytes
    text = "\n".join(paragraph.text for paragraph in Document(generated).paragraphs)
    assert "Bewerbung als Senior Platform Engineer | Kennziffer FS-100" in text
    assert "Meine Motivation." in text
    assert "{{" not in text
    assert "WORKING TEMPLATE" not in text
