from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from jam.services.documents import render_template, template_tokens

TOKENS = (
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
)


def _template(path: Path) -> None:
    document = Document()
    document.add_paragraph("WORKING TEMPLATE - remove me")
    for token in TOKENS:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(f"{{{{{token}}}}}")
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), "DDEBF7")
        run._element.get_or_add_rPr().append(shading)
    document.save(path)


def test_explicit_template_rendering_is_copy_only_and_removes_optional_lines(
    tmp_path: Path,
) -> None:
    source = tmp_path / "master.docx"
    destination = tmp_path / "generated.docx"
    _template(source)
    original = source.read_bytes()
    values = {token: f"value for {token}" for token in TOKENS}
    values["OPTIONAL_CONTEXT_PARAGRAPH"] = ""

    render_template(
        source,
        destination,
        values,
        removable_tokens={"OPTIONAL_CONTEXT_PARAGRAPH"},
    )

    assert source.read_bytes() == original
    assert template_tokens(destination) == set()
    generated = Document(destination)
    text = "\n".join(paragraph.text for paragraph in generated.paragraphs)
    assert "WORKING TEMPLATE" not in text
    assert "OPTIONAL_CONTEXT" not in text
    assert "value for COMPANY_NAME" in text
    assert not any(
        run._element.xpath(".//w:shd")
        for paragraph in generated.paragraphs
        for run in paragraph.runs
    )


def test_template_render_refuses_overwrite_and_missing_fields(tmp_path: Path) -> None:
    source = tmp_path / "master.docx"
    destination = tmp_path / "generated.docx"
    _template(source)
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        render_template(source, destination, {})

    destination.unlink()
    with pytest.raises(ValueError, match="Missing template fields"):
        render_template(source, destination, {"COMPANY_NAME": "Example"})
