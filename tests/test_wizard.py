from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from docx import Document

from jam.ui.app import _cover_from_application, _wizard_resume_step


def _application(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "finalized_at": "",
        "status": "Reviewing",
        "cover_salutation": "",
        "cover_motivation": "",
        "cover_relevant_experience": "",
        "cover_value_proposition": "",
        "cover_optional_context": "",
        "cover_closing": "",
        "cover_letter_file": "",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_resume_step_is_derived_from_persisted_application_state(
    tmp_path: Path,
) -> None:
    completed_cover = tmp_path / "cover.docx"
    document = Document()
    document.add_paragraph("Completed cover letter")
    document.save(completed_cover)

    assert _wizard_resume_step(_application()) == 2
    assert _wizard_resume_step(_application(status="Preparing")) == 3
    assert (
        _wizard_resume_step(
            _application(
                cover_motivation="Motivation",
                cover_relevant_experience="Experience",
                cover_value_proposition="Value",
                cover_closing="Closing",
                cover_letter_file=str(completed_cover),
            )
        )
        == 4
    )
    assert _wizard_resume_step(_application(finalized_at="2026-07-28")) == 4


def test_cover_content_is_restored_for_resumed_wizard() -> None:
    app = _application(
        cover_salutation="Dear Hiring Team,",
        cover_motivation="Motivation",
        cover_relevant_experience="Experience",
        cover_value_proposition="Value",
        cover_optional_context="Context",
        cover_closing="Closing",
    )

    content = _cover_from_application(app)

    assert content is not None
    assert content.motivation == "Motivation"
    assert content.optional_context == "Context"


def test_incomplete_cover_is_not_treated_as_accepted() -> None:
    assert _cover_from_application(_application(cover_motivation="Only one field")) is None
