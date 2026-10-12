from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel

from jam.domain.ai import AgentAnalysis, AgentRun

from .database import Database


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AgentRunRepository:
    def __init__(self, database: Database):
        self.database = database

    def start(
        self,
        *,
        application_id: int | None,
        run_type: str,
        provider: str,
        model: str,
        reasoning_effort: str,
        communication_language: str = "EN",
        prompt_version: str,
        input_hash: str,
    ) -> AgentRun:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO agent_runs
                   (application_id, run_type, provider, model, reasoning_effort,
                    communication_language, status, prompt_version, input_hash,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)""",
                (
                    application_id,
                    run_type,
                    provider,
                    model,
                    reasoning_effort,
                    communication_language,
                    prompt_version,
                    input_hash,
                    _now(),
                ),
            )
            run_id = int(cursor.lastrowid)
        result = self.get(run_id)
        assert result is not None
        return result

    def complete(
        self,
        run_id: int,
        *,
        analysis: AgentAnalysis,
        response_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> AgentRun:
        return self.complete_payload(
            run_id,
            payload=analysis,
            response_id=response_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def complete_payload(
        self,
        run_id: int,
        *,
        payload: BaseModel,
        response_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> AgentRun:
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE agent_runs
                   SET status='completed', result_json=?, response_id=?,
                       input_tokens=?, output_tokens=?, completed_at=?
                   WHERE id=?""",
                (
                    payload.model_dump_json(),
                    response_id,
                    input_tokens,
                    output_tokens,
                    _now(),
                    run_id,
                ),
            )
        result = self.get(run_id)
        assert result is not None
        return result

    def fail(self, run_id: int, error_message: str) -> AgentRun:
        with self.database.connect() as connection:
            connection.execute(
                """UPDATE agent_runs
                   SET status='failed', error_message=?, completed_at=?
                   WHERE id=?""",
                (error_message[:2000], _now(), run_id),
            )
        result = self.get(run_id)
        assert result is not None
        return result

    def mark_queued(self, run_id: int, batch_id: str) -> AgentRun:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='queued', response_id=? WHERE id=?",
                (batch_id, run_id),
            )
        result = self.get(run_id)
        assert result is not None
        return result

    def mark_applied(self, run_id: int, application_id: int | None = None) -> AgentRun:
        with self.database.connect() as connection:
            if application_id is None:
                connection.execute(
                    "UPDATE agent_runs SET status='applied', applied_at=? WHERE id=?",
                    (_now(), run_id),
                )
            else:
                connection.execute(
                    """UPDATE agent_runs
                       SET status='applied', application_id=?, applied_at=?
                       WHERE id=?""",
                    (application_id, _now(), run_id),
                )
        result = self.get(run_id)
        assert result is not None
        return result

    def attach(self, run_id: int, application_id: int) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET application_id=? WHERE id=?",
                (application_id, run_id),
            )

    def get(self, run_id: int) -> AgentRun | None:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        return AgentRun(**dict(row)) if row else None

    def analysis(self, run_id: int) -> AgentAnalysis:
        run = self.get(run_id)
        if run is None:
            raise KeyError(f"Agent run {run_id} was not found.")
        if not run.result_json:
            raise ValueError(f"Agent run {run_id} has no completed result.")
        return AgentAnalysis.model_validate(json.loads(run.result_json))

    def list_recent(self, limit: int = 50) -> list[AgentRun]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_runs ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AgentRun(**dict(row)) for row in rows]

    def list_queued(self, application_id: int | None = None) -> list[AgentRun]:
        query = "SELECT * FROM agent_runs WHERE status='queued'"
        parameters: tuple[object, ...] = ()
        if application_id is not None:
            query += " AND application_id=?"
            parameters = (application_id,)
        query += " ORDER BY created_at, id"
        with self.database.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [AgentRun(**dict(row)) for row in rows]

    def latest(
        self, *, application_id: int, run_type: str, status: str = ""
    ) -> AgentRun | None:
        query = (
            "SELECT * FROM agent_runs WHERE application_id=? AND run_type=?"
        )
        parameters: list[object] = [application_id, run_type]
        if status:
            query += " AND status=?"
            parameters.append(status)
        query += " ORDER BY created_at DESC, id DESC LIMIT 1"
        with self.database.connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return AgentRun(**dict(row)) if row else None
