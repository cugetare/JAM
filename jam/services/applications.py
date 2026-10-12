from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from jam.config import Settings
from jam.domain.models import Application, ApplicationInput
from jam.persistence.repositories import ApplicationRepository

from .documents import render_template, template_tokens
from .filesystem import (
    application_path,
    copy_new,
    create_directory_tree,
    next_version_path,
    sanitize_component,
    write_new_json,
    write_new_text,
)
from .pdf import PdfInfo, convert_docx_to_pdf, file_sha256, latest_docx

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FinalizationResult:
    package_directory: Path
    cv_source: Path
    cover_letter_source: Path
    cv_pdf: Path
    cover_letter_pdf: Path
    manifest: Path


class ApplicationService:
    def __init__(self, settings: Settings, repository: ApplicationRepository):
        self.settings = settings
        self.repository = repository

    def planned_path(self, data: ApplicationInput) -> Path:
        return application_path(
            Path(self.settings.applications_root),
            data.company,
            data.job_title,
            data.job_id,
            data.location,
        )

    def find_duplicate(self, data: ApplicationInput) -> Application | None:
        path = self.planned_path(data)
        return self.repository.find_duplicate(data.company, data.job_id, str(path))

    def create(
        self, data: ApplicationInput, *, copy_cv: bool = True, copy_cover_letter: bool = True
    ) -> Application:
        data.validate()
        path = self.planned_path(data)
        duplicate = self.find_duplicate(data)
        if duplicate:
            raise ValueError(
                f"Application already exists as record {duplicate.id}: "
                f"{duplicate.application_directory}"
            )
        if path.exists():
            raise FileExistsError(
                f"Directory already exists and will not be modified: {path}. "
                "Use the import workflow instead."
            )

        cv_path = ""
        cover_path = ""
        cv_master_used = ""
        cover_master_used = ""
        try:
            create_directory_tree(path)
            self.repository.log_filesystem("create_directory_tree", destination=str(path))
            write_new_text(path / "00_JD" / "JD_original.txt", data.job_description_text)
            write_new_json(
                path / "00_JD" / "JD_metadata.json",
                {
                    "company": data.company,
                    "job_title": data.job_title,
                    "job_id": data.job_id,
                    "location": data.location,
                    "job_url": data.job_url,
                    "language": data.application_language,
                },
            )

            job_ref = sanitize_component(data.job_id or data.job_title)
            company = sanitize_component(data.company)
            name = sanitize_component(self.settings.applicant_name)
            filename_values = {
                "name": name,
                "language": data.application_language,
                "company": company,
                "job_ref": job_ref,
            }
            if copy_cv and (master := self.settings.master_cv(data.application_language)):
                cv_master_used = str(master)
                cv_stem = sanitize_component(
                    self.settings.filename_convention.format(document="CV", **filename_values)
                )
                destination = next_version_path(
                    path / "01_Application" / "CV",
                    cv_stem,
                    master.suffix or ".docx",
                )
                cv_path = str(copy_new(master, destination))
                self.repository.log_filesystem("copy_master_cv", str(master), cv_path)
            if copy_cover_letter and (
                template := self.settings.cover_template(data.application_language)
            ):
                cover_master_used = str(template)
                cover_stem = sanitize_component(
                    self.settings.filename_convention.format(
                        document="Cover_Letter", **filename_values
                    )
                )
                destination = next_version_path(
                    path / "01_Application" / "Cover_Letter",
                    cover_stem,
                    template.suffix or ".docx",
                )
                cover_path = str(copy_new(template, destination))
                self.repository.log_filesystem(
                    "copy_cover_letter_template", str(template), cover_path
                )

            application = self.repository.create(
                data,
                application_directory=str(path),
                cv_file=cv_path,
                cover_letter_file=cover_path,
                cv_master_used=cv_master_used,
                cover_letter_master_used=cover_master_used,
            )
            write_new_json(
                path / "02_Submission" / "application_data.json",
                asdict(application),
            )
            LOGGER.info("Created application %s at %s", application.id, path)
            return application
        except Exception:
            LOGGER.exception("Application creation failed for %s", path)
            # The directory is deliberately retained for audit/recovery; it is never
            # silently deleted after a partial filesystem operation.
            raise

    def export_ai_brief(self, application_id: int) -> Path:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")
        target = Path(app.application_directory) / "00_JD" / "AI_Brief.md"
        if target.exists():
            target = next_version_path(target.parent, "AI_Brief", ".md")
        content = f"""# AI Brief: {app.company} — {app.job_title}

## Application metadata

- Company: {app.company}
- Job title: {app.job_title}
- Job ID: {app.job_id}
- Location: {app.location}
- URL: {app.job_url}
- Language: {app.application_language}
- CV master used: {app.cv_master_used}

## Application strategy

{app.application_strategy}

## User comments

{app.personal_notes}

## Complete job description

{app.job_description_text}
"""
        write_new_text(target, content)
        self.repository.log_filesystem(
            "export_ai_brief", destination=str(target), application_id=application_id
        )
        return target

    def update_job_description(
        self, application_id: int, job_description_text: str
    ) -> Application:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")
        content = job_description_text.strip()
        if not content:
            raise ValueError("The original job description cannot be empty.")
        if content == app.job_description_text.strip():
            return app

        target = Path(app.application_directory) / "00_JD" / "JD_original.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if target.is_file() and target.read_text(encoding="utf-8").strip():
            backup = next_version_path(target.parent, target.stem, target.suffix)
            copy_new(target, backup)
            self.repository.log_filesystem(
                "version_job_description",
                str(target),
                str(backup),
                application_id,
            )
        target.write_text(content + "\n", encoding="utf-8", newline="\n")
        updated = self.repository.update(
            application_id, {"job_description_text": content}
        )

        snapshot = (
            Path(updated.application_directory)
            / "02_Submission"
            / "application_data.json"
        )
        if snapshot.is_file():
            snapshot.write_text(
                json.dumps(asdict(updated), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        self.repository.log_filesystem(
            "update_job_description",
            str(backup or ""),
            str(target),
            application_id,
        )
        return updated

    def create_working_document_version(self, application_id: int, kind: str) -> Path:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")
        if kind not in {"cv", "cover_letter"}:
            raise ValueError("Document kind must be cv or cover_letter.")
        current_value = app.cv_file if kind == "cv" else app.cover_letter_file
        if not current_value:
            raise ValueError(f"No current {kind} working document is recorded.")
        current = Path(current_value)
        # Submitted artifacts are never used as a source for regeneration.
        if "_submitted" in current.stem.lower():
            raise ValueError("Submitted documents are immutable.")
        stem = current.stem.rsplit("_v", 1)[0]
        destination = next_version_path(current.parent, stem, current.suffix)
        copy_new(current, destination)
        field = "cv_file" if kind == "cv" else "cover_letter_file"
        self.repository.update(application_id, {field: str(destination)})
        self.repository.log_filesystem(
            f"version_{kind}", str(current), str(destination), application_id
        )
        return destination

    def latest_working_documents(
        self, application_id: int
    ) -> tuple[Path | None, Path | None]:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")
        root = Path(app.application_directory) / "01_Application"
        return (
            latest_docx(root / "CV", app.cv_file),
            latest_docx(root / "Cover_Letter", app.cover_letter_file),
        )

    @staticmethod
    def _source_evidence(path: Path) -> dict[str, object]:
        stat = path.stat()
        return {
            "path": str(path),
            "filename": path.name,
            "byte_size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(
                timespec="seconds"
            ),
            "sha256": file_sha256(path),
        }

    @staticmethod
    def _pdf_evidence(info: PdfInfo, final_path: Path) -> dict[str, object]:
        return {
            "path": str(final_path),
            "filename": final_path.name,
            "byte_size": info.byte_size,
            "page_count": info.page_count,
            "sha256": info.sha256,
            "converter": info.converter,
        }

    def finalize_application(self, application_id: int) -> FinalizationResult:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")
        cv_source, cover_source = self.latest_working_documents(application_id)
        if cv_source is None:
            raise FileNotFoundError("No working CV DOCX was found.")
        if cover_source is None:
            raise FileNotFoundError("No working cover-letter DOCX was found.")

        finalized_at = datetime.now().astimezone()
        final_root = Path(app.application_directory) / "02_Submission" / "final"
        final_root.mkdir(parents=True, exist_ok=True)
        package_name = finalized_at.strftime("%Y%m%d_%H%M%S")
        package_directory = final_root / package_name
        for version in range(2, 100):
            if not package_directory.exists():
                break
            package_directory = final_root / f"{package_name}_{version:02d}"
        else:
            raise RuntimeError("No available finalization package directory.")

        staging = final_root / f".staging_{uuid4().hex}"
        staging.mkdir()
        try:
            applicant = sanitize_component(
                self.settings.applicant_name, "Applicant", max_length=48
            )
            cv_staging = staging / f"CV_{applicant}.pdf"
            cover_staging = staging / f"Cover_Letter_{applicant}.pdf"
            cv_info = convert_docx_to_pdf(cv_source, cv_staging)
            cover_info = convert_docx_to_pdf(cover_source, cover_staging)

            cv_pdf = package_directory / cv_staging.name
            cover_pdf = package_directory / cover_staging.name
            manifest = package_directory / "finalization_manifest.json"
            next_status = (
                "Ready to Apply"
                if app.status in {"Identified", "Reviewing", "Preparing"}
                else app.status
            )
            manifest_data = {
                "application_id": app.id,
                "company": app.company,
                "job_title": app.job_title,
                "job_id": app.job_id,
                "finalized_at": finalized_at.isoformat(timespec="seconds"),
                "status_before": app.status,
                "status_after": next_status,
                "sources": {
                    "cv": self._source_evidence(cv_source),
                    "cover_letter": self._source_evidence(cover_source),
                },
                "outputs": {
                    "cv": self._pdf_evidence(cv_info, cv_pdf),
                    "cover_letter": self._pdf_evidence(cover_info, cover_pdf),
                },
            }
            write_new_json(staging / manifest.name, manifest_data)
            staging.rename(package_directory)

            changes = {
                "finalized_cv_pdf": str(cv_pdf),
                "finalized_cover_letter_pdf": str(cover_pdf),
                "finalized_cv_source": str(cv_source),
                "finalized_cover_letter_source": str(cover_source),
                "finalized_at": finalized_at.isoformat(timespec="seconds"),
                "finalization_manifest": str(manifest),
            }
            if next_status != app.status:
                changes["status"] = next_status
            updated = self.repository.update(
                application_id,
                changes,
                status_note="Final PDF application package created",
            )
            snapshot = (
                Path(updated.application_directory)
                / "02_Submission"
                / "application_data.json"
            )
            if snapshot.is_file():
                snapshot.write_text(
                    json.dumps(asdict(updated), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            self.repository.log_filesystem(
                "finalize_cv_pdf", str(cv_source), str(cv_pdf), application_id
            )
            self.repository.log_filesystem(
                "finalize_cover_letter_pdf",
                str(cover_source),
                str(cover_pdf),
                application_id,
            )
            self.repository.log_filesystem(
                "create_final_application_package",
                destination=str(package_directory),
                application_id=application_id,
            )
            return FinalizationResult(
                package_directory=package_directory,
                cv_source=cv_source,
                cover_letter_source=cover_source,
                cv_pdf=cv_pdf,
                cover_letter_pdf=cover_pdf,
                manifest=manifest,
            )
        except Exception as exc:
            self.repository.log_filesystem(
                "finalize_application_failed",
                f"{cv_source} | {cover_source}",
                f"{type(exc).__name__}: {exc}",
                application_id,
            )
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def generate_cover_letter(self, application_id: int) -> Path:
        app = self.repository.get(application_id)
        if app is None:
            raise KeyError(f"Application {application_id} was not found.")

        required_content = {
            "MOTIVATION_PARAGRAPH": app.cover_motivation,
            "RELEVANT_EXPERIENCE_PARAGRAPH": app.cover_relevant_experience,
            "VALUE_PROPOSITION_PARAGRAPH": app.cover_value_proposition,
            "CLOSING_PARAGRAPH": app.cover_closing,
        }
        missing = [name for name, value in required_content.items() if not value.strip()]
        if missing:
            labels = ", ".join(name.replace("_", " ").title() for name in missing)
            raise ValueError(f"Complete these cover-letter fields first: {labels}.")

        language = app.application_language
        configured_template = self.settings.cover_template(language)
        current = Path(app.cover_letter_file) if app.cover_letter_file else None
        if current and current.is_file() and template_tokens(current):
            source = current
        elif configured_template and configured_template.is_file():
            source = configured_template
        else:
            raise FileNotFoundError(f"No usable {language} cover-letter template is configured.")

        if app.application_date:
            parsed_date = date.fromisoformat(app.application_date)
        else:
            parsed_date = datetime.now().astimezone()
        date_text = parsed_date.strftime(self.settings.date_format)
        if app.job_id:
            job_reference = (
                f" | Kennziffer {app.job_id}" if language == "DE" else f" | Reference {app.job_id}"
            )
        else:
            job_reference = ""
        subject = (
            f"Bewerbung als {app.job_title}{job_reference}"
            if language == "DE"
            else f"Application for {app.job_title}{job_reference}"
        )
        default_salutation = (
            "Sehr geehrte Damen und Herren," if language == "DE" else "Dear Hiring Team,"
        )
        values = {
            "COMPANY_NAME": app.company,
            "CONTACT_LINE": app.cover_contact_line or app.contact_name,
            "COMPANY_ADDRESS_LINE_1": app.company_address_line_1,
            "COMPANY_ADDRESS_LINE_2": app.company_address_line_2,
            "DATE": date_text,
            "SUBJECT_LINE": subject,
            "SALUTATION": app.cover_salutation or default_salutation,
            **required_content,
            "OPTIONAL_CONTEXT_PARAGRAPH": app.cover_optional_context,
        }
        destination = next_version_path(
            Path(app.application_directory) / "01_Application" / "Cover_Letter",
            f"Cover_Letter_{sanitize_component(self.settings.applicant_name)}_"
            f"{language}_{sanitize_component(app.company)}_"
            f"{sanitize_component(app.job_id or app.job_title)}",
            ".docx",
        )
        render_template(
            source,
            destination,
            values,
            removable_tokens={
                "CONTACT_LINE",
                "COMPANY_ADDRESS_LINE_1",
                "COMPANY_ADDRESS_LINE_2",
                "OPTIONAL_CONTEXT_PARAGRAPH",
            },
        )
        self.repository.update(application_id, {"cover_letter_file": str(destination)})
        self.repository.log_filesystem(
            "generate_cover_letter_from_explicit_template",
            str(source),
            str(destination),
            application_id,
        )
        return destination
