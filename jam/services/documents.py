from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import RGBColor

TOKEN_PATTERN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def template_tokens(path: str | Path) -> set[str]:
    document = Document(path)
    return {
        match.group(1)
        for paragraph in document.paragraphs
        for match in TOKEN_PATTERN.finditer(paragraph.text)
    }


def _replace_paragraph_text(paragraph, text: str, *, accent: bool = False) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run._element.getparent().remove(run._element)
    else:
        paragraph.add_run(text)
    run = paragraph.runs[0]
    run.font.color.rgb = RGBColor(0, 84, 147) if accent else RGBColor(25, 25, 25)
    properties = run._element.get_or_add_rPr()
    for shading in properties.findall(qn("w:shd")):
        properties.remove(shading)


def _remove_paragraph(paragraph) -> None:
    element = paragraph._element
    element.getparent().remove(element)


def render_template(
    source: str | Path,
    destination: str | Path,
    values: Mapping[str, str],
    *,
    removable_tokens: set[str] | None = None,
) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(f"Cover-letter template does not exist: {source_path}")
    if destination_path.exists():
        raise FileExistsError(f"Refusing to overwrite: {destination_path}")

    document = Document(source_path)
    expected = template_tokens(source_path)
    unknown_values = set(values) - expected
    if unknown_values:
        raise ValueError(f"Unknown template fields: {', '.join(sorted(unknown_values))}")

    removable = removable_tokens or set()
    missing = expected - set(values) - removable
    if missing:
        raise ValueError(f"Missing template fields: {', '.join(sorted(missing))}")

    for paragraph in list(document.paragraphs):
        original = paragraph.text
        tokens = set(TOKEN_PATTERN.findall(original))
        if not tokens:
            if original.startswith(("ARBEITSVORLAGE", "WORKING TEMPLATE")):
                _remove_paragraph(paragraph)
            continue
        if tokens <= removable and all(not values.get(token, "").strip() for token in tokens):
            _remove_paragraph(paragraph)
            continue
        rendered = original
        for token in tokens:
            rendered = rendered.replace(f"{{{{{token}}}}}", values.get(token, "").strip())
        _replace_paragraph_text(
            paragraph,
            rendered,
            accent="SUBJECT_LINE" in tokens,
        )

    unresolved = {
        match.group(1)
        for paragraph in document.paragraphs
        for match in TOKEN_PATTERN.finditer(paragraph.text)
    }
    if unresolved:
        raise ValueError(f"Unresolved template fields: {', '.join(sorted(unresolved))}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(destination_path)
    return destination_path
