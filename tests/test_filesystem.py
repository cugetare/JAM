from datetime import date
from pathlib import Path

import pytest

from jam.services.filesystem import (
    application_path,
    copy_new,
    next_version_path,
    sanitize_component,
)


def test_directory_naming_with_and_without_job_id(tmp_path: Path) -> None:
    with_id = application_path(tmp_path, "ACME: GmbH", "Senior / Engineer", "R-42", "Berlin")
    assert with_id == tmp_path / "ACME_GmbH" / "R-42_Senior_Engineer"

    without_id = application_path(
        tmp_path,
        "ACME",
        "Platform Engineer",
        "",
        "München",
        today=date(2026, 7, 1),
    )
    assert without_id == tmp_path / "ACME" / "2026-07_Platform_Engineer_München"


def test_windows_reserved_and_invalid_names_are_sanitized() -> None:
    assert sanitize_component("CON") == "_CON"
    assert sanitize_component("  Staff: Engineer?  ") == "Staff_Engineer"


def test_copy_never_overwrites_and_versions_increment(tmp_path: Path) -> None:
    source = tmp_path / "master.docx"
    source.write_bytes(b"master")
    target = tmp_path / "CV_v01.docx"
    copy_new(source, target)
    assert source.read_bytes() == target.read_bytes()
    with pytest.raises(FileExistsError):
        copy_new(source, target)
    assert next_version_path(tmp_path, "CV", ".docx").name == "CV_v02.docx"
