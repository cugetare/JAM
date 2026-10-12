from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 5

APPLICATION_COLUMNS = """
company TEXT NOT NULL,
job_title TEXT NOT NULL,
job_id TEXT NOT NULL DEFAULT '',
location TEXT NOT NULL DEFAULT '',
country TEXT NOT NULL DEFAULT '',
job_url TEXT NOT NULL DEFAULT '',
source TEXT NOT NULL DEFAULT '',
contact_name TEXT NOT NULL DEFAULT '',
contact_email TEXT NOT NULL DEFAULT '',
application_language TEXT NOT NULL DEFAULT 'DE',
job_description_text TEXT NOT NULL DEFAULT '',
application_strategy TEXT NOT NULL DEFAULT '',
personal_notes TEXT NOT NULL DEFAULT '',
salary_expectation TEXT NOT NULL DEFAULT '',
work_model TEXT NOT NULL DEFAULT '',
office_days TEXT NOT NULL DEFAULT '',
application_date TEXT NOT NULL DEFAULT '',
status TEXT NOT NULL DEFAULT 'Identified',
status_updated_at TEXT NOT NULL,
next_action TEXT NOT NULL DEFAULT '',
next_action_date TEXT NOT NULL DEFAULT '',
cv_file TEXT NOT NULL DEFAULT '',
cover_letter_file TEXT NOT NULL DEFAULT '',
confirmation_file TEXT NOT NULL DEFAULT '',
finalized_cv_pdf TEXT NOT NULL DEFAULT '',
finalized_cover_letter_pdf TEXT NOT NULL DEFAULT '',
finalized_cv_source TEXT NOT NULL DEFAULT '',
finalized_cover_letter_source TEXT NOT NULL DEFAULT '',
finalized_at TEXT NOT NULL DEFAULT '',
finalization_manifest TEXT NOT NULL DEFAULT '',
application_directory TEXT NOT NULL UNIQUE,
cv_master_used TEXT NOT NULL DEFAULT '',
cover_letter_master_used TEXT NOT NULL DEFAULT '',
match_score TEXT NOT NULL DEFAULT '',
match_summary TEXT NOT NULL DEFAULT '',
strengths TEXT NOT NULL DEFAULT '',
transferable_experience TEXT NOT NULL DEFAULT '',
gaps TEXT NOT NULL DEFAULT '',
risks TEXT NOT NULL DEFAULT '',
recommended_cv_changes TEXT NOT NULL DEFAULT '',
cover_letter_draft TEXT NOT NULL DEFAULT '',
final_application_notes TEXT NOT NULL DEFAULT '',
company_address_line_1 TEXT NOT NULL DEFAULT '',
company_address_line_2 TEXT NOT NULL DEFAULT '',
cover_contact_line TEXT NOT NULL DEFAULT '',
cover_salutation TEXT NOT NULL DEFAULT '',
cover_motivation TEXT NOT NULL DEFAULT '',
cover_relevant_experience TEXT NOT NULL DEFAULT '',
cover_value_proposition TEXT NOT NULL DEFAULT '',
cover_optional_context TEXT NOT NULL DEFAULT '',
cover_closing TEXT NOT NULL DEFAULT '',
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {APPLICATION_COLUMNS}
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_job_identity
                    ON applications(company, job_id) WHERE job_id <> '';
                CREATE TABLE IF NOT EXISTS status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                    old_status TEXT NOT NULL DEFAULT '',
                    new_status TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS filesystem_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
                    operation TEXT NOT NULL,
                    source_path TEXT NOT NULL DEFAULT '',
                    destination_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
                    run_type TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reasoning_effort TEXT NOT NULL DEFAULT '',
                    communication_language TEXT NOT NULL DEFAULT 'EN',
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
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_application
                    ON agent_runs(application_id, created_at DESC);
                """
            )
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
                )
                version = SCHEMA_VERSION
            else:
                version = int(row["version"])

            def add_column_if_missing(column: str, definition: str) -> None:
                existing = {
                    item["name"]
                    for item in connection.execute("PRAGMA table_info(applications)")
                }
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE applications ADD COLUMN {column} {definition}"
                    )

            def add_agent_column_if_missing(
                column: str, definition: str
            ) -> None:
                existing = {
                    item["name"]
                    for item in connection.execute("PRAGMA table_info(agent_runs)")
                }
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE agent_runs ADD COLUMN {column} {definition}"
                    )

            if version == 1:
                for column in (
                    "company_address_line_1",
                    "company_address_line_2",
                    "cover_contact_line",
                    "cover_salutation",
                    "cover_motivation",
                    "cover_relevant_experience",
                    "cover_value_proposition",
                    "cover_optional_context",
                    "cover_closing",
                ):
                    add_column_if_missing(column, "TEXT NOT NULL DEFAULT ''")
                connection.execute("UPDATE schema_version SET version = 2")
                version = 2
            if version == 2:
                connection.execute("UPDATE schema_version SET version = 3")
                version = 3
            if version == 3:
                for column in (
                    "finalized_cv_pdf",
                    "finalized_cover_letter_pdf",
                    "finalized_cv_source",
                    "finalized_cover_letter_source",
                    "finalized_at",
                    "finalization_manifest",
                ):
                    add_column_if_missing(column, "TEXT NOT NULL DEFAULT ''")
                connection.execute("UPDATE schema_version SET version = 4")
                version = 4
            if version == 4:
                add_agent_column_if_missing(
                    "communication_language",
                    "TEXT NOT NULL DEFAULT 'EN'",
                )
                connection.execute("UPDATE schema_version SET version = 5")
                version = 5
            if version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema {version} is not supported; expected {SCHEMA_VERSION}."
                )
