from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

OPENAI_MODELS = ("gpt-5.6-terra", "gpt-5.6-luna")
OPENAI_REASONING_EFFORTS = ("low", "medium")
STRATEGY_LANGUAGES = ("EN", "DE", "RO")
AI_MODES = {
    "Quick": {
        "model": "gpt-5.6-luna",
        "reasoning_effort": "low",
        "usage": "Initial screening",
    },
    "Standard": {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "low",
        "usage": "Most applications",
    },
    "Deep": {
        "model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "usage": "Important or difficult applications",
    },
}


@dataclass(slots=True)
class Settings:
    applications_root: str = "data/Applications"
    database_path: str = "data/jam.sqlite3"
    german_cv_master: str = ""
    english_cv_master: str = ""
    german_cover_letter_template: str = ""
    english_cover_letter_template: str = ""
    bewerbungsliste_path: str = "data/Bewerbungsliste.xlsx"
    default_application_language: str = "DE"
    default_source: str = ""
    filename_convention: str = "{document}_{name}_{language}_{company}_{job_ref}"
    applicant_name: str = "Applicant"
    date_format: str = "%d.%m.%Y"
    bewerbungsliste_column_mapping: str = ""
    candidate_facts_path: str = "data/candidate_facts.md"
    candidate_profile_path: str = "data/candidate_profile.json"
    active_candidate_profile_id: str = "default"
    agent_instructions_path: str = "data/agent_instructions.md"
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: str = "medium"
    openai_max_output_tokens: str = "4000"
    strategy_language: str = "EN"
    openai_data_sharing_enabled: str = "false"

    def resolve(self, base: Path) -> Settings:
        values = asdict(self)
        for key in (
            "applications_root",
            "database_path",
            "german_cv_master",
            "english_cv_master",
            "german_cover_letter_template",
            "english_cover_letter_template",
            "bewerbungsliste_path",
            "candidate_facts_path",
            "candidate_profile_path",
            "agent_instructions_path",
        ):
            value = values[key]
            if value:
                value = str(value).strip().strip('"').strip("'")
                path = Path(os.path.expandvars(os.path.expanduser(value)))
                values[key] = str(path if path.is_absolute() else (base / path).resolve())
        return Settings(**values)

    def master_cv(self, language: str) -> Path | None:
        value = self.german_cv_master if language == "DE" else self.english_cv_master
        return Path(value) if value else None

    def cover_template(self, language: str) -> Path | None:
        value = (
            self.german_cover_letter_template
            if language == "DE"
            else self.english_cover_letter_template
        )
        return Path(value) if value else None


def load_settings(path: str | Path = "config.toml") -> Settings:
    config_path = Path(path).resolve()
    if not config_path.exists():
        return Settings().resolve(config_path.parent)
    with config_path.open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    allowed = set(Settings.__dataclass_fields__)
    values = {key: value for key, value in data.get("jam", {}).items() if key in allowed}
    return Settings(**values).resolve(config_path.parent)


def save_settings(settings: Settings, path: str | Path = "config.toml") -> None:
    config_path = Path(path)
    lines = ["[jam]"]
    for key, value in asdict(settings).items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{key} = "{escaped}"')
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
