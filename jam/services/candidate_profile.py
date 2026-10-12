from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from docx import Document
from PIL import Image

from jam.domain.candidate import (
    CandidateCVVersion,
    CandidateIdentity,
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    LanguageSkill,
    SkillGroup,
    SourceDocument,
    utc_now,
)

SUMMARY_LABELS = {"professional summary", "berufliches profil"}
EDUCATION_LABELS = {"education", "studium"}
SKILLS_LABELS = {"competencies", "skills", "kompetenzen"}
EXPERIENCE_LABELS = {"professional experience", "berufserfahrung", "professional"}
CERTIFICATION_LABELS = {
    "professional training & certifications",
    "training & certifications",
    "weiterbildungen & zertifizierungen",
}
ACHIEVEMENT_LABELS = {"selected achievements", "ausgewählte erfolge"}
LANGUAGE_LABELS = {"languages", "sprachen"}


@dataclass(frozen=True, slots=True)
class CandidateProfileSummary:
    profile_id: str
    display_name: str
    path: Path
    photo_path: str


def profile_display_name(profile: CandidateProfile) -> str:
    return (
        profile.display_name.strip()
        or profile.identity.full_name.strip()
        or "Candidate profile"
    )


def list_candidate_profiles(primary_path: str | Path) -> list[CandidateProfileSummary]:
    primary = Path(primary_path)
    paths = [primary]
    profiles_dir = primary.parent / "candidate_profiles"
    if profiles_dir.is_dir():
        paths.extend(sorted(profiles_dir.glob("*.json")))
    summaries: list[CandidateProfileSummary] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            profile = load_candidate_profile(path)
        except (OSError, ValueError):
            continue
        if profile.profile_id in seen:
            continue
        seen.add(profile.profile_id)
        summaries.append(
            CandidateProfileSummary(
                profile_id=profile.profile_id,
                display_name=profile_display_name(profile),
                path=path.resolve(),
                photo_path=profile.photo_path,
            )
        )
    return summaries


def active_candidate_profile_path(
    primary_path: str | Path, active_profile_id: str
) -> Path:
    profiles = list_candidate_profiles(primary_path)
    for profile in profiles:
        if profile.profile_id == active_profile_id:
            return profile.path
    return Path(primary_path)


def create_candidate_profile(
    primary_path: str | Path, display_name: str
) -> tuple[CandidateProfile, Path]:
    name = display_name.strip()
    if not name:
        raise ValueError("Enter a profile name.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "candidate"
    profile_id = f"{slug}-{uuid4().hex[:8]}"
    profile_path = Path(primary_path).parent / "candidate_profiles" / f"{profile_id}.json"
    profile = CandidateProfile(profile_id=profile_id, display_name=name)
    save_candidate_profile(profile, profile_path)
    return profile, profile_path


def save_profile_photo(
    profile: CandidateProfile,
    profile_path: str | Path,
    primary_path: str | Path,
    image_bytes: bytes,
) -> Path:
    if not image_bytes:
        raise ValueError("Choose an image first.")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise ValueError("The profile photo must be smaller than 10 MB.")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
            image_format = str(image.format or "").upper()
    except Exception as exc:
        raise ValueError("The selected file is not a valid image.") from exc
    extensions = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    if image_format not in extensions:
        raise ValueError("Use a JPG, PNG, or WebP image.")
    assets = Path(primary_path).parent / "candidate_profile_assets"
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / f"{profile.profile_id}{extensions[image_format]}"
    target.write_bytes(image_bytes)
    profile.photo_path = str(target.resolve())
    save_candidate_profile(profile, profile_path)
    return target


def load_candidate_profile(path: str | Path) -> CandidateProfile:
    profile_path = Path(path)
    if not profile_path.is_file():
        return CandidateProfile()
    return CandidateProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))


def save_candidate_profile(profile: CandidateProfile, path: str | Path) -> Path:
    profile_path = Path(path)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if profile_path.is_file():
        backup_dir = profile_path.parent / "candidate_profile_versions"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(profile_path, backup_dir / f"candidate_profile_{timestamp}.json")
    profile.updated_at = utc_now()
    temporary = profile_path.with_suffix(".json.tmp")
    temporary.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(profile_path)
    return profile_path


def candidate_facts_for_ai(
    profile_path: str | Path,
    legacy_facts_path: str | Path,
    preferred_language: str = "EN",
) -> str:
    profile = load_candidate_profile(profile_path)
    if profile.cv_versions:
        return profile.agent_context(preferred_language)
    legacy = Path(legacy_facts_path)
    return legacy.read_text(encoding="utf-8") if legacy.is_file() else ""


def parse_cv_docx(path: str | Path, language: str | None = None) -> CandidateCVVersion:
    document = Document(str(path))
    detected_language = (language or _detect_language(document)).upper()
    main_table = max(document.tables, key=lambda table: len(table.rows))
    cv = CandidateCVVersion(language=detected_language)
    experience_mode = False
    skills_seen = False

    for row in main_table.rows:
        unique_cells = _unique_cells(row.cells)
        if not unique_cells:
            continue
        first = unique_cells[0]
        first_text = _clean(first.text)
        normalized = first_text.casefold()
        content_cell = unique_cells[-1]

        if normalized in SUMMARY_LABELS:
            cv.professional_summary = _clean(content_cell.text)
            experience_mode = False
        elif normalized in EDUCATION_LABELS:
            text = _clean(content_cell.text)
            if text:
                cv.education.append(EducationEntry(description=text))
            experience_mode = False
        elif normalized in SKILLS_LABELS:
            cv.skill_groups, cv.languages = _parse_skills(content_cell)
            skills_seen = True
            experience_mode = False
        elif normalized in EXPERIENCE_LABELS:
            experience_mode = True
        elif normalized in CERTIFICATION_LABELS:
            cv.certifications = _parse_certifications(content_cell)
            experience_mode = False
        elif experience_mode and _looks_like_experience(first):
            cv.experience.append(_parse_experience(first, detected_language))
        elif cv.professional_summary and not skills_seen and first_text:
            # Some CV layouts merge the education label with its content.
            cv.education.append(EducationEntry(description=first_text))
        elif first_text:
            cv.unmapped_sections.append(first_text)
    return cv


