from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

APPLICATION_STATUSES = (
    "Identified",
    "Reviewing",
    "Preparing",
    "Ready to Apply",
    "Applied",
    "Recruiter Screening",
    "Hiring Manager Review",
    "Interview Scheduled",
    "Interview Completed",
    "Waiting",
    "Rejected",
    "Withdrawn",
    "Offer",
    "Accepted",
)

SUBMITTED_STATUSES = {
    "Applied",
    "Recruiter Screening",
    "Hiring Manager Review",
    "Interview Scheduled",
    "Interview Completed",
    "Waiting",
    "Offer",
    "Accepted",
}

LANGUAGES = ("DE", "EN")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class ApplicationInput:
    company: str
    job_title: str
    job_id: str = ""
    location: str = ""
    country: str = ""
    job_url: str = ""
    source: str = ""
    contact_name: str = ""
    contact_email: str = ""
    application_language: str = "DE"
    job_description_text: str = ""
    application_strategy: str = ""
    personal_notes: str = ""
    salary_expectation: str = ""
    work_model: str = ""
    office_days: str = ""
    application_date: str = ""
    status: str = "Identified"
    next_action: str = ""
    next_action_date: str = ""
    match_score: str = ""
    match_summary: str = ""
    strengths: str = ""
    transferable_experience: str = ""
    gaps: str = ""
    risks: str = ""
    recommended_cv_changes: str = ""
    cover_letter_draft: str = ""
    final_application_notes: str = ""
    company_address_line_1: str = ""
    company_address_line_2: str = ""
    cover_contact_line: str = ""
    cover_salutation: str = ""
    cover_motivation: str = ""
    cover_relevant_experience: str = ""
    cover_value_proposition: str = ""
    cover_optional_context: str = ""
    cover_closing: str = ""

    def validate(self) -> None:
        self.company = self.company.strip()
        self.job_title = self.job_title.strip()
        self.application_language = self.application_language.upper().strip()
        if not self.company:
            raise ValueError("Company is required.")
        if not self.job_title:
            raise ValueError("Job title is required.")
        if self.application_language not in LANGUAGES:
            raise ValueError("Application language must be DE or EN.")
        if self.status not in APPLICATION_STATUSES:
            raise ValueError(f"Unknown status: {self.status}")
        if self.contact_email and "@" not in self.contact_email:
            raise ValueError("Contact email is not valid.")
        for field_name in ("application_date", "next_action_date"):
            value = getattr(self, field_name)
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{field_name} must use YYYY-MM-DD.") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Application(ApplicationInput):
    id: int = 0
    status_updated_at: str = field(default_factory=utc_now)
    cv_file: str = ""
    cover_letter_file: str = ""
    confirmation_file: str = ""
    finalized_cv_pdf: str = ""
    finalized_cover_letter_pdf: str = ""
    finalized_cv_source: str = ""
    finalized_cover_letter_source: str = ""
    finalized_at: str = ""
    finalization_manifest: str = ""
    application_directory: str = ""
    cv_master_used: str = ""
    cover_letter_master_used: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class StatusHistory:
    id: int
    application_id: int
    old_status: str
    new_status: str
    changed_at: str
    note: str = ""
