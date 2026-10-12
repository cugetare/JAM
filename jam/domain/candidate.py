from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class CandidateIdentity(BaseModel):
    full_name: str = ""
    location: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""


class SkillGroup(BaseModel):
    name: str
    items: list[str] = Field(default_factory=list)


class ExperienceEntry(BaseModel):
    id: str
    date_text: str = ""
    role: str = ""
    company: str = ""
    location: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    description: str


class CertificationEntry(BaseModel):
    name: str
    year: str = ""


class LanguageSkill(BaseModel):
    language: str
    proficiency: str = ""


class CandidateCVVersion(BaseModel):
    language: str
    professional_summary: str = ""
    education: list[EducationEntry] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    languages: list[LanguageSkill] = Field(default_factory=list)
    unmapped_sections: list[str] = Field(default_factory=list)


class SourceDocument(BaseModel):
    language: str
    original_path: str
    archived_path: str
    sha256: str
    imported_at: str = Field(default_factory=utc_now)


class CandidateProfile(BaseModel):
    schema_version: int = 1
    profile_id: str = "default"
    display_name: str = ""
    photo_path: str = ""
    identity: CandidateIdentity = Field(default_factory=CandidateIdentity)
    cv_versions: dict[str, CandidateCVVersion] = Field(default_factory=dict)
    additional_facts: str = ""
    source_documents: list[SourceDocument] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now)

    def agent_context(self, preferred_language: str = "EN") -> str:
        language = preferred_language.upper()
        cv = (
            self.cv_versions.get(language)
            or self.cv_versions.get("EN")
            or self.cv_versions.get("DE")
            or next(iter(self.cv_versions.values()), None)
        )
        payload: dict[str, Any] = {
            "identity": self.identity.model_dump(exclude_none=True),
            "additional_verified_facts": self.additional_facts,
        }
        if cv:
            payload["cv"] = cv.model_dump(exclude={"unmapped_sections"})
        return self.__class__.model_validate(self).model_dump_json(
            indent=2,
            exclude={
                "source_documents",
                "updated_at",
                "schema_version",
                "profile_id",
                "display_name",
                "photo_path",
            },
        ) if not cv else _compact_json(payload)


def _compact_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