def import_cv(
    source_path: str | Path,
    language: str,
    profile_path: str | Path,
    *,
    legacy_facts_path: str | Path | None = None,
) -> CandidateProfile:
    source = Path(source_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".docx":
        raise ValueError("Select an existing DOCX file.")
    profile = load_candidate_profile(profile_path)
    cv = parse_cv_docx(source, language)
    profile.cv_versions[language.upper()] = cv
    identity = _parse_identity(Document(str(source)))
    profile.identity = _merge_identity(profile.identity, identity)
    if not profile.additional_facts and legacy_facts_path:
        legacy = Path(legacy_facts_path)
        if legacy.is_file():
            profile.additional_facts = legacy.read_text(encoding="utf-8")

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    archive_dir = Path(profile_path).parent / "candidate_profile_sources"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive = archive_dir / f"{timestamp}_{language.upper()}_{source.name}"
    if not archive.exists():
        shutil.copy2(source, archive)
    profile.source_documents.append(
        SourceDocument(
            language=language.upper(),
            original_path=str(source),
            archived_path=str(archive.resolve()),
            sha256=digest,
        )
    )
    save_candidate_profile(profile, profile_path)
    return profile


def _detect_language(document: Document) -> str:
    text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
    return "DE" if "Berufserfahrung" in text or "Kompetenzen" in text else "EN"


def _unique_cells(cells):
    result = []
    seen = set()
    for cell in cells:
        key = id(cell._tc)
        if key not in seen and _clean(cell.text):
            seen.add(key)
            result.append(cell)
    return result


def _clean(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.replace("\xa0", " ")).strip()


def _paragraphs(cell) -> list:
    return [paragraph for paragraph in cell.paragraphs if _clean(paragraph.text)]


def _parse_skills(cell) -> tuple[list[SkillGroup], list[LanguageSkill]]:
    groups: list[SkillGroup] = []
    languages: list[LanguageSkill] = []
    current: SkillGroup | None = None
    in_languages = False
    for paragraph in _paragraphs(cell):
        text = _clean(paragraph.text)
        is_header = any(bool(run.bold) for run in paragraph.runs)
        if is_header:
            in_languages = text.casefold() in LANGUAGE_LABELS
            current = None if in_languages else SkillGroup(name=text)
            if current:
                groups.append(current)
        elif in_languages:
            parts = re.split(r"\s+[–—-]\s+", text, maxsplit=1)
            languages.append(
                LanguageSkill(
                    language=parts[0],
                    proficiency=parts[1] if len(parts) > 1 else "",
                )
            )
        elif current:
            current.items.append(text)
        else:
            groups.append(SkillGroup(name="Other", items=[text]))
            current = groups[-1]
    return groups, languages


def _looks_like_experience(cell) -> bool:
    paragraphs = _paragraphs(cell)
    return len(paragraphs) >= 4 and bool(re.match(r"\d{2}/\d{4}", _clean(paragraphs[0].text)))


def _parse_experience(cell, language: str) -> ExperienceEntry:
    values = [_clean(paragraph.text) for paragraph in _paragraphs(cell)]
    date_text, role, company, location, *body = values
    responsibilities: list[str] = []
    achievements: list[str] = []
    target = responsibilities
    for value in body:
        if value.casefold() in ACHIEVEMENT_LABELS:
            target = achievements
        else:
            target.append(value)
    stable_id = str(uuid5(NAMESPACE_URL, f"{date_text}|{company}|{role}"))
    return ExperienceEntry(
        id=stable_id,
        date_text=date_text,
        role=role,
        company=company,
        location=location,
        responsibilities=responsibilities,
        achievements=achievements,
    )


def _parse_certifications(cell) -> list[CertificationEntry]:
    certifications = []
    for paragraph in _paragraphs(cell):
        text = _clean(paragraph.text)
        match = re.match(r"^(.*)\s+\((\d{4})\)$", text)
        certifications.append(
            CertificationEntry(
                name=match.group(1) if match else text,
                year=match.group(2) if match else "",
            )
        )
    return certifications


def _parse_identity(document: Document) -> CandidateIdentity:
    name = _clean(document.tables[0].cell(0, 0).text) if document.tables else ""
    raw_contact = document.tables[1].cell(0, 0).text if len(document.tables) > 1 else ""
    contact_lines = [_clean(line) for line in raw_contact.splitlines() if _clean(line)]
    contact = " | ".join(contact_lines)
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", contact)
    website_match = re.search(r"(?:www\.)[\w.-]+\.[A-Za-z]{2,}", contact)
    phone_match = re.search(r"\+\d[\d\s()/-]{7,}\d", contact)
    location = contact_lines[0] if contact_lines else ""
    return CandidateIdentity(
        full_name=name,
        location=location,
        email=email_match.group(0) if email_match else "",
        phone=phone_match.group(0) if phone_match else "",
        website=website_match.group(0) if website_match else "",
    )


def _merge_identity(current: CandidateIdentity, imported: CandidateIdentity) -> CandidateIdentity:
    return CandidateIdentity(
        **{
            field: getattr(imported, field) or getattr(current, field)
            for field in CandidateIdentity.model_fields
        }
    )
