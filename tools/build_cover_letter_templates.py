from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "templates"
BLUE = RGBColor(0, 84, 147)
INK = RGBColor(25, 25, 25)
MUTED = RGBColor(95, 95, 95)
TOKEN_FILL = "DDEBF7"


def format_run(
    run,
    *,
    size: float = 10.5,
    color: RGBColor = INK,
    bold: bool = False,
    italic: bool = False,
    token: bool = False,
) -> None:
    run.font.name = "Calibri"
    fonts = run._element.get_or_add_rPr().rFonts
    fonts.set(qn("w:ascii"), "Calibri")
    fonts.set(qn("w:hAnsi"), "Calibri")
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.bold = bold
    run.italic = italic
    if token:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:fill"), TOKEN_FILL)
        run._element.get_or_add_rPr().append(shading)


def paragraph(
    doc: Document,
    text: str = "",
    *,
    after: float = 0,
    before: float = 0,
    size: float = 10.5,
    color: RGBColor = INK,
    bold: bool = False,
    italic: bool = False,
    token: bool = False,
    alignment=None,
):
    item = doc.add_paragraph()
    item.paragraph_format.space_before = Pt(before)
    item.paragraph_format.space_after = Pt(after)
    item.paragraph_format.line_spacing = 1.1
    if alignment is not None:
        item.alignment = alignment
    run = item.add_run(text)
    format_run(
        run,
        size=size,
        color=color,
        bold=bold,
        italic=italic,
        token=token,
    )
    return item


def configure(doc: Document, title: str) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(1.35)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.7)
    section.right_margin = Cm(1.7)
    section.header_distance = Cm(1.25)
    section.footer_distance = Cm(1.25)

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    fonts = normal._element.get_or_add_rPr().rFonts
    fonts.set(qn("w:ascii"), "Calibri")
    fonts.set(qn("w:hAnsi"), "Calibri")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1

    doc.core_properties.author = "Dan Glogoveanu"
    doc.core_properties.last_modified_by = "JAM"
    doc.core_properties.title = title
    doc.core_properties.subject = "JAM deterministic cover-letter template"
    doc.core_properties.keywords = "cover letter, template, JAM"


def identity_block(doc: Document, working_note: str) -> None:
    paragraph(
        doc,
        working_note,
        after=5,
        size=7.5,
        color=MUTED,
        italic=True,
    )
    paragraph(doc, "Dan Glogoveanu", after=0, size=15.5, color=BLUE, bold=True)
    paragraph(
        doc,
        "Sindelfingen, Deutschland  |  +49 (0) 1520 81 51 917  |  "
        "dan@glogoveanu.eu  |  www.glogoveanu.eu",
        after=16,
        size=9,
        color=INK,
    )


def token_block(doc: Document, *, city_date: str, closing: str) -> None:
    for token in (
        "{{COMPANY_NAME}}",
        "{{CONTACT_LINE}}",
        "{{COMPANY_ADDRESS_LINE_1}}",
        "{{COMPANY_ADDRESS_LINE_2}}",
    ):
        paragraph(doc, token, color=BLUE, token=True)

    paragraph(
        doc,
        city_date,
        after=14,
        color=BLUE,
        token=True,
        alignment=WD_ALIGN_PARAGRAPH.RIGHT,
    )
    paragraph(doc, "{{SUBJECT_LINE}}", after=12, color=BLUE, bold=True, token=True)
    paragraph(doc, "{{SALUTATION}}", after=9, color=BLUE, token=True)
    for token in (
        "{{MOTIVATION_PARAGRAPH}}",
        "{{RELEVANT_EXPERIENCE_PARAGRAPH}}",
        "{{VALUE_PROPOSITION_PARAGRAPH}}",
        "{{OPTIONAL_CONTEXT_PARAGRAPH}}",
        "{{CLOSING_PARAGRAPH}}",
    ):
        paragraph(doc, token, after=7, color=BLUE, token=True)
    paragraph(doc, closing, before=4, after=15)
    paragraph(doc, "Dan Glogoveanu", color=BLUE, bold=True)


def build(language: str) -> Path:
    doc = Document()
    if language == "DE":
        configure(doc, "Anschreiben - JAM Vorlage")
        identity_block(
            doc,
            "ARBEITSVORLAGE - vor dem Versand alle {{...}} Platzhalter ersetzen oder entfernen.",
        )
        token_block(
            doc,
            city_date="Sindelfingen, {{DATE}}",
            closing="Mit freundlichen Grüßen",
        )
        target = OUTPUT / "Cover_DE.docx"
    else:
        configure(doc, "Cover Letter - JAM Template")
        identity_block(
            doc,
            "WORKING TEMPLATE - replace or remove every {{...}} placeholder before sending.",
        )
        token_block(
            doc,
            city_date="Sindelfingen, {{DATE}}",
            closing="Kind regards,",
        )
        target = OUTPUT / "Cover_EN.docx"
    doc.save(target)
    return target


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for language in ("DE", "EN"):
        print(build(language))


if __name__ == "__main__":
    main()
