from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from PIL import Image

from jam.services.candidate_profile import (
    active_candidate_profile_path,
    candidate_facts_for_ai,
    create_candidate_profile,
    import_cv,
    list_candidate_profiles,
    load_candidate_profile,
    parse_cv_docx,
    save_profile_photo,
)


def _cv(path: Path) -> None:
    document = Document()
    name = document.add_table(rows=1, cols=1)
    name.cell(0, 0).text = "Test Person"
    contact = document.add_table(rows=1, cols=1)
    contact.cell(0, 0).text = "Berlin | +49 123 456789 | test@example.com | www.example.com"
    table = document.add_table(rows=6, cols=2)
    table.cell(0, 0).text = "Professional Summary"
    table.cell(0, 1).text = "Senior systems engineer."
    table.cell(1, 0).text = "Education"
    table.cell(1, 1).text = "Diploma Engineer | 2009"
    table.cell(2, 0).text = "Competencies"
    skills = table.cell(2, 1)
    skills.text = ""
    header = skills.paragraphs[0]
    header.add_run("Systems Engineering").bold = True
    skills.add_paragraph("System architecture")
    language_header = skills.add_paragraph()
    language_header.add_run("Languages").bold = True
    skills.add_paragraph("English – C1")
    table.cell(3, 0).text = "Professional Experience"
    experience = table.cell(4, 0)
    table.cell(4, 1).merge(experience)
    experience.text = "10/2020 – 12/2025"
    experience.add_paragraph("System Lead")
    experience.add_paragraph("Example GmbH")
    experience.add_paragraph("Berlin")
    experience.add_paragraph("Led system architecture")
    experience.add_paragraph("Selected Achievements")
    experience.add_paragraph("Reduced defects")
    table.cell(5, 0).text = "Professional Training & Certifications"
    table.cell(5, 1).text = "Systems Engineering (2024)"
    document.save(path)


def test_parse_and_import_cv_preserves_structured_content(tmp_path: Path) -> None:
    source = tmp_path / "resume.docx"
    profile_path = tmp_path / "candidate_profile.json"
    _cv(source)

    parsed = parse_cv_docx(source, "EN")
    assert parsed.professional_summary == "Senior systems engineer."
    assert parsed.skill_groups[0].items == ["System architecture"]
    assert parsed.languages[0].proficiency == "C1"
    assert parsed.experience[0].achievements == ["Reduced defects"]

    imported = import_cv(source, "EN", profile_path)
    assert imported.identity.email == "test@example.com"
    assert imported.source_documents[0].sha256
    assert Path(imported.source_documents[0].archived_path).is_file()
    assert load_candidate_profile(profile_path).cv_versions["EN"].experience
    assert '"cv"' in candidate_facts_for_ai(profile_path, tmp_path / "legacy.md")


def test_legacy_facts_are_used_until_a_cv_is_imported(tmp_path: Path) -> None:
    legacy = tmp_path / "facts.md"
    legacy.write_text("verified legacy facts", encoding="utf-8")
    assert (
        candidate_facts_for_ai(tmp_path / "missing.json", legacy)
        == "verified legacy facts"
    )


def test_multiple_profiles_and_local_photo(tmp_path: Path) -> None:
    primary = tmp_path / "candidate_profile.json"
    first, first_path = create_candidate_profile(primary, "Second Candidate")

    profiles = list_candidate_profiles(primary)
    assert [profile.display_name for profile in profiles] == ["Second Candidate"]
    assert active_candidate_profile_path(primary, first.profile_id) == first_path.resolve()

    image = BytesIO()
    Image.new("RGB", (32, 32), "navy").save(image, format="PNG")
    photo = save_profile_photo(first, first_path, primary, image.getvalue())

    assert photo.is_file()
    assert load_candidate_profile(first_path).photo_path == str(photo.resolve())
