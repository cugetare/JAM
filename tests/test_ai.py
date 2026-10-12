import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jam.domain.ai import AgentAnalysis, CoverLetterContent
from jam.persistence import AgentRunRepository, Database
from jam.services.ai import (
    AIAnalysisService,
    BatchPollResult,
    CoverLetterProviderResult,
    ProviderResult,
    QueuedProviderResult,
)
from jam.services.ai.openai_provider import OpenAIProvider


def _analysis() -> AgentAnalysis:
    field = {"value": "", "confidence": 0.1, "evidence": ""}
    return AgentAnalysis.model_validate(
        {
            "metadata": {
                "company": {
                    "value": "Example Robotics",
                    "confidence": 0.98,
                    "evidence": "Example Robotics",
                },
                "job_title": {
                    "value": "Staff Engineer",
                    "confidence": 0.95,
                    "evidence": "Staff Engineer",
                },
                "job_id": field,
                "location": field,
                "country": field,
                "job_url": field,
                "source": field,
                "contact_name": field,
                "contact_email": field,
                "application_language": "EN",
                "salary_expectation": field,
                "work_model": field,
                "office_days": field,
            },
            "match_score": 82,
            "match_summary": "Strong platform fit.",
            "strengths": ["Distributed systems"],
            "transferable_experience": ["Technical leadership"],
            "gaps": ["No robotics domain evidence"],
            "risks": ["Travel expectation is unclear"],
            "application_strategy": "Lead with platform reliability.",
            "recommended_cv_changes": ["Promote the reliability project."],
            "cover_letter": {
                "salutation": "Dear Hiring Team,",
                "motivation": "The platform challenge is compelling.",
                "relevant_experience": "I have led reliable platform work.",
                "value_proposition": "I bring systems depth and leadership.",
                "optional_context": "",
                "closing": "I would welcome a discussion.",
            },
            "next_action": "Review the proposed claims.",
            "assumptions": ["No full CV was supplied."],
        }
    )


class FakeProvider:
    name = "fake"
    model = "fake-model"
    reasoning_effort = "low"

    def analyze(self, **_: object) -> ProviderResult:
        return ProviderResult(
            analysis=_analysis(),
            response_id="response-test",
            input_tokens=120,
            output_tokens=80,
        )

    def generate_cover_letter(self, **_: object) -> CoverLetterProviderResult:
        assert _analysis().cover_letter is not None
        return CoverLetterProviderResult(
            content=_analysis().cover_letter,
            response_id="cover-response-test",
            input_tokens=100,
            output_tokens=40,
        )

    def queue_analysis(self, **_: object) -> QueuedProviderResult:
        return QueuedProviderResult(batch_id="batch-test")

    def poll_batch(self, batch_id: str) -> BatchPollResult:
        assert batch_id == "batch-test"
        analysis = _analysis()
        analysis.cover_letter = None
        return BatchPollResult(
            status="completed",
            analysis=analysis,
            response_id="batch-response-test",
            input_tokens=90,
            output_tokens=35,
        )


class FailingProvider(FakeProvider):
    def analyze(self, **_: object) -> ProviderResult:
        raise RuntimeError("provider unavailable")


@pytest.fixture
def agent_repository(tmp_path: Path) -> AgentRunRepository:
    database = Database(tmp_path / "ai.sqlite3")
    database.initialize()
    return AgentRunRepository(database)


def _application_id(repository: AgentRunRepository, suffix: str) -> int:
    with repository.database.connect() as connection:
        cursor = connection.execute(
            """INSERT INTO applications
               (company, job_title, status_updated_at, application_directory,
                created_at, updated_at)
               VALUES ('Example', 'Engineer', 'now', ?, 'now', 'now')""",
            (f"application-{suffix}",),
        )
        return int(cursor.lastrowid)


