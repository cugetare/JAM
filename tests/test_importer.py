from pathlib import Path

import pytest

from jam.persistence import ApplicationRepository
from jam.services.importer import import_candidate, scan_existing


def test_scan_and_import_existing_directory_without_modification(
    tmp_path: Path, repository: ApplicationRepository
) -> None:
    root = tmp_path / "OldApplications"
    job = root / "Legacy_Industries" / "LI-7_Principal_Engineer"
    job.mkdir(parents=True)
    cv = job / "My_CV.docx"
    cv.write_bytes(b"unchanged")
    original_mtime = cv.stat().st_mtime_ns

    candidates = scan_existing(root)
    assert len(candidates) == 1
    assert candidates[0].company == "Legacy Industries"
    assert candidates[0].job_id == "LI-7"
    app_id = import_candidate(candidates[0], repository, language="EN")
    app = repository.get(app_id)
    assert app is not None
    assert app.application_directory == str(job.resolve())
    assert cv.read_bytes() == b"unchanged"
    assert cv.stat().st_mtime_ns == original_mtime

    with pytest.raises(ValueError, match="already imported"):
        import_candidate(candidates[0], repository, language="EN")
