from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jam.domain.models import (
    SUBMITTED_STATUSES,
    Application,
    ApplicationInput,
    StatusHistory,
)

from .database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ApplicationRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(
        self,
        data: ApplicationInput,
        *,
        application_directory: str,
        cv_file: str = "",
        cover_letter_file: str = "",
        cv_master_used: str = "",
        cover_letter_master_used: str = "",
    ) -> Application:
        data.validate()
        now = _now()
        values = data.to_dict() | {
            "status_updated_at": now,
            "cv_file": cv_file,
            "cover_letter_file": cover_letter_file,
            "confirmation_file": "",
            "application_directory": application_directory,
            "cv_master_used": cv_master_used,
            "cover_letter_master_used": cover_letter_master_used,
            "created_at": now,
            "updated_at": now,
        }
        columns = list(values)
        sql = (
            f"INSERT INTO applications ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})"
        )
        with self.database.connect() as connection:
            try:
                cursor = connection.execute(sql, tuple(values[column] for column in columns))
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ValueError("This application already exists.") from exc
                raise
            app_id = int(cursor.lastrowid)
            connection.execute(
                """INSERT INTO status_history
                   (application_id, old_status, new_status, changed_at, note)
                   VALUES (?, '', ?, ?, 'Application created')""",
                (app_id, data.status, now),
            )
        result = self.get(app_id)
        assert result is not None
        return result

    def get(self, application_id: int) -> Application | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM applications WHERE id = ?", (application_id,)
            ).fetchone()
        return Application(**dict(row)) if row else None

    def find_duplicate(self, company: str, job_id: str, directory: str = "") -> Application | None:
        with self.database.connect() as connection:
            if job_id:
                row = connection.execute(
                    "SELECT * FROM applications WHERE lower(company)=lower(?) AND job_id=?",
                    (company.strip(), job_id.strip()),
                ).fetchone()
            elif directory:
                row = connection.execute(
                    "SELECT * FROM applications WHERE application_directory=?", (directory,)
                ).fetchone()
            else:
                row = None
        return Application(**dict(row)) if row else None

    def list(
        self,
        *,
        query: str = "",
        status: str = "",
        language: str = "",
        source: str = "",
    ) -> list[Application]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append("(company LIKE ? OR job_title LIKE ? OR location LIKE ?)")
            params.extend([f"%{query}%"] * 3)
        for column, value in (
            ("status", status),
            ("application_language", language),
            ("source", source),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM applications{where} ORDER BY updated_at DESC", params
            ).fetchall()
        return [Application(**dict(row)) for row in rows]

    def update(
        self, application_id: int, changes: dict[str, Any], status_note: str = ""
    ) -> Application:
        immutable = {
            "id",
            "application_directory",
            "created_at",
            "cv_master_used",
            "cover_letter_master_used",
        }
        allowed = set(Application.__dataclass_fields__) - immutable
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Fields cannot be updated: {', '.join(sorted(invalid))}")
        current = self.get(application_id)
        if current is None:
            raise KeyError(f"Application {application_id} was not found.")
        if not changes:
            return current
        input_fields = set(ApplicationInput.__dataclass_fields__)
        candidate_values = {field: getattr(current, field) for field in input_fields}
        candidate_values.update(
            {key: value for key, value in changes.items() if key in input_fields}
        )
        candidate = ApplicationInput(**candidate_values)
        candidate.validate()
        for key in set(changes) & input_fields:
            changes[key] = getattr(candidate, key)
        now = _now()
        if "status" in changes and changes["status"] != current.status:
            changes["status_updated_at"] = now
            if (
                changes["status"] in SUBMITTED_STATUSES
                and not current.application_date
                and not changes.get("application_date")
            ):
                changes["application_date"] = (
                    datetime.now().astimezone().date().isoformat()
                )
        changes["updated_at"] = now
        assignments = ", ".join(f"{column}=?" for column in changes)
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE applications SET {assignments} WHERE id=?",
                (*changes.values(), application_id),
            )
            if "status" in changes and changes["status"] != current.status:
                connection.execute(
                    """INSERT INTO status_history
                       (application_id, old_status, new_status, changed_at, note)
                       VALUES (?, ?, ?, ?, ?)""",
                    (application_id, current.status, changes["status"], now, status_note),
                )
        result = self.get(application_id)
        assert result is not None
        return result

    def status_history(self, application_id: int) -> list[StatusHistory]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM status_history WHERE application_id=? ORDER BY changed_at DESC, id DESC",
                (application_id,),
            ).fetchall()
        return [StatusHistory(**dict(row)) for row in rows]

    def log_filesystem(
        self,
        operation: str,
        source: str = "",
        destination: str = "",
        application_id: int | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO filesystem_log
                   (application_id, operation, source_path, destination_path, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (application_id, operation, source, destination, _now()),
            )

    def dashboard(self) -> dict[str, Any]:
        today = datetime.now().astimezone().date()
        month = today.strftime("%Y-%m")
        with self.database.connect() as connection:
            total = connection.execute("SELECT count(*) FROM applications").fetchone()[0]
            statuses = dict(
                connection.execute(
                    "SELECT status, count(*) FROM applications GROUP BY status ORDER BY status"
                ).fetchall()
            )
            submitted = connection.execute(
                "SELECT count(*) FROM applications WHERE application_date LIKE ?",
                (f"{month}%",),
            ).fetchone()[0]
            upcoming = connection.execute(
                """SELECT count(*) FROM applications
                   WHERE next_action_date <> '' AND next_action_date >= ?
                   AND status NOT IN ('Rejected','Withdrawn','Accepted')""",
                (today.isoformat(),),
            ).fetchone()[0]
            interviews = connection.execute(
                "SELECT count(*) FROM applications WHERE status='Interview Scheduled'"
            ).fetchone()[0]
            waiting = connection.execute(
                "SELECT count(*) FROM applications WHERE status='Waiting'"
            ).fetchone()[0]
        return {
            "total": total,
            "by_status": statuses,
            "submitted_this_month": submitted,
            "upcoming_followups": upcoming,
            "interviews": interviews,
            "waiting": waiting,
        }
