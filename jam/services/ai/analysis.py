from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jam.domain.ai import AgentAnalysis, CoverLetterContent
from jam.persistence.ai_repository import AgentRunRepository

from .base import AIProvider

PROMPT_VERSION = "application-analyst-v2"
COVER_PROMPT_VERSION = "cover-letter-v1"


def read_local_text(path: str | Path) -> str:
    local_path = Path(path)
    return local_path.read_text(encoding="utf-8") if local_path.is_file() else ""


def save_local_text(path: str | Path, content: str) -> Path:
    local_path = Path(path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content.strip() + "\n", encoding="utf-8")
    return local_path


class AIAnalysisService:
    def __init__(self, repository: AgentRunRepository, provider: AIProvider):
        self.repository = repository
        self.provider = provider

    def analyze(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
        application_id: int | None = None,
    ) -> tuple[int, AgentAnalysis]:
        payload = json.dumps(
            {
                "job_description": job_description,
                "candidate_facts": candidate_facts,
                "agent_instructions": agent_instructions,
                "current_metadata": current_metadata,
                "strategy_language": strategy_language,
                "prompt_version": PROMPT_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        input_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        run = self.repository.start(
            application_id=application_id,
            run_type="application_analysis",
            provider=self.provider.name,
            model=self.provider.model,
            reasoning_effort=self.provider.reasoning_effort,
            communication_language=strategy_language,
            prompt_version=PROMPT_VERSION,
            input_hash=input_hash,
        )
        try:
            result = self.provider.analyze(
                job_description=job_description,
                candidate_facts=candidate_facts,
                agent_instructions=agent_instructions,
                current_metadata=current_metadata,
                strategy_language=strategy_language,
            )
            self.repository.complete(
                run.id,
                analysis=result.analysis,
                response_id=result.response_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            return run.id, result.analysis
        except Exception as exc:
            self.repository.fail(run.id, str(exc))
            raise

    def generate_cover_letter(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        application_context: dict[str, str],
        application_id: int,
    ) -> tuple[int, CoverLetterContent]:
        payload = json.dumps(
            {
                "job_description": job_description,
                "candidate_facts": candidate_facts,
                "agent_instructions": agent_instructions,
                "application_context": application_context,
                "prompt_version": COVER_PROMPT_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        input_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        run = self.repository.start(
            application_id=application_id,
            run_type="cover_letter_generation",
            provider=self.provider.name,
            model=self.provider.model,
            reasoning_effort=self.provider.reasoning_effort,
            communication_language=application_context.get(
                "application_language", ""
            ),
            prompt_version=COVER_PROMPT_VERSION,
            input_hash=input_hash,
        )
        try:
            result = self.provider.generate_cover_letter(
                job_description=job_description,
                candidate_facts=candidate_facts,
                agent_instructions=agent_instructions,
                application_context=application_context,
            )
            self.repository.complete_payload(
                run.id,
                payload=result.content,
                response_id=result.response_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            return run.id, result.content
        except Exception as exc:
            self.repository.fail(run.id, str(exc))
            raise

    def queue_analysis(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
        application_id: int,
    ) -> int:
        payload = json.dumps(
            {
                "job_description": job_description,
                "candidate_facts": candidate_facts,
                "agent_instructions": agent_instructions,
                "current_metadata": current_metadata,
                "strategy_language": strategy_language,
                "prompt_version": PROMPT_VERSION,
                "delivery": "batch",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        input_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        run = self.repository.start(
            application_id=application_id,
            run_type="application_analysis_batch",
            provider=self.provider.name,
            model=self.provider.model,
            reasoning_effort=self.provider.reasoning_effort,
            communication_language=strategy_language,
            prompt_version=PROMPT_VERSION,
            input_hash=input_hash,
        )
        try:
            queued = self.provider.queue_analysis(
                run_id=run.id,
                job_description=job_description,
                candidate_facts=candidate_facts,
                agent_instructions=agent_instructions,
                current_metadata=current_metadata,
                strategy_language=strategy_language,
            )
            self.repository.mark_queued(run.id, queued.batch_id)
            return run.id
        except Exception as exc:
            self.repository.fail(run.id, str(exc))
            raise

    def refresh_queued(
        self, application_id: int | None = None
    ) -> list[tuple[int, AgentAnalysis]]:
        completed: list[tuple[int, AgentAnalysis]] = []
        for run in self.repository.list_queued(application_id):
            result = self.provider.poll_batch(run.response_id)
            if result.status == "completed" and result.analysis is not None:
                self.repository.complete(
                    run.id,
                    analysis=result.analysis,
                    response_id=result.response_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
                completed.append((run.id, result.analysis))
            elif result.error:
                self.repository.fail(run.id, result.error)
        return completed