def test_analysis_run_is_logged_and_structured(
    agent_repository: AgentRunRepository,
) -> None:
    service = AIAnalysisService(agent_repository, FakeProvider())
    run_id, analysis = service.analyze(
        job_description="Example Robotics seeks a Staff Engineer.",
        candidate_facts="Platform engineer.",
        agent_instructions="Use a direct style.",
        current_metadata={},
        strategy_language="RO",
    )
    run = agent_repository.get(run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.response_id == "response-test"
    assert run.input_tokens == 120
    assert run.communication_language == "RO"
    assert agent_repository.analysis(run_id) == analysis
    assert analysis.application_changes()["company"] == "Example Robotics"
    assert analysis.application_changes()["cover_motivation"].startswith("The platform")


def test_failed_analysis_is_retained_for_audit(
    agent_repository: AgentRunRepository,
) -> None:
    service = AIAnalysisService(agent_repository, FailingProvider())
    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.analyze(
            job_description="A JD",
            candidate_facts="A profile",
            agent_instructions="Be factual.",
            current_metadata={},
        )
    run = agent_repository.list_recent()[0]
    assert run.status == "failed"
    assert run.error_message == "provider unavailable"


def test_cover_letter_is_generated_as_a_separate_run(
    agent_repository: AgentRunRepository,
) -> None:
    service = AIAnalysisService(agent_repository, FakeProvider())
    application_id = _application_id(agent_repository, "cover")
    run_id, content = service.generate_cover_letter(
        job_description="A JD",
        candidate_facts="Platform engineer.",
        agent_instructions="Use a direct style.",
        application_context={"application_language": "EN"},
        application_id=application_id,
    )
    run = agent_repository.get(run_id)
    assert run is not None
    assert run.run_type == "cover_letter_generation"
    assert run.status == "completed"
    assert CoverLetterContent.model_validate_json(run.result_json) == content


def test_batch_analysis_is_queued_then_reconciled(
    agent_repository: AgentRunRepository,
) -> None:
    service = AIAnalysisService(agent_repository, FakeProvider())
    application_id = _application_id(agent_repository, "batch")
    run_id = service.queue_analysis(
        job_description="A JD",
        candidate_facts="Platform engineer.",
        agent_instructions="Be factual.",
        current_metadata={},
        application_id=application_id,
    )
    queued = agent_repository.get(run_id)
    assert queued is not None
    assert queued.status == "queued"
    assert queued.response_id == "batch-test"

    completed = service.refresh_queued(application_id=application_id)
    assert completed[0][0] == run_id
    run = agent_repository.get(run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.response_id == "batch-response-test"
    assert agent_repository.analysis(run_id).cover_letter is None


def test_cached_prefix_ends_after_agent_instructions() -> None:
    input_items, cache_key = OpenAIProvider._cached_input(
        system_prompt="Stable system",
        candidate_facts="Stable facts",
        agent_instructions="Stable instructions",
        dynamic_context={"job_description": "Changing JD"},
    )
    stable_blocks = input_items[1]["content"]
    assert stable_blocks[0]["text"].endswith("Stable facts")
    assert stable_blocks[1]["text"].endswith("Stable instructions")
    assert stable_blocks[1]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert "Changing JD" in input_items[2]["content"]
    assert cache_key.startswith("jam-")


def test_openai_batch_request_and_result_contract() -> None:
    analysis = _analysis()
    analysis.cover_letter = None
    response_body = {
        "id": "resp-batch",
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": analysis.model_dump_json()}
                ],
            }
        ],
        "usage": {"input_tokens": 70, "output_tokens": 30},
    }
    output_jsonl = json.dumps(
        {"response": {"status_code": 200, "body": response_body}}
    )

    class FakeFiles:
        uploaded: tuple[str, bytes] | None = None

        def create(self, *, file: tuple[str, bytes], purpose: str) -> SimpleNamespace:
            assert purpose == "batch"
            self.uploaded = file
            return SimpleNamespace(id="file-input")

        def content(self, file_id: str) -> SimpleNamespace:
            assert file_id == "file-output"
            return SimpleNamespace(text=output_jsonl)

    class FakeBatches:
        def create(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["endpoint"] == "/v1/responses"
            return SimpleNamespace(id="batch-contract")

        def retrieve(self, batch_id: str) -> SimpleNamespace:
            assert batch_id == "batch-contract"
            return SimpleNamespace(
                status="completed",
                output_file_id="file-output",
            )

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.model = "gpt-5.6-luna"
    provider.reasoning_effort = "low"
    provider.max_output_tokens = 4000
    files = FakeFiles()
    provider.client = SimpleNamespace(files=files, batches=FakeBatches())

    queued = provider.queue_analysis(
        run_id=42,
        job_description="Changing JD",
        candidate_facts="Stable facts",
        agent_instructions="Stable instructions",
        current_metadata={},
        strategy_language="RO",
    )
    assert queued.batch_id == "batch-contract"
    assert files.uploaded is not None
    request = json.loads(files.uploaded[1])
    assert request["custom_id"] == "jam-run-42"
    assert request["body"]["max_output_tokens"] == 4000
    assert request["body"]["prompt_cache_options"]["mode"] == "explicit"
    assert request["body"]["text"]["format"]["strict"] is True
    dynamic_context = json.loads(request["body"]["input"][2]["content"])
    language_requirements = dynamic_context["language_requirements"]
    assert language_requirements["strategy_discussion"] == "Romanian (RO)"
    assert language_requirements["application_language_is_independent"] is True
    assert "application language" in language_requirements["cv_recommendations"]

    result = provider.poll_batch(queued.batch_id)
    assert result.status == "completed"
    assert result.analysis == analysis
    assert result.response_id == "resp-batch"
