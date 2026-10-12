import sqlite3
from pathlib import Path

from jam.persistence import Database
from jam.persistence.database import APPLICATION_COLUMNS

NEW_COLUMNS = (
    "company_address_line_1",
    "company_address_line_2",
    "cover_contact_line",
    "cover_salutation",
    "cover_motivation",
    "cover_relevant_experience",
    "cover_value_proposition",
    "cover_optional_context",
    "cover_closing",
)

FINALIZATION_COLUMNS = (
    "finalized_cv_pdf",
    "finalized_cover_letter_pdf",
    "finalized_cv_source",
    "finalized_cover_letter_source",
    "finalized_at",
    "finalization_manifest",
)


def test_schema_v1_is_migrated_without_losing_application(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    legacy_columns = APPLICATION_COLUMNS
    for column in NEW_COLUMNS:
        legacy_columns = legacy_columns.replace(f"{column} TEXT NOT NULL DEFAULT '',\n", "")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (1)")
        connection.execute(
            f"CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, {legacy_columns})"
        )
        connection.execute(
            """INSERT INTO applications
               (company, job_title, status_updated_at, application_directory,
                created_at, updated_at)
               VALUES ('Legacy GmbH', 'Engineer', '2026-01-01', 'C:/legacy',
                       '2026-01-01', '2026-01-01')"""
        )

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(applications)")}
        company = connection.execute("SELECT company FROM applications").fetchone()[0]
    assert version == 5
    assert set(NEW_COLUMNS) <= columns
    assert set(FINALIZATION_COLUMNS) <= columns
    assert company == "Legacy GmbH"
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "agent_runs" in tables


def test_schema_v2_adds_agent_runs_without_changing_applications(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (2)")
        connection.execute(
            f"CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            f"{APPLICATION_COLUMNS})"
        )
        connection.execute(
            """INSERT INTO applications
               (company, job_title, status_updated_at, application_directory,
                created_at, updated_at)
               VALUES ('Preserved GmbH', 'Architect', '2026-01-01', 'C:/preserved',
                       '2026-01-01', '2026-01-01')"""
        )

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 5
        assert connection.execute("SELECT company FROM applications").fetchone()[0] == (
            "Preserved GmbH"
        )
        assert connection.execute("SELECT count(*) FROM agent_runs").fetchone()[0] == 0


def test_schema_v3_adds_pdf_finalization_evidence_columns(tmp_path: Path) -> None:
    path = tmp_path / "v3.sqlite3"
    legacy_columns = APPLICATION_COLUMNS
    for column in FINALIZATION_COLUMNS:
        legacy_columns = legacy_columns.replace(
            f"{column} TEXT NOT NULL DEFAULT '',\n", ""
        )
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (3)")
        connection.execute(
            f"CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            f"{legacy_columns})"
        )
        connection.execute(
            """INSERT INTO applications
               (company, job_title, status_updated_at, application_directory,
                created_at, updated_at)
               VALUES ('Evidence GmbH', 'Engineer', '2026-01-01', 'C:/evidence',
                       '2026-01-01', '2026-01-01')"""
        )

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(applications)")}
        company = connection.execute("SELECT company FROM applications").fetchone()[0]
    assert version == 5
    assert set(FINALIZATION_COLUMNS) <= columns
    assert company == "Evidence GmbH"


def test_schema_v4_adds_agent_communication_language_without_losing_runs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v4.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (4)")
        connection.execute(
            f"CREATE TABLE applications (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            f"{APPLICATION_COLUMNS})"
        )
        connection.execute(
            """CREATE TABLE agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER,
                run_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                reasoning_effort TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '',
                response_id TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        connection.execute(
            """INSERT INTO agent_runs
               (run_type, provider, model, reasoning_effort, status,
                prompt_version, input_hash, created_at)
               VALUES ('application_analysis', 'openai', 'test', 'low',
                       'completed', 'v1', 'hash', '2026-01-01')"""
        )

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        version = connection.execute("SELECT version FROM schema_version").fetchone()[0]
        row = connection.execute(
            "SELECT run_type, communication_language FROM agent_runs"
        ).fetchone()
    assert version == 5
    assert row == ("application_analysis", "EN")
