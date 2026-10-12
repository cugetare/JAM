from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jam.domain.ai import AgentAnalysis, CoverLetterContent


@dataclass(slots=True)
class ProviderResult:
    analysis: AgentAnalysis
    response_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class CoverLetterProviderResult:
    content: CoverLetterContent
    response_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class QueuedProviderResult:
    batch_id: str


@dataclass(slots=True)
class BatchPollResult:
    status: str
    analysis: AgentAnalysis | None = None
    response_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


class AIProvider(Protocol):
    name: str
    model: str
    reasoning_effort: str

    def analyze(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
    ) -> ProviderResult: ...

    def generate_cover_letter(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        application_context: dict[str, str],
    ) -> CoverLetterProviderResult: ...

    def queue_analysis(
        self,
        *,
        run_id: int,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
    ) -> QueuedProviderResult: ...

    def poll_batch(self, batch_id: str) -> BatchPollResult: ...
