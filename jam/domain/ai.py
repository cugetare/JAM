from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FieldSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    confidence: float = Field(ge=0, le=1)
    evidence: str = ""


class MetadataSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: FieldSuggestion
    job_title: FieldSuggestion
    job_id: FieldSuggestion
    location: FieldSuggestion
    country: FieldSuggestion
    job_url: FieldSuggestion
    source: FieldSuggestion
    contact_name: FieldSuggestion
    contact_email: FieldSuggestion
    application_language: Literal["DE", "EN"]
    salary_expectation: FieldSuggestion
    work_model: FieldSuggestion
    office_days: FieldSuggestion


class CoverLetterContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    salutation: str
    motivation: str
    relevant_experience: str
    value_proposition: str
    optional_context: str
    closing: str


class AgentAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: MetadataSuggestions
    match_score: int = Field(ge=0, le=100)
    match_summary: str
    strengths: list[str]
    transferable_experience: list[str]
    gaps: list[str]
    risks: list[str]
    application_strategy: str
    recommended_cv_changes: list[str]
    cover_letter: CoverLetterContent | None
    next_action: str
    assumptions: list[str]

    def application_changes(self) -> dict[str, str]:
        changes: dict[str, str] = {}
        for field_name in (
            "company",
            "job_title",
            "job_id",
            "location",
            "country",
            "job_url",
            "source",
            "contact_name",
            "contact_email",
            "salary_expectation",
            "work_model",
            "office_days",
        ):
            suggestion = getattr(self.metadata, field_name)
            if suggestion.value.strip():
                changes[field_name] = suggestion.value.strip()
        changes.update(
            {
                "application_language": self.metadata.application_language,
                "match_score": str(self.match_score),
                "match_summary": self.match_summary.strip(),
                "strengths": "\n".join(self.strengths),
                "transferable_experience": "\n".join(self.transferable_experience),
                "gaps": "\n".join(self.gaps),
                "risks": "\n".join(self.risks),
                "application_strategy": self.application_strategy.strip(),
                "recommended_cv_changes": "\n".join(self.recommended_cv_changes),
                "next_action": self.next_action.strip(),
            }
        )
        if self.cover_letter is not None:
            changes.update(
                {
                    "cover_salutation": self.cover_letter.salutation.strip(),
                    "cover_motivation": self.cover_letter.motivation.strip(),
                    "cover_relevant_experience": (
                        self.cover_letter.relevant_experience.strip()
                    ),
                    "cover_value_proposition": (
                        self.cover_letter.value_proposition.strip()
                    ),
                    "cover_optional_context": (
                        self.cover_letter.optional_context.strip()
                    ),
                    "cover_closing": self.cover_letter.closing.strip(),
                }
            )
        return changes


@dataclass(slots=True)
class AgentRun:
    id: int
    application_id: int | None
    run_type: str
    provider: str
    model: str
    reasoning_effort: str
    communication_language: str
    status: str
    prompt_version: str
    input_hash: str
    result_json: str
    response_id: str
    input_tokens: int
    output_tokens: int
    error_message: str
    created_at: str
    completed_at: str
    applied_at: str
