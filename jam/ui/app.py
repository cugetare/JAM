from __future__ import annotations

import csv
import html
import io
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

import streamlit as st

from jam.config import (
    AI_MODES,
    STRATEGY_LANGUAGES,
    Settings,
    load_settings,
    save_settings,
)
from jam.domain.ai import AgentAnalysis, CoverLetterContent
from jam.domain.candidate import (
    CandidateIdentity,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    LanguageSkill,
    SkillGroup,
)
from jam.domain.models import APPLICATION_STATUSES, Application, ApplicationInput
from jam.persistence import AgentRunRepository, ApplicationRepository, Database
from jam.security import (
    delete_openai_api_key,
    openai_api_key_source,
    save_openai_api_key,
    stored_openai_api_key_exists,
)
from jam.services import ApplicationService
from jam.services.ai import AIAnalysisService, OpenAIProvider
from jam.services.ai.analysis import read_local_text, save_local_text
from jam.services.candidate_profile import (
    active_candidate_profile_path,
    candidate_facts_for_ai,
    create_candidate_profile,
    import_cv,
    list_candidate_profiles,
    load_candidate_profile,
    parse_cv_docx,
    profile_display_name,
    save_candidate_profile,
    save_profile_photo,
)
from jam.services.documents import template_tokens
from jam.services.excel import export_bewerbungsliste, preview_rows
from jam.services.filesystem import open_path
from jam.services.importer import ImportCandidate, import_candidate, scan_existing
from jam.services.metadata import extract_metadata
from jam.services.pdf import preferred_pdf_converter
from jam.services.runtime import schedule_shutdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

NEW_APPLICATION_WIDGET_KEYS = {
    "company": "new_company",
    "job_title": "new_title",
    "job_id": "new_job_id",
    "location": "new_location",
    "job_url": "new_url",
    "contact_email": "new_email",
    "application_language": "new_language",
}


def _apply_extracted_suggestions(suggestions: dict[str, str]) -> None:
    for field, value in suggestions.items():
        if widget_key := NEW_APPLICATION_WIDGET_KEYS.get(field):
            st.session_state[widget_key] = value


def _new_form_metadata(raw_jd: str) -> dict[str, str]:
    extracted = extract_metadata(raw_jd)
    state_fields = {
        "company": "new_company",
        "job_title": "new_title",
        "job_id": "new_job_id",
        "location": "new_location",
        "country": "new_country",
        "job_url": "new_url",
        "source": "new_source",
        "contact_name": "new_contact",
        "contact_email": "new_email",
        "salary_expectation": "new_salary",
        "work_model": "new_work_model",
        "office_days": "new_office_days",
        "application_language": "new_language",
    }
    for field, widget_key in state_fields.items():
        value = str(st.session_state.get(widget_key, "") or "").strip()
        if value:
            extracted[field] = value
    return extracted


def _apply_ai_to_new_form(analysis: AgentAnalysis) -> None:
    changes = analysis.application_changes()
    widget_fields = {
        "company": "new_company",
        "job_title": "new_title",
        "job_id": "new_job_id",
        "location": "new_location",
        "country": "new_country",
        "job_url": "new_url",
        "source": "new_source",
        "contact_name": "new_contact",
        "contact_email": "new_email",
        "salary_expectation": "new_salary",
        "work_model": "new_work_model",
        "office_days": "new_office_days",
        "application_language": "new_language",
        "application_strategy": "new_strategy",
        "next_action": "new_next_action",
    }
    for field, widget_key in widget_fields.items():
        if field in changes:
            st.session_state[widget_key] = changes[field]
    st.session_state["new_ai_application_changes"] = changes


def _show_agent_analysis(analysis: AgentAnalysis) -> None:
    score, language = st.columns(2)
    score.metric("Match score", f"{analysis.match_score}/100")
    language.metric("Language", analysis.metadata.application_language)
    st.markdown("**Match summary**")
    st.write(analysis.match_summary)
    metadata_rows = []
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
        suggestion = getattr(analysis.metadata, field_name)
        if suggestion.value or suggestion.evidence:
            metadata_rows.append(
                {
                    "Field": field_name.replace("_", " ").title(),
                    "Suggested value": suggestion.value,
                    "Confidence": f"{suggestion.confidence:.0%}",
                    "Evidence": suggestion.evidence,
                }
            )
    if metadata_rows:
        st.dataframe(metadata_rows, width="stretch", hide_index=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**Strengths**")
        st.write(analysis.strengths)
        st.markdown("**Gaps**")
        st.write(analysis.gaps)
    with right:
        st.markdown("**Transferable experience**")
        st.write(analysis.transferable_experience)
        st.markdown("**Risks**")
        st.write(analysis.risks)
    st.markdown("**Application strategy**")
    st.write(analysis.application_strategy)
    st.markdown("**Recommended CV changes**")
    st.write(analysis.recommended_cv_changes)
    if analysis.cover_letter is not None:
        with st.expander("Proposed cover-letter content"):
            st.write(analysis.cover_letter.salutation)
            st.write(analysis.cover_letter.motivation)
            st.write(analysis.cover_letter.relevant_experience)
            st.write(analysis.cover_letter.value_proposition)
            if analysis.cover_letter.optional_context:
                st.write(analysis.cover_letter.optional_context)
            st.write(analysis.cover_letter.closing)
    if analysis.assumptions:
        st.caption("Assumptions: " + " | ".join(analysis.assumptions))


@st.cache_resource
def _repository(database_path: str) -> ApplicationRepository:
    database = Database(database_path)
    database.initialize()
    return ApplicationRepository(database)


@st.cache_resource
def _agent_repository(database_path: str) -> AgentRunRepository:
    database = Database(database_path)
    database.initialize()
    return AgentRunRepository(database)


def _context() -> tuple[Settings, ApplicationRepository, AgentRunRepository, ApplicationService]:
    settings = load_settings()
    repository = _repository(settings.database_path)
    agent_repository = _agent_repository(settings.database_path)
    return (
        settings,
        repository,
        agent_repository,
        ApplicationService(settings, repository),
    )


def _ai_service(settings: Settings, repository: AgentRunRepository) -> AIAnalysisService:
    provider = OpenAIProvider(
        model=settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        max_output_tokens=int(settings.openai_max_output_tokens),
    )
    return AIAnalysisService(repository, provider)


def _batch_ai_service(
    settings: Settings, repository: AgentRunRepository
) -> AIAnalysisService:
    provider = OpenAIProvider(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        max_output_tokens=int(settings.openai_max_output_tokens),
    )
    return AIAnalysisService(repository, provider)


def _ai_data_sharing_enabled(settings: Settings) -> bool:
    return str(settings.openai_data_sharing_enabled).strip().lower() == "true"


def _candidate_context(settings: Settings, language: str = "EN") -> str:
    return candidate_facts_for_ai(
        _active_profile_path(settings),
        settings.candidate_facts_path,
        language,
    )


def _active_profile_path(settings: Settings) -> Path:
    return active_candidate_profile_path(
        settings.candidate_profile_path,
        settings.active_candidate_profile_id,
    )


def _ai_unavailable_message(settings: Settings) -> None:
    if not _ai_data_sharing_enabled(settings):
        st.warning(
            "OpenAI data sharing is disabled. Enable it once in "
            "Settings → AI Assistant to use AI features.",
            icon=":material/privacy_tip:",
        )


def _open_button(label: str, path: str, key: str) -> None:
    if path and st.button(label, key=key):
        try:
            open_path(path)
        except Exception as exc:
            st.error(str(exc))


def _application_input(
    defaults: dict[str, str],
    prefix: str = "",
    job_description_text: str | None = None,
) -> ApplicationInput:
    left, right = st.columns(2)
    with left:
        company = st.text_input("Company *", defaults.get("company", ""), key=f"{prefix}company")
        job_title = st.text_input(
            "Job title *", defaults.get("job_title", ""), key=f"{prefix}title"
        )
        job_id = st.text_input("Job ID", defaults.get("job_id", ""), key=f"{prefix}job_id")
        location = st.text_input("Location", defaults.get("location", ""), key=f"{prefix}location")
        country = st.text_input("Country", defaults.get("country", ""), key=f"{prefix}country")
        job_url = st.text_input("Job URL", defaults.get("job_url", ""), key=f"{prefix}url")
        source = st.text_input("Source", defaults.get("source", ""), key=f"{prefix}source")
        contact_name = st.text_input(
            "Contact person", defaults.get("contact_name", ""), key=f"{prefix}contact"
        )
        contact_email = st.text_input(
            "Contact email", defaults.get("contact_email", ""), key=f"{prefix}email"
        )
    with right:
        language = st.selectbox(
            "Application language",
            ["DE", "EN"],
            index=0 if defaults.get("application_language", "DE") == "DE" else 1,
            key=f"{prefix}language",
        )
        salary = st.text_input(
            "Salary expectation", defaults.get("salary_expectation", ""), key=f"{prefix}salary"
        )
        work_model = st.text_input(
            "Work model", defaults.get("work_model", ""), key=f"{prefix}work_model"
        )
        office_days = st.text_input(
            "Office days", defaults.get("office_days", ""), key=f"{prefix}office_days"
        )
        strategy = st.text_area(
            "Application strategy",
            defaults.get("application_strategy", ""),
            key=f"{prefix}strategy",
        )
        notes = st.text_area(
            "Personal notes", defaults.get("personal_notes", ""), key=f"{prefix}notes"
        )
        next_action = st.text_input(
            "Next action", defaults.get("next_action", ""), key=f"{prefix}next_action"
        )
        next_date = st.text_input(
            "Next action date (YYYY-MM-DD)",
            defaults.get("next_action_date", ""),
            key=f"{prefix}next_date",
        )
    if job_description_text is None:
        jd = st.text_area(
            "Original job description",
            defaults.get("job_description_text", ""),
            height=300,
            key=f"{prefix}jd",
        )
    else:
        jd = job_description_text
        st.caption(f"The pasted job description ({len(jd)} characters) will be saved.")
    return ApplicationInput(
        company=company,
        job_title=job_title,
        job_id=job_id,
        location=location,
        country=country,
        job_url=job_url,
        source=source,
        contact_name=contact_name,
        contact_email=contact_email,
        application_language=language,
        job_description_text=jd,
        application_strategy=strategy,
        personal_notes=notes,
        salary_expectation=salary,
        work_model=work_model,
        office_days=office_days,
        next_action=next_action,
        next_action_date=next_date,
    )


def dashboard(repository: ApplicationRepository) -> None:
    st.header("Dashboard")
    st.button(
        "Start a new application",
        icon=":material/add:",
        type="primary",
        on_click=lambda: st.session_state.update(
            {"main_navigation": "Application Wizard"}
        ),
    )
    summary = repository.dashboard()
    columns = st.columns(5)
    metrics = (
        ("Total", summary["total"]),
        ("Submitted this month", summary["submitted_this_month"]),
        ("Follow-ups", summary["upcoming_followups"]),
        ("Interviews", summary["interviews"]),
        ("Waiting", summary["waiting"]),
    )
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)
    st.subheader("Applications by status")
    if summary["by_status"]:
        st.bar_chart(summary["by_status"])
    else:
        st.info("No applications yet.")
    recent = repository.list()[:8]
    if recent:
        st.subheader("Recently modified")
        st.dataframe(
            [
                {
                    "ID": app.id,
                    "Company": app.company,
                    "Position": app.job_title,
                    "Status": app.status,
                    "Next action": app.next_action,
                    "Follow-up": app.next_action_date,
                }
                for app in recent
            ],
            width="stretch",
            hide_index=True,
        )


WIZARD_STEPS = (
    "Analyze job",
    "Set strategy",
    "Prepare documents",
    "Finalize",
)


def _wizard_progress(step: int) -> None:
    columns = st.columns(len(WIZARD_STEPS))
    for index, (column, label) in enumerate(zip(columns, WIZARD_STEPS), start=1):
        with column:
            if index < step:
                st.badge(label, icon=":material/check:", color="green")
            elif index == step:
                st.badge(label, icon=":material/arrow_forward:", color="blue")
            else:
                st.badge(label, color="gray")
    st.progress(
        (step - 1) / (len(WIZARD_STEPS) - 1),
        text=f"Step {step} of {len(WIZARD_STEPS)}",
    )


def _reset_wizard() -> None:
    for key in tuple(st.session_state):
        if key.startswith("wizard_"):
            del st.session_state[key]


def _wizard_resume_step(app: Application) -> int:
    if app.finalized_at:
        return 4
    cover_content_complete = (
        app.cover_motivation.strip()
        and app.cover_relevant_experience.strip()
        and app.cover_value_proposition.strip()
        and app.cover_closing.strip()
    )
    cover_path = Path(app.cover_letter_file)
    cover_document_ready = False
    if cover_content_complete and cover_path.is_file():
        try:
            cover_document_ready = not template_tokens(cover_path)
        except (OSError, ValueError):
            cover_document_ready = False
    if cover_document_ready:
        return 4
    if app.status in {"Preparing", "Ready to Apply"}:
        return 3
    return 2


def _wizard_analysis_fields(analysis: AgentAnalysis, settings: Settings) -> None:
    changes = analysis.application_changes()
    values = {
        "wizard_company": changes.get("company", ""),
        "wizard_job_title": changes.get("job_title", ""),
        "wizard_job_id": changes.get("job_id", ""),
        "wizard_location": changes.get("location", ""),
        "wizard_country": changes.get("country", ""),
        "wizard_url": changes.get("job_url", ""),
        "wizard_source": changes.get("source", settings.default_source),
        "wizard_contact": changes.get("contact_name", ""),
        "wizard_email": changes.get("contact_email", ""),
        "wizard_salary": changes.get("salary_expectation", ""),
        "wizard_work_model": changes.get("work_model", ""),
        "wizard_office_days": changes.get("office_days", ""),
        "wizard_language": changes.get(
            "application_language", settings.default_application_language
        ),
        "wizard_strategy_draft": analysis.application_strategy,
    }
    for key, value in values.items():
        st.session_state[key] = value


def _wizard_create_application(
    *,
    raw_jd: str,
    analysis: AgentAnalysis,
    settings: Settings,
) -> ApplicationInput:
    changes = analysis.application_changes()
    return ApplicationInput(
        company=str(st.session_state.get("wizard_company", "")),
        job_title=str(st.session_state.get("wizard_job_title", "")),
        job_id=str(st.session_state.get("wizard_job_id", "")),
        location=str(st.session_state.get("wizard_location", "")),
        country=str(st.session_state.get("wizard_country", "")),
        job_url=str(st.session_state.get("wizard_url", "")),
        source=str(st.session_state.get("wizard_source", settings.default_source)),
        contact_name=str(st.session_state.get("wizard_contact", "")),
        contact_email=str(st.session_state.get("wizard_email", "")),
        application_language=str(
            st.session_state.get(
                "wizard_language", settings.default_application_language
            )
        ),
        job_description_text=raw_jd,
        application_strategy=str(
            st.session_state.get("wizard_strategy_draft", analysis.application_strategy)
        ),
        salary_expectation=str(st.session_state.get("wizard_salary", "")),
        work_model=str(st.session_state.get("wizard_work_model", "")),
        office_days=str(st.session_state.get("wizard_office_days", "")),
        status="Reviewing",
        next_action="Confirm the application strategy",
        match_score=changes["match_score"],
        match_summary=changes["match_summary"],
        strengths=changes["strengths"],
        transferable_experience=changes["transferable_experience"],
        gaps=changes["gaps"],
        risks=changes["risks"],
        recommended_cv_changes=changes["recommended_cv_changes"],
    )


def _wizard_resume(repository: ApplicationRepository) -> None:
    candidates = [
        app
        for app in repository.list()
        if app.status not in {"Rejected", "Withdrawn", "Accepted"}
    ]
    if not candidates:
        return
    with st.expander("Resume an existing application", icon=":material/history:"):
        labels = {
            f"{app.company} — {app.job_title} [{app.status}]": app.id
            for app in candidates
        }
        selection = st.selectbox(
            "Application",
            ("", *labels),
            key="wizard_resume_selection",
        )
        if st.button(
            "Resume",
            icon=":material/play_arrow:",
            disabled=not selection,
            key="wizard_resume_button",
        ):
            app_id = labels[selection]
            app = repository.get(app_id)
            assert app is not None
            st.session_state["wizard_app_id"] = app_id
            st.session_state["wizard_step"] = _wizard_resume_step(app)
            st.rerun()


def _wizard_step_analyze(
    settings: Settings,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
) -> None:
    st.subheader("Paste and analyze the job")
    st.caption(
        "Paste the complete job description. JAM will extract the role, evaluate "
        "your fit, and propose an application strategy."
    )
    raw_jd = st.text_area(
        "Job description",
        height=360,
        key="wizard_jd",
        placeholder="Paste the complete job description here…",
        persist_state="session",
    )
    key_available = bool(openai_api_key_source())
    if not key_available:
        st.warning(
            "Save an OpenAI API key in Settings before starting the analysis.",
            icon=":material/key:",
        )
    _ai_unavailable_message(settings)
    st.caption(
        f"Analysis mode: {settings.openai_model} · "
        f"{settings.openai_reasoning_effort} reasoning · "
        f"strategy discussion in {settings.strategy_language}"
    )
    analyze = st.button(
        "Analyze job",
        icon=":material/analytics:",
        type="primary",
        width="stretch",
        disabled=(
            not raw_jd.strip()
            or not key_available
            or not _ai_data_sharing_enabled(settings)
        ),
    )
    if analyze:  # noqa: SIM102 - keep the consent guard visible at the call site
        if _ai_data_sharing_enabled(settings):
            try:
                with st.status(
                    "Analyzing match and application strategy…",
                    expanded=True,
                ) as status:
                    status.write("Reading the job description")
                    run_id, analysis = _ai_service(
                        settings, agent_repository
                    ).analyze(
                        job_description=raw_jd,
                        candidate_facts=_candidate_context(
                            settings, settings.strategy_language
                        ),
                        agent_instructions=read_local_text(
                            settings.agent_instructions_path
                        ),
                        current_metadata=extract_metadata(raw_jd),
                        strategy_language=settings.strategy_language,
                    )
                    status.write("Validating structured recommendations")
                    status.update(
                        label="Analysis complete",
                        state="complete",
                        expanded=False,
                    )
                st.session_state["wizard_analysis_run_id"] = run_id
                st.session_state["wizard_analysis"] = analysis.model_dump()
                _wizard_analysis_fields(analysis, settings)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    analysis_data = st.session_state.get("wizard_analysis")
    if not analysis_data:
        return
    analysis = AgentAnalysis.model_validate(analysis_data)
    score_column, recommendation_column = st.columns([1, 3])
    score_column.metric("Match score", f"{analysis.match_score}/100")
    with recommendation_column.container(border=True):
        st.markdown("**Assessment**")
        st.write(analysis.match_summary)
    st.text_area(
        "Application strategy",
        height=180,
        key="wizard_strategy_draft",
        help=(
            "Edit the strategy now. The accepted version will be used when JAM "
            "generates the cover letter."
        ),
        persist_state="session",
    )
    with st.expander("Review extracted job details", expanded=True):
        company, title = st.columns(2)
        company.text_input(
            "Company *", key="wizard_company", persist_state="session"
        )
        title.text_input(
            "Job title *", key="wizard_job_title", persist_state="session"
        )
        location, job_id, language = st.columns(3)
        location.text_input(
            "Location", key="wizard_location", persist_state="session"
        )
        job_id.text_input("Job ID", key="wizard_job_id", persist_state="session")
        language.segmented_control(
            "Language",
            ("DE", "EN"),
            key="wizard_language",
            persist_state="session",
        )
        url, source = st.columns(2)
        url.text_input("Job URL", key="wizard_url", persist_state="session")
        source.text_input("Source", key="wizard_source", persist_state="session")
        with st.expander("Additional extracted details"):
            left, right = st.columns(2)
            left.text_input(
                "Country", key="wizard_country", persist_state="session"
            )
            left.text_input(
                "Contact person", key="wizard_contact", persist_state="session"
            )
            left.text_input(
                "Contact email", key="wizard_email", persist_state="session"
            )
            right.text_input(
                "Salary expectation",
                key="wizard_salary",
                persist_state="session",
            )
            right.text_input(
                "Work model", key="wizard_work_model", persist_state="session"
            )
            right.text_input(
                "Office days", key="wizard_office_days", persist_state="session"
            )
    with st.expander("Why this score?"):
        left, right = st.columns(2)
        left.markdown("**Strengths**")
        left.write(analysis.strengths)
        left.markdown("**Transferable experience**")
        left.write(analysis.transferable_experience)
        right.markdown("**Gaps**")
        right.write(analysis.gaps)
        right.markdown("**Risks**")
        right.write(analysis.risks)
    with st.container(horizontal=True, horizontal_alignment="right"):
        discard = st.button(
            "Discard analysis",
            icon=":material/close:",
            key="wizard_discard_analysis",
        )
        continue_with_job = st.button(
            "Keep this job and continue",
            icon=":material/arrow_forward:",
            type="primary",
        )
    if discard:
        _reset_wizard()
        st.rerun()
    if continue_with_job:
        try:
            data = _wizard_create_application(
                raw_jd=raw_jd,
                analysis=analysis,
                settings=settings,
            )
            app = service.create(data, copy_cv=True, copy_cover_letter=True)
            run_id = int(st.session_state["wizard_analysis_run_id"])
            agent_repository.mark_applied(run_id, app.id)
            st.session_state["wizard_app_id"] = app.id
            st.session_state["wizard_step"] = 2
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
            duplicate = service.find_duplicate(data) if "data" in locals() else None
            if duplicate:
                st.info(
                    f"This job is already application {duplicate.id}. "
                    "Resume it from the wizard start."
                )


def _wizard_step_strategy(
    app: Application,
    repository: ApplicationRepository,
) -> None:
    st.subheader("Confirm the application strategy")
    score, role = st.columns([1, 3])
    score.metric("Match score", f"{app.match_score}/100")
    with role.container(border=True):
        st.markdown(f"**{app.company} — {app.job_title}**")
        st.write(app.match_summary)
    strategy = st.text_area(
        "Your application strategy",
        app.application_strategy,
        height=240,
        key=f"wizard_strategy_{app.id}",
        help=(
            "This exact strategy is saved with the application and sent as context "
            "when the cover letter is generated."
        ),
    )
    with st.expander("Matching evidence"):
        left, right = st.columns(2)
        left.markdown("**Strengths**")
        left.write(app.strengths)
        left.markdown("**Transferable experience**")
        left.write(app.transferable_experience)
        right.markdown("**Gaps**")
        right.write(app.gaps)
        right.markdown("**Risks**")
        right.write(app.risks)
    if st.button(
        "Save strategy and continue",
        icon=":material/arrow_forward:",
        type="primary",
        width="stretch",
    ):
        try:
            repository.update(
                app.id,
                {
                    "application_strategy": strategy,
                    "status": "Preparing",
                    "next_action": "Review CV recommendations and prepare documents",
                },
                status_note="Application strategy confirmed in wizard",
            )
            st.session_state["wizard_step"] = 3
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _cover_from_application(app: Application) -> CoverLetterContent | None:
    required = (
        app.cover_motivation,
        app.cover_relevant_experience,
        app.cover_value_proposition,
        app.cover_closing,
    )
    if not all(value.strip() for value in required):
        return None
    return CoverLetterContent(
        salutation=app.cover_salutation,
        motivation=app.cover_motivation,
        relevant_experience=app.cover_relevant_experience,
        value_proposition=app.cover_value_proposition,
        optional_context=app.cover_optional_context,
        closing=app.cover_closing,
    )


def _wizard_step_documents(
    app: Application,
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
) -> None:
    st.subheader("Prepare the CV and cover letter")
    with st.container(border=True):
        st.markdown("#### CV recommendations")
        if app.recommended_cv_changes.strip():
            st.markdown(
                "\n".join(
                    f"- {line.lstrip('- ').strip()}"
                    for line in app.recommended_cv_changes.splitlines()
                    if line.strip()
                )
            )
        else:
            st.info("No CV changes were recommended.")
        st.caption(
            "JAM does not rewrite the CV yet. Apply these recommendations in the "
            "copied working document; automatic CV generation remains a future step."
        )
        _open_button("Open working CV", app.cv_file, f"wizard-open-cv-{app.id}")

    cover_content = None
    if cover_data := st.session_state.get(f"wizard_cover_content_{app.id}"):
        cover_content = CoverLetterContent.model_validate(cover_data)
    elif existing_cover := _cover_from_application(app):
        cover_content = existing_cover

    if cover_content is None:
        st.markdown("#### Generate the cover letter")
        st.write(
            "The draft will use the strategy you confirmed in the previous step."
        )
        key_available = bool(openai_api_key_source())
        if not key_available:
            st.warning(
                "Save an OpenAI API key in Settings before generating the draft.",
                icon=":material/key:",
            )
        _ai_unavailable_message(settings)
        if st.button(  # noqa: SIM102 - keep the consent guard visible at the call site
            "Generate cover-letter draft",
            icon=":material/edit_document:",
            type="primary",
            width="stretch",
            disabled=not key_available or not _ai_data_sharing_enabled(settings),
        ):
            if _ai_data_sharing_enabled(settings):
                try:
                    context = {
                        "company": app.company,
                        "job_title": app.job_title,
                        "application_language": app.application_language,
                        "contact_name": app.contact_name,
                        "match_summary": app.match_summary,
                        "strengths": app.strengths,
                        "transferable_experience": app.transferable_experience,
                        "gaps": app.gaps,
                        "application_strategy": app.application_strategy,
                    }
                    with st.status(
                        "Drafting the cover letter from your strategy…"
                    ) as status:
                        run_id, generated = _ai_service(
                            settings, agent_repository
                        ).generate_cover_letter(
                            job_description=app.job_description_text,
                            candidate_facts=_candidate_context(
                                settings, app.application_language
                            ),
                            agent_instructions=read_local_text(
                                settings.agent_instructions_path
                            ),
                            application_context=context,
                            application_id=app.id,
                        )
                        status.update(
                            label="Cover-letter draft ready",
                            state="complete",
                            expanded=False,
                        )
                    st.session_state[f"wizard_cover_run_{app.id}"] = run_id
                    st.session_state[f"wizard_cover_content_{app.id}"] = (
                        generated.model_dump()
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if st.button(
            "Back to strategy",
            icon=":material/arrow_back:",
            key=f"wizard_back_strategy_{app.id}",
        ):
            st.session_state["wizard_step"] = 2
            st.rerun()
        return

    st.markdown("#### Review the cover letter")
    st.caption(
        "Edit anything you want. Only the accepted text is inserted into a new "
        "template-based DOCX version."
    )
    with st.form(f"wizard_cover_form_{app.id}"):
        salutation = st.text_input("Salutation", cover_content.salutation)
        motivation = st.text_area(
            "Motivation", cover_content.motivation, height=110
        )
        experience = st.text_area(
            "Relevant experience", cover_content.relevant_experience, height=130
        )
        value = st.text_area(
            "Value proposition", cover_content.value_proposition, height=110
        )
        optional_context = st.text_area(
            "Optional context", cover_content.optional_context, height=90
        )
        closing = st.text_area("Closing", cover_content.closing, height=100)
        accept_cover = st.form_submit_button(
            "Accept and create cover-letter DOCX",
            icon=":material/check:",
            type="primary",
            width="stretch",
        )
    if accept_cover:
        try:
            repository.update(
                app.id,
                {
                    "cover_salutation": salutation,
                    "cover_motivation": motivation,
                    "cover_relevant_experience": experience,
                    "cover_value_proposition": value,
                    "cover_optional_context": optional_context,
                    "cover_closing": closing,
                    "next_action": "Review working documents and finalize PDFs",
                },
            )
            if run_id := st.session_state.get(f"wizard_cover_run_{app.id}"):
                agent_repository.mark_applied(int(run_id), app.id)
            service.generate_cover_letter(app.id)
            st.session_state["wizard_step"] = 4
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.button(
        "Back to strategy",
        icon=":material/arrow_back:",
        key=f"wizard_back_strategy_with_cover_{app.id}",
    ):
        st.session_state["wizard_step"] = 2
        st.rerun()


def _wizard_step_finalize(
    app: Application,
    repository: ApplicationRepository,
    service: ApplicationService,
) -> None:
    st.subheader("Review and finalize the application")
    try:
        latest_cv, latest_cover = service.latest_working_documents(app.id)
    except Exception as exc:
        latest_cv, latest_cover = None, None
        st.error(str(exc))
    left, right = st.columns(2)
    with left.container(border=True):
        st.markdown("**CV working document**")
        st.caption(latest_cv.name if latest_cv else "No DOCX found")
        _open_button(
            "Open CV",
            str(latest_cv or ""),
            f"wizard-final-cv-source-{app.id}",
        )
    with right.container(border=True):
        st.markdown("**Cover-letter working document**")
        st.caption(latest_cover.name if latest_cover else "No DOCX found")
        _open_button(
            "Open cover letter",
            str(latest_cover or ""),
            f"wizard-final-cover-source-{app.id}",
        )
    st.info(
        "Make your final edits, save and close both DOCX files, then create "
        f"the PDF package with {preferred_pdf_converter()}.",
        icon=":material/info:",
    )
    if st.button(
        "Finalize application and create PDFs",
        icon=":material/picture_as_pdf:",
        type="primary",
        width="stretch",
        disabled=latest_cv is None or latest_cover is None,
    ):
        try:
            with st.status("Creating the final PDF package…") as status:
                result = service.finalize_application(app.id)
                status.update(
                    label="Final application package created",
                    state="complete",
                    expanded=False,
                )
            st.success(str(result.package_directory))
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if app.finalized_at:
        st.success(
            "The application is ready for manual upload.",
            icon=":material/check_circle:",
        )
        actions = st.container(horizontal=True)
        with actions:
            _open_button(
                "Open CV PDF",
                app.finalized_cv_pdf,
                f"wizard-final-cv-{app.id}",
            )
            _open_button(
                "Open cover-letter PDF",
                app.finalized_cover_letter_pdf,
                f"wizard-final-cover-{app.id}",
            )
            _open_button(
                "Open package",
                str(Path(app.finalization_manifest).parent),
                f"wizard-final-folder-{app.id}",
            )
        submitted = st.checkbox(
            "I uploaded the documents and submitted the application",
            key=f"wizard_submitted_{app.id}",
        )
        if st.button(
            "Mark application as applied",
            icon=":material/send:",
            width="stretch",
            disabled=not submitted or app.status == "Applied",
        ):
            try:
                repository.update(
                    app.id,
                    {
                        "status": "Applied",
                        "next_action": "Record confirmation and schedule follow-up",
                    },
                    status_note="Manual submission confirmed in wizard",
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if app.status == "Applied":
            st.caption(
                f"Submitted on {app.application_date}; the transition is saved "
                "in status history."
            )
    with st.container(horizontal=True):
        if st.button(
            "Back to documents",
            icon=":material/arrow_back:",
            key=f"wizard_back_documents_{app.id}",
        ):
            st.session_state["wizard_step"] = 3
            st.rerun()
        if st.button(
            "Start another application",
            icon=":material/add:",
            key=f"wizard_start_another_{app.id}",
        ):
            _reset_wizard()
            st.rerun()


def new_application(
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
) -> None:
    st.header("Application wizard")
    st.caption(
        "From pasted job description to a final, auditable application package."
    )
    app_id = st.session_state.get("wizard_app_id")
    if not app_id:
        _wizard_resume(repository)
    step = int(st.session_state.get("wizard_step", 1))
    if app_id:
        app = repository.get(int(app_id))
        if app is None:
            _reset_wizard()
            st.warning("The selected application no longer exists.")
            st.rerun()
    else:
        app = None
        step = 1
    _wizard_progress(step)
    if step == 1:
        _wizard_step_analyze(settings, agent_repository, service)
    elif step == 2 and app is not None:
        _wizard_step_strategy(app, repository)
    elif step == 3 and app is not None:
        _wizard_step_documents(
            app,
            settings,
            repository,
            agent_repository,
            service,
        )
    elif step == 4 and app is not None:
        _wizard_step_finalize(app, repository, service)

    st.space("large")
    use_advanced = st.toggle(
        "Show advanced application form",
        help="Use the original all-fields form for exceptional or offline cases.",
        key="wizard_show_advanced",
    )
    if use_advanced:
        _advanced_new_application(settings, repository, agent_repository, service)


def _advanced_new_application(
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
) -> None:
    st.subheader("Advanced application form")
    st.caption(
        "JAM copies configured masters into a new working folder. It never edits DOCX content."
    )
    raw_jd = st.text_area(
        "Paste a job description to extract initial suggestions",
        height=180,
        key="new_raw_jd",
    )
    local_action, ai_action = st.columns(2)
    if local_action.button("Extract suggestions"):
        if not raw_jd.strip():
            st.warning("Paste a job description first.")
        else:
            suggestions = extract_metadata(raw_jd)
            _apply_extracted_suggestions(suggestions)
            detected = [
                field.replace("_", " ")
                for field in suggestions
                if field != "application_language"
            ]
            if detected:
                st.success(
                    "Detected: " + ", ".join(detected) + ". Review and correct the fields below."
                )
            else:
                st.info(
                    "The description and language were copied. No labelled company, "
                    "title, job ID, location, URL, or email was detected; enter those "
                    "fields manually."
                )
    _ai_unavailable_message(settings)
    if ai_action.button("Analyze JD with AI"):
        if not raw_jd.strip():
            st.warning("Paste a job description first.")
        elif not _ai_data_sharing_enabled(settings):
            _ai_unavailable_message(settings)
        else:
            try:
                with st.spinner("Analyzing the JD..."):
                    run_id, analysis = _ai_service(settings, agent_repository).analyze(
                        job_description=raw_jd,
                        candidate_facts=_candidate_context(
                            settings, settings.strategy_language
                        ),
                        agent_instructions=read_local_text(
                            settings.agent_instructions_path
                        ),
                        current_metadata=_new_form_metadata(raw_jd),
                        strategy_language=settings.strategy_language,
                    )
                st.session_state["new_ai_run_id"] = run_id
                st.session_state["new_ai_analysis"] = analysis.model_dump()
                st.success("AI analysis completed. Review it before accepting.")
            except Exception as exc:
                st.error(str(exc))
    if analysis_data := st.session_state.get("new_ai_analysis"):
        analysis = AgentAnalysis.model_validate(analysis_data)
        with st.expander("AI analysis preview", expanded=True):
            _show_agent_analysis(analysis)
            if st.button("Accept AI suggestions into the application form"):
                _apply_ai_to_new_form(analysis)
                run_id = int(st.session_state["new_ai_run_id"])
                agent_repository.mark_applied(run_id)
                st.success("Suggestions applied. Review the form before creating the record.")
                st.rerun()
    defaults = {
        "application_language": settings.default_application_language,
        "source": settings.default_source,
    }
    with st.form("new_application_form"):
        data = _application_input(defaults, "new_", job_description_text=raw_jd)
        for field, value in st.session_state.get("new_ai_application_changes", {}).items():
            if hasattr(data, field):
                setattr(data, field, value)
        copy_cv = st.checkbox("Copy configured master CV", value=True)
        copy_cover = st.checkbox("Copy configured cover-letter template", value=True)
        submitted = st.form_submit_button("Create application")
    if submitted:
        try:
            planned = service.planned_path(data)
            app = service.create(data, copy_cv=copy_cv, copy_cover_letter=copy_cover)
            if run_id := st.session_state.get("new_ai_run_id"):
                agent_repository.attach(int(run_id), app.id)
            st.success(f"Created application {app.id} at {planned}")
            for state_key in (
                "new_ai_run_id",
                "new_ai_analysis",
                "new_ai_application_changes",
            ):
                st.session_state.pop(state_key, None)
        except Exception as exc:
            st.error(str(exc))
            duplicate = service.find_duplicate(data)
            if duplicate:
                st.info(
                    f"Existing record: {duplicate.id} — {duplicate.company}, {duplicate.job_title}"
                )


def application_list(
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
) -> None:
    st.header("Application List")
    selected_application_id = st.session_state.get("selected_application_id")
    if selected_application_id:
        if st.button(
            "Back to application list",
            icon=":material/arrow_back:",
            key="back_to_application_list",
        ):
            st.session_state.pop("selected_application_id", None)
            st.session_state["application_table_generation"] = (
                int(st.session_state.get("application_table_generation", 0)) + 1
            )
            st.rerun()
        application_details(
            settings,
            repository,
            agent_repository,
            service,
            application_id=int(selected_application_id),
            embedded=True,
        )
        return

    view = st.segmented_control(
        "List view",
        ("Applications", "Bewerbungsliste"),
        default="Applications",
        required=True,
        key="application_list_view",
        width="stretch",
    )
    if view == "Bewerbungsliste":
        bewerbungsliste(settings, repository, embedded=True)
        return

    st.caption("Select any row to open the complete application record.")
    applications_all = repository.list()
    sources = sorted({app.source for app in applications_all if app.source})
    col1, col2, col3, col4 = st.columns(4)
    query = col1.text_input("Search")
    status = col2.selectbox("Status", [""] + list(APPLICATION_STATUSES))
    language = col3.selectbox("Language", ["", "DE", "EN"])
    source = col4.selectbox("Source", [""] + sources)
    applications = repository.list(
        query=query,
        status=status,
        language=language,
        source=source,
    )
    rows = [
        {
            "ID": app.id,
            "Company": app.company,
            "Position": app.job_title,
            "Job ID": app.job_id,
            "Location": app.location,
            "Language": app.application_language,
            "Status": app.status,
            "Application date": app.application_date,
            "Next action": app.next_action_date,
        }
        for app in applications
    ]
    table_generation = int(st.session_state.get("application_table_generation", 0))
    table_event = st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        key=f"application_table_{table_generation}",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small", pinned=True),
            "Company": st.column_config.TextColumn("Company", pinned=True),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        },
    )
    if table_event.selection.rows:
        selected_row = int(table_event.selection.rows[0])
        if 0 <= selected_row < len(rows):
            st.session_state["selected_application_id"] = rows[selected_row]["ID"]
            st.rerun()
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    st.download_button(
        "Download CSV",
        buffer.getvalue().encode("utf-8-sig"),
        "applications.csv",
        "text/csv",
    )


def application_details(
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
    service: ApplicationService,
    *,
    application_id: int | None = None,
    embedded: bool = False,
) -> None:
    if not embedded:
        st.header("Application Details")
    applications = repository.list()
    if not applications:
        st.info("Create or import an application first.")
        return
    if application_id is None:
        labels = {
            f"{app.id}: {app.company} — {app.job_title}": app.id
            for app in applications
        }
        selection = st.selectbox("Application", list(labels))
        app = repository.get(labels[selection])
        assert app is not None
    else:
        app = repository.get(application_id)
        if app is None:
            st.error(f"Application {application_id} was not found.")
            return
        st.subheader(f"{app.company} — {app.job_title}")
        st.badge(app.status, icon=":material/work:")
    st.caption(app.application_directory)
    recoverable_jd = str(st.session_state.get("new_raw_jd", "") or "").strip()
    if not app.job_description_text.strip():
        st.warning(
            "This application has no saved job description. AI analysis and "
            "cover-letter generation cannot continue until it is restored."
        )
        if recoverable_jd:
            st.info(
                f"The current Application Wizard draft still contains "
                f"{len(recoverable_jd)} JD characters."
            )
            if st.button(
                "Recover JD from current Application Wizard draft",
                key=f"recover_jd_{app.id}",
            ):
                try:
                    service.update_job_description(app.id, recoverable_jd)
                    st.success("The JD was restored to the database and local file.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _open_button("Open folder", app.application_directory, f"folder-{app.id}")
    with col2:
        _open_button("Open CV", app.cv_file, f"cv-{app.id}")
    with col3:
        _open_button("Open cover letter", app.cover_letter_file, f"cover-{app.id}")
    with col4:
        _open_button(
            "Open JD",
            str(Path(app.application_directory) / "00_JD" / "JD_original.txt"),
            f"jd-{app.id}",
        )
    with st.form(f"details-{app.id}"):
        left, right = st.columns(2)
        company = left.text_input("Company", app.company)
        job_title = left.text_input("Job title", app.job_title)
        job_id = left.text_input("Job ID", app.job_id)
        location = left.text_input("Location", app.location)
        job_url = left.text_input("Job URL", app.job_url)
        status = left.selectbox(
            "Status", APPLICATION_STATUSES, index=APPLICATION_STATUSES.index(app.status)
        )
        application_date = left.text_input("Application date (YYYY-MM-DD)", app.application_date)
        next_action = left.text_input("Next action", app.next_action)
        next_action_date = left.text_input("Next action date (YYYY-MM-DD)", app.next_action_date)
        status_note = left.text_input("Status change note")
        strategy = right.text_area("Application strategy", app.application_strategy)
        notes = right.text_area("Personal notes", app.personal_notes)
        match_score = right.text_input("Match score", app.match_score)
        recommendations = st.text_area(
            "Recommended CV changes (structured recommendations only)",
            app.recommended_cv_changes,
            height=160,
        )
        match_summary = st.text_area("Match summary", app.match_summary)
        strengths = st.text_area("Strengths", app.strengths)
        transferable = st.text_area("Transferable experience", app.transferable_experience)
        gaps = st.text_area("Gaps", app.gaps)
        risks = st.text_area("Risks", app.risks)
        original_jd = st.text_area(
            "Original job description",
            app.job_description_text,
            height=300,
            help=(
                "Saving a replacement keeps the previous non-empty JD as a "
                "versioned local backup."
            ),
        )
        cover_draft = st.text_area("Cover-letter draft", app.cover_letter_draft, height=160)
        final_notes = st.text_area("Final application notes", app.final_application_notes)
        st.markdown("#### Template-based cover letter")
        company_address_1 = st.text_input("Company address line 1", app.company_address_line_1)
        company_address_2 = st.text_input("Company address line 2", app.company_address_line_2)
        cover_contact = st.text_input(
            "Cover-letter contact line", app.cover_contact_line or app.contact_name
        )
        cover_salutation = st.text_input(
            "Salutation",
            app.cover_salutation
            or (
                "Sehr geehrte Damen und Herren,"
                if app.application_language == "DE"
                else "Dear Hiring Team,"
            ),
        )
        cover_motivation = st.text_area("Motivation paragraph", app.cover_motivation)
        cover_experience = st.text_area(
            "Relevant experience paragraph", app.cover_relevant_experience
        )
        cover_value = st.text_area("Value proposition paragraph", app.cover_value_proposition)
        cover_context = st.text_area("Optional context paragraph", app.cover_optional_context)
        cover_closing = st.text_area("Closing paragraph", app.cover_closing)
        save = st.form_submit_button("Save changes")
    if save:
        try:
            if original_jd.strip() != app.job_description_text.strip():
                service.update_job_description(app.id, original_jd)
            repository.update(
                app.id,
                {
                    "company": company,
                    "job_title": job_title,
                    "job_id": job_id,
                    "location": location,
                    "job_url": job_url,
                    "status": status,
                    "application_date": application_date,
                    "next_action": next_action,
                    "next_action_date": next_action_date,
                    "application_strategy": strategy,
                    "personal_notes": notes,
                    "recommended_cv_changes": recommendations,
                    "match_score": match_score,
                    "match_summary": match_summary,
                    "strengths": strengths,
                    "transferable_experience": transferable,
                    "gaps": gaps,
                    "risks": risks,
                    "cover_letter_draft": cover_draft,
                    "final_application_notes": final_notes,
                    "company_address_line_1": company_address_1,
                    "company_address_line_2": company_address_2,
                    "cover_contact_line": cover_contact,
                    "cover_salutation": cover_salutation,
                    "cover_motivation": cover_motivation,
                    "cover_relevant_experience": cover_experience,
                    "cover_value_proposition": cover_value,
                    "cover_optional_context": cover_context,
                    "cover_closing": cover_closing,
                },
                status_note=status_note,
            )
            st.success("Changes saved.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    action1, action2, action3, action4 = st.columns(4)
    if action1.button("Export AI Brief"):
        try:
            st.success(f"Exported {service.export_ai_brief(app.id)}")
        except Exception as exc:
            st.error(str(exc))
    if action2.button("New CV working version", disabled=not bool(app.cv_file)):
        try:
            st.success(f"Created {service.create_working_document_version(app.id, 'cv')}")
        except Exception as exc:
            st.error(str(exc))
    if action3.button("New cover-letter working version", disabled=not bool(app.cover_letter_file)):
        try:
            st.success(f"Created {service.create_working_document_version(app.id, 'cover_letter')}")
        except Exception as exc:
            st.error(str(exc))
    if action4.button("Generate cover letter from template"):
        try:
            st.success(f"Generated {service.generate_cover_letter(app.id)}")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Final application package")
    try:
        latest_cv, latest_cover = service.latest_working_documents(app.id)
    except Exception as exc:
        latest_cv, latest_cover = None, None
        st.error(str(exc))
    cv_source_column, cover_source_column = st.columns(2)
    cv_source_column.markdown("**Latest CV DOCX**")
    cv_source_column.caption(latest_cv.name if latest_cv else "Not found")
    cover_source_column.markdown("**Latest cover-letter DOCX**")
    cover_source_column.caption(latest_cover.name if latest_cover else "Not found")
    st.caption(
        "Save and close both DOCX files before finalizing. "
        f"JAM will use {preferred_pdf_converter()} and never modifies the sources."
    )
    if st.button(
        "Finalize Application (create PDFs)",
        key=f"finalize_application_{app.id}",
        type="primary",
        width="stretch",
        disabled=latest_cv is None or latest_cover is None,
    ):
        try:
            with st.spinner(
                f"Exporting the latest DOCX versions with {preferred_pdf_converter()}..."
            ):
                result = service.finalize_application(app.id)
            st.success(
                f"Final package created with CV and cover-letter PDFs: "
                f"{result.package_directory}"
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if app.finalized_at:
        st.caption(f"Last finalized: {app.finalized_at}")
        final_cv_action, final_cover_action, final_folder_action = st.columns(3)
        with final_cv_action:
            _open_button("Open final CV PDF", app.finalized_cv_pdf, f"final-cv-{app.id}")
        with final_cover_action:
            _open_button(
                "Open final cover-letter PDF",
                app.finalized_cover_letter_pdf,
                f"final-cover-{app.id}",
            )
        with final_folder_action:
            final_folder = (
                str(Path(app.finalization_manifest).parent)
                if app.finalization_manifest
                else ""
            )
            _open_button("Open final package", final_folder, f"final-folder-{app.id}")

    st.subheader("AI application analyst")
    _ai_unavailable_message(settings)
    ai_allowed = _ai_data_sharing_enabled(settings)
    current_metadata = {
        field: str(getattr(app, field) or "")
        for field in (
            "company",
            "job_title",
            "job_id",
            "location",
            "country",
            "job_url",
            "source",
            "contact_name",
            "contact_email",
            "application_language",
            "salary_expectation",
            "work_model",
            "office_days",
        )
    }
    analyze_action, queue_action, refresh_action, cover_action = st.columns(4)
    analyze_now = analyze_action.button(
        "Analyze now",
        key=f"analyze_app_{app.id}",
        width="stretch",
        disabled=not bool(app.job_description_text.strip()) or not ai_allowed,
    )
    queue_analysis = queue_action.button(
        "Queue low-cost analysis",
        key=f"queue_analysis_{app.id}",
        width="stretch",
        disabled=not bool(app.job_description_text.strip()) or not ai_allowed,
    )
    refresh_queue = refresh_action.button(
        "Check queued analysis",
        key=f"refresh_analysis_{app.id}",
        width="stretch",
        disabled=not ai_allowed,
    )
    generate_cover = cover_action.button(
        "Generate cover-letter content",
        key=f"generate_cover_{app.id}",
        width="stretch",
        disabled=not bool(app.job_description_text.strip()) or not ai_allowed,
    )
    if analyze_now:  # noqa: SIM102 - keep the consent guard visible at the call site
        if ai_allowed:
            try:
                with st.spinner("Analyzing the application..."):
                    run_id, analysis = _ai_service(settings, agent_repository).analyze(
                        job_description=app.job_description_text,
                        candidate_facts=_candidate_context(
                            settings, settings.strategy_language
                        ),
                        agent_instructions=read_local_text(
                            settings.agent_instructions_path
                        ),
                        current_metadata=current_metadata,
                        strategy_language=settings.strategy_language,
                        application_id=app.id,
                    )
                st.session_state[f"detail_ai_run_{app.id}"] = run_id
                st.session_state[f"detail_ai_analysis_{app.id}"] = analysis.model_dump()
                st.success("AI analysis completed. Review changes before accepting.")
            except Exception as exc:
                st.error(str(exc))
    if queue_analysis:  # noqa: SIM102 - keep the consent guard visible at the call site
        if ai_allowed:
            try:
                with st.spinner("Submitting low-cost Luna/low Batch analysis..."):
                    run_id = _batch_ai_service(
                        settings, agent_repository
                    ).queue_analysis(
                        job_description=app.job_description_text,
                        candidate_facts=_candidate_context(
                            settings, settings.strategy_language
                        ),
                        agent_instructions=read_local_text(
                            settings.agent_instructions_path
                        ),
                        current_metadata=current_metadata,
                        strategy_language=settings.strategy_language,
                        application_id=app.id,
                    )
                st.success(
                    f"Analysis queued as run {run_id}. Use “Check queued analysis” "
                    "later to retrieve it."
                )
            except Exception as exc:
                st.error(str(exc))
    if refresh_queue:
        try:
            with st.spinner("Checking OpenAI Batch status..."):
                completed = _batch_ai_service(
                    settings, agent_repository
                ).refresh_queued(app.id)
            if completed:
                run_id, analysis = completed[-1]
                st.session_state[f"detail_ai_run_{app.id}"] = run_id
                st.session_state[f"detail_ai_analysis_{app.id}"] = (
                    analysis.model_dump()
                )
                st.success("Queued analysis completed. Review it below.")
            elif agent_repository.list_queued(app.id):
                st.info("The queued analysis is still processing.")
            else:
                latest_batch = agent_repository.latest(
                    application_id=app.id,
                    run_type="application_analysis_batch",
                )
                if latest_batch and latest_batch.result_json:
                    analysis = agent_repository.analysis(latest_batch.id)
                    st.session_state[f"detail_ai_run_{app.id}"] = latest_batch.id
                    st.session_state[f"detail_ai_analysis_{app.id}"] = (
                        analysis.model_dump()
                    )
                    st.success("Loaded the latest completed queued analysis.")
                elif latest_batch and latest_batch.error_message:
                    st.error(latest_batch.error_message)
                else:
                    st.info("There is no queued analysis for this application.")
        except Exception as exc:
            st.error(str(exc))
    if generate_cover:  # noqa: SIM102 - keep the consent guard visible at the call site
        if ai_allowed:
            try:
                application_context = {
                    "company": app.company,
                    "job_title": app.job_title,
                    "application_language": app.application_language,
                    "contact_name": app.contact_name,
                    "match_summary": app.match_summary,
                    "strengths": app.strengths,
                    "transferable_experience": app.transferable_experience,
                    "gaps": app.gaps,
                    "application_strategy": app.application_strategy,
                }
                with st.spinner("Drafting concise cover-letter content..."):
                    run_id, cover_content = _ai_service(
                        settings, agent_repository
                    ).generate_cover_letter(
                        job_description=app.job_description_text,
                        candidate_facts=_candidate_context(
                            settings, app.application_language
                        ),
                        agent_instructions=read_local_text(
                            settings.agent_instructions_path
                        ),
                        application_context=application_context,
                        application_id=app.id,
                    )
                st.session_state[f"detail_cover_run_{app.id}"] = run_id
                st.session_state[f"detail_cover_content_{app.id}"] = (
                    cover_content.model_dump()
                )
                st.success("Cover-letter content generated. Review it before accepting.")
            except Exception as exc:
                st.error(str(exc))
    if analysis_data := st.session_state.get(f"detail_ai_analysis_{app.id}"):
        analysis = AgentAnalysis.model_validate(analysis_data)
        with st.expander("AI analysis and proposed changes", expanded=True):
            _show_agent_analysis(analysis)
            changes = analysis.application_changes()
            differences = [
                {
                    "Field": field.replace("_", " ").title(),
                    "Current": str(getattr(app, field, "") or ""),
                    "Proposed": value,
                }
                for field, value in changes.items()
                if str(getattr(app, field, "") or "") != value
            ]
            if differences:
                st.markdown("**Changes that will be applied**")
                st.dataframe(differences, width="stretch", hide_index=True)
            if st.button("Accept AI suggestions", key=f"accept_ai_{app.id}"):
                try:
                    repository.update(app.id, changes)
                    run_id = int(st.session_state[f"detail_ai_run_{app.id}"])
                    agent_repository.mark_applied(run_id, app.id)
                    st.success("AI suggestions saved. No documents were generated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    if cover_data := st.session_state.get(f"detail_cover_content_{app.id}"):
        cover_content = CoverLetterContent.model_validate(cover_data)
        with st.expander("Cover-letter content preview", expanded=True):
            st.write(cover_content.salutation)
            st.write(cover_content.motivation)
            st.write(cover_content.relevant_experience)
            st.write(cover_content.value_proposition)
            if cover_content.optional_context:
                st.write(cover_content.optional_context)
            st.write(cover_content.closing)
            if st.button("Accept cover-letter content", key=f"accept_cover_{app.id}"):
                try:
                    repository.update(
                        app.id,
                        {
                            "cover_salutation": cover_content.salutation,
                            "cover_motivation": cover_content.motivation,
                            "cover_relevant_experience": (
                                cover_content.relevant_experience
                            ),
                            "cover_value_proposition": (
                                cover_content.value_proposition
                            ),
                            "cover_optional_context": (
                                cover_content.optional_context
                            ),
                            "cover_closing": cover_content.closing,
                        },
                    )
                    run_id = int(st.session_state[f"detail_cover_run_{app.id}"])
                    agent_repository.mark_applied(run_id, app.id)
                    st.success(
                        "Cover-letter fields saved. The DOCX was not generated yet."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
    st.subheader("Status history")
    st.dataframe(
        [asdict(item) for item in repository.status_history(app.id)],
        width="stretch",
        hide_index=True,
    )
    with st.expander("Full job description"):
        st.text(app.job_description_text)


def bewerbungsliste(
    settings: Settings,
    repository: ApplicationRepository,
    *,
    embedded: bool = False,
) -> None:
    (st.subheader if embedded else st.header)("Bewerbungsliste")
    applications = repository.list()
    st.caption(
        "Preview of rows to append. Existing sheets and unrelated workbook content are preserved."
    )
    mapping = None
    if settings.bewerbungsliste_column_mapping:
        try:
            mapping = json.loads(settings.bewerbungsliste_column_mapping)
        except json.JSONDecodeError:
            st.error("The configured Bewerbungsliste column mapping is not valid JSON.")
    st.dataframe(preview_rows(applications, mapping), width="stretch", hide_index=True)
    target = st.text_input("Workbook path", settings.bewerbungsliste_path)
    if st.button("Update workbook"):
        try:
            added, skipped = export_bewerbungsliste(target, applications, mapping=mapping)
            st.success(f"Added {added} row(s); skipped {skipped} duplicate(s).")
        except Exception as exc:
            st.error(str(exc))
    _open_button("Open Bewerbungsliste", target, "open-bewerbungsliste")


def importer(
    repository: ApplicationRepository,
    *,
    embedded: bool = False,
) -> None:
    (st.subheader if embedded else st.header)("Import existing folders")
    st.caption("Import is read-only: existing files and directories are never modified.")
    root = st.text_input("Existing applications root")
    if st.button("Scan"):
        try:
            st.session_state["import_candidates"] = scan_existing(root)
        except Exception as exc:
            st.error(str(exc))
    candidates = st.session_state.get("import_candidates", [])
    if candidates:
        st.dataframe(
            [
                {
                    "Index": index,
                    "Company": item.company,
                    "Position": item.job_title,
                    "Job ID": item.job_id,
                    "Directory": str(item.directory),
                }
                for index, item in enumerate(candidates)
            ],
            width="stretch",
            hide_index=True,
        )
        index = st.number_input(
            "Candidate index", min_value=0, max_value=len(candidates) - 1, step=1
        )
        selected = candidates[int(index)]
        company = st.text_input("Correct company", selected.company)
        job_title = st.text_input("Correct job title", selected.job_title)
        job_id = st.text_input("Correct job ID", selected.job_id)
        language = st.selectbox("Language for imported record", ["DE", "EN"])
        if st.button("Import selected candidate"):
            try:
                corrected = ImportCandidate(
                    company=company,
                    job_title=job_title,
                    job_id=job_id,
                    directory=selected.directory,
                    cv_file=selected.cv_file,
                    cover_letter_file=selected.cover_letter_file,
                )
                app_id = import_candidate(corrected, repository, language=language)
                st.success(f"Imported as record {app_id}; no files were changed.")
            except Exception as exc:
                st.error(str(exc))


def _api_key_settings() -> None:
    key_source = openai_api_key_source()
    if key_source:
        st.success(f"API key available from {key_source}.")
    else:
        st.info("No OpenAI API key is configured.")
    st.caption(
        "The saved key is kept in Windows Credential Manager and is never "
        "written to config.toml or the JAM database."
    )
    with st.form("openai_api_key_settings", clear_on_submit=True):
        api_key = st.text_input(
            "New API key",
            type="password",
            placeholder="Paste the key here",
            autocomplete="off",
        )
        save_key = st.form_submit_button(
            "Save securely", icon=":material/key:", width="stretch"
        )
    if save_key:
        try:
            save_openai_api_key(api_key)
            st.success("API key saved in Windows Credential Manager.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if key_source == "PowerShell environment":
        st.caption(
            "OPENAI_API_KEY from the current environment takes priority. A saved "
            "credential will be used automatically on future JAM launches."
        )
    if stored_openai_api_key_exists() and st.button(
        "Remove saved key",
        icon=":material/delete:",
        type="secondary",
        width="stretch",
    ):
        try:
            delete_openai_api_key()
            st.success("Saved key removed from Windows Credential Manager.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _records(value) -> list[dict]:
    return value.to_dict("records") if hasattr(value, "to_dict") else list(value)


def _avatar_svg(name: str) -> str:
    initial = html.escape((name.strip()[:1] or "?").upper())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160">'
        '<circle cx="80" cy="80" r="80" fill="#314158"/>'
        f'<text x="80" y="101" text-anchor="middle" font-family="Arial" '
        f'font-size="72" font-weight="700" fill="#ffffff">{initial}</text></svg>'
    )


def _profile_image(profile, width: int) -> None:
    photo = Path(profile.photo_path) if profile.photo_path else None
    st.image(
        photo if photo and photo.is_file() else _avatar_svg(profile_display_name(profile)),
        width=width,
    )


def _candidate_photo_editor(
    settings: Settings, profile, profile_path: Path
) -> None:
    st.markdown("#### Profile photo")
    photo_column, upload_column = st.columns([1, 3], vertical_alignment="center")
    with photo_column:
        _profile_image(profile, 140)
    with upload_column:
        photo_upload = st.file_uploader(
            "Choose a profile photo",
            type=("jpg", "jpeg", "png", "webp"),
            key=f"candidate_photo_{profile.profile_id}",
            help="Stored locally. The photo is never included in OpenAI requests.",
        )
        st.caption("JPG, PNG, or WebP · maximum 10 MB")
        if st.button(
            "Save profile photo",
            icon=":material/add_a_photo:",
            disabled=photo_upload is None,
            key=f"save_candidate_photo_{profile.profile_id}",
        ):
            try:
                save_profile_photo(
                    profile,
                    profile_path,
                    settings.candidate_profile_path,
                    photo_upload.getvalue(),
                )
                st.toast("Profile photo saved.", icon=":material/check_circle:")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _candidate_import_panel(settings: Settings, profile_path: Path) -> None:
    st.subheader("Import CV")
    st.caption(
        "JAM reads a DOCX into structured fields and archives an unchanged evidence "
        "copy. Review the preview before accepting it."
    )
    language = st.segmented_control(
        "CV language",
        ("DE", "EN"),
        default=settings.default_application_language,
        required=True,
        key="candidate_import_language",
    )
    configured = {
        "DE": settings.german_cv_master,
        "EN": settings.english_cv_master,
    }
    source_path = st.text_input(
        "DOCX path",
        value=configured.get(language, ""),
        key=f"candidate_import_path_{language}",
    )
    upload = st.file_uploader("Or choose a DOCX", type=("docx",))
    if st.button("Preview CV import", icon=":material/preview:"):
        try:
            if upload is not None:
                preview_dir = profile_path.parent / "candidate_import_preview"
                preview_dir.mkdir(parents=True, exist_ok=True)
                preview_path = preview_dir / Path(upload.name).name
                preview_path.write_bytes(upload.getvalue())
                source_path = str(preview_path)
            parsed = parse_cv_docx(source_path, language)
            st.session_state["candidate_import_preview"] = {
                "source_path": source_path,
                "language": language,
                "summary": bool(parsed.professional_summary),
                "skill_groups": len(parsed.skill_groups),
                "experience": len(parsed.experience),
                "certifications": len(parsed.certifications),
                "unmapped": len(parsed.unmapped_sections),
            }
        except Exception as exc:
            st.error(f"Could not read this CV: {exc}")
    preview = st.session_state.get("candidate_import_preview")
    if preview:
        with st.container(border=True):
            st.markdown(f"**{preview['language']} import preview**")
            columns = st.columns(4)
            columns[0].metric("Summary", "Found" if preview["summary"] else "Missing")
            columns[1].metric("Skill groups", preview["skill_groups"])
            columns[2].metric("Experience entries", preview["experience"])
            columns[3].metric("Certifications", preview["certifications"])
            if preview["unmapped"]:
                st.warning(
                    f"{preview['unmapped']} unrecognized section(s) will be preserved."
                )
            if st.button(
                "Accept and serialize CV",
                type="primary",
                width="stretch",
                icon=":material/archive:",
            ):
                try:
                    import_cv(
                        preview["source_path"],
                        preview["language"],
                        profile_path,
                        legacy_facts_path=settings.candidate_facts_path,
                    )
                    del st.session_state["candidate_import_preview"]
                    st.success("CV imported into Candidate Profile.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def candidate_profile_page(settings: Settings) -> None:
    st.header("Candidate Profile")
    st.caption(
        "Your local, structured professional source of truth. Edit facts here once; "
        "JAM can reuse them for matching and future document generation."
    )
    profile_path = _active_profile_path(settings)
    profile = load_candidate_profile(profile_path)
    if not profile.cv_versions:
        st.info(
            "Start by importing one of your CVs. The configured German and English "
            "masters are prefilled below."
        )
        with st.container(border=True):
            st.markdown(f"#### {profile_display_name(profile)}")
            _candidate_photo_editor(settings, profile, profile_path)
        _candidate_import_panel(settings, profile_path)
        return

    overview, experience_tab, qualifications, import_tab = st.tabs(
        ("Overview", "Experience", "Skills & qualifications", "Import & evidence")
    )
    languages = tuple(sorted(profile.cv_versions))
    selected_language = languages[0]

    with overview:
        _candidate_photo_editor(settings, profile, profile_path)
        selected_language = st.segmented_control(
            "Profile language",
            languages,
            default=("EN" if "EN" in languages else languages[0]),
            required=True,
            key="candidate_overview_language",
        )
        cv = profile.cv_versions[selected_language]
        with st.form("candidate_overview_form"):
            left, right = st.columns(2)
            full_name = left.text_input("Full name", profile.identity.full_name)
            location = left.text_input("Location", profile.identity.location)
            email = right.text_input("Email", profile.identity.email)
            phone = right.text_input("Phone", profile.identity.phone)
            website = right.text_input("Website", profile.identity.website)
            summary = st.text_area(
                f"Professional summary ({selected_language})",
                cv.professional_summary,
                height=180,
            )
            additional = st.text_area(
                "Additional verified facts",
                profile.additional_facts,
                height=220,
                help="Facts not represented in the CV structure, such as work authorization.",
            )
            save_overview = st.form_submit_button("Save profile", type="primary")
        if save_overview:
            profile.identity = CandidateIdentity(
                full_name=full_name,
                location=location,
                email=email,
                phone=phone,
                website=website,
            )
            cv.professional_summary = summary
            profile.additional_facts = additional
            profile.display_name = full_name.strip() or profile.display_name
            save_candidate_profile(profile, profile_path)
            st.success("Candidate Profile saved locally.")

    with experience_tab:
        exp_language = st.segmented_control(
            "Experience language",
            languages,
            default=("EN" if "EN" in languages else languages[0]),
            required=True,
            key="candidate_experience_language",
        )
        cv = profile.cv_versions[exp_language]
        rows = [
            {
                "ID": entry.id,
                "Dates": entry.date_text,
                "Role": entry.role,
                "Company": entry.company,
                "Location": entry.location,
                "Responsibilities": "\n".join(entry.responsibilities),
                "Achievements": "\n".join(entry.achievements),
            }
            for entry in cv.experience
        ]
        with st.form("candidate_experience_form"):
            edited = st.data_editor(
                rows,
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                disabled=("ID",),
                column_config={"ID": None},
            )
            save_experience = st.form_submit_button("Save experience", type="primary")
        if save_experience:
            cv.experience = [
                ExperienceEntry(
                    id=str(row.get("ID") or f"manual-{index}"),
                    date_text=str(row.get("Dates") or ""),
                    role=str(row.get("Role") or ""),
                    company=str(row.get("Company") or ""),
                    location=str(row.get("Location") or ""),
                    responsibilities=[
                        item.strip()
                        for item in str(row.get("Responsibilities") or "").splitlines()
                        if item.strip()
                    ],
                    achievements=[
                        item.strip()
                        for item in str(row.get("Achievements") or "").splitlines()
                        if item.strip()
                    ],
                )
                for index, row in enumerate(_records(edited))
                if str(row.get("Role") or row.get("Company") or "").strip()
            ]
            save_candidate_profile(profile, profile_path)
            st.success("Experience saved.")

    with qualifications:
        qual_language = st.segmented_control(
            "Qualifications language",
            languages,
            default=("EN" if "EN" in languages else languages[0]),
            required=True,
            key="candidate_qualifications_language",
        )
        cv = profile.cv_versions[qual_language]
        skill_rows = [
            {"Group": group.name, "Skill": item}
            for group in cv.skill_groups
            for item in group.items
        ]
        with st.form("candidate_qualifications_form"):
            edited_skills = st.data_editor(
                skill_rows, num_rows="dynamic", hide_index=True, width="stretch"
            )
            education_text = st.text_area(
                "Education — one entry per line",
                "\n".join(item.description for item in cv.education),
            )
            certification_rows = st.data_editor(
                [item.model_dump() for item in cv.certifications],
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
            )
            language_rows = st.data_editor(
                [item.model_dump() for item in cv.languages],
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
            )
            save_qualifications = st.form_submit_button(
                "Save skills & qualifications", type="primary"
            )
        if save_qualifications:
            grouped: dict[str, list[str]] = {}
            for row in _records(edited_skills):
                group = str(row.get("Group") or "").strip()
                skill = str(row.get("Skill") or "").strip()
                if group and skill:
                    grouped.setdefault(group, []).append(skill)
            cv.skill_groups = [
                SkillGroup(name=name, items=items) for name, items in grouped.items()
            ]
            cv.education = [
                EducationEntry(description=line.strip())
                for line in education_text.splitlines()
                if line.strip()
            ]
            cv.certifications = [
                CertificationEntry(
                    name=str(row.get("name") or "").strip(),
                    year=str(row.get("year") or "").strip(),
                )
                for row in _records(certification_rows)
                if str(row.get("name") or "").strip()
            ]
            cv.languages = [
                LanguageSkill(
                    language=str(row.get("language") or "").strip(),
                    proficiency=str(row.get("proficiency") or "").strip(),
                )
                for row in _records(language_rows)
                if str(row.get("language") or "").strip()
            ]
            save_candidate_profile(profile, profile_path)
            st.success("Skills and qualifications saved.")

    with import_tab:
        _candidate_import_panel(settings, profile_path)
        st.subheader("Evidence archive")
        if profile.source_documents:
            st.dataframe(
                [
                    {
                        "Language": source.language,
                        "Original": source.original_path,
                        "Archived copy": source.archived_path,
                        "SHA-256": source.sha256,
                        "Imported": source.imported_at,
                    }
                    for source in profile.source_documents
                ],
                hide_index=True,
                width="stretch",
            )


def ai_assistant_page(
    settings: Settings,
    repository: AgentRunRepository,
    *,
    embedded: bool = False,
) -> None:
    (st.subheader if embedded else st.header)("AI Assistant")
    key_source = openai_api_key_source()
    key_available = bool(key_source)
    key_status, configuration = st.columns([1, 2])
    key_status.metric("API key", "Available" if key_available else "Not available")
    if key_available:
        key_status.caption(key_source)
    with configuration:
        current_mode = next(
            (
                mode
                for mode, profile in AI_MODES.items()
                if profile["model"] == settings.openai_model
                and profile["reasoning_effort"] == settings.openai_reasoning_effort
            ),
            "Standard",
        )
        with st.form("ai_runtime_settings"):
            mode_column, details_column, save_column = st.columns([1, 2, 1])
            selected_mode = mode_column.selectbox(
                "Analysis mode",
                tuple(AI_MODES),
                index=tuple(AI_MODES).index(current_mode),
            )
            selected_profile = AI_MODES[selected_mode]
            details_column.markdown(
                f"**{selected_profile['usage']}**  \n"
                f"{selected_profile['model']} · "
                f"{selected_profile['reasoning_effort']} reasoning"
            )
            save_ai_settings = save_column.form_submit_button(
                "Apply", width="stretch"
            )
        if save_ai_settings:
            save_settings(
                replace(
                    settings,
                    openai_model=selected_profile["model"],
                    openai_reasoning_effort=selected_profile["reasoning_effort"],
                )
            )
            st.success(f"{selected_mode} mode saved.")
            st.rerun()
    sharing_enabled = _ai_data_sharing_enabled(settings)
    with st.container(border=True):
        st.markdown("#### OpenAI data sharing")
        st.write(
            "AI requests may include the job description and metadata, the serialized "
            "Candidate Profile, Agent instructions, and an approved application strategy. "
            "JAM never uploads the source CV or cover-letter DOCX files."
        )
        consent = st.toggle(
            "Allow JAM to send this data to OpenAI",
            value=sharing_enabled,
            key="openai_data_sharing_setting",
        )
        if st.button("Save data-sharing preference", width="stretch"):
            save_settings(
                replace(
                    settings,
                    openai_data_sharing_enabled="true" if consent else "false",
                )
            )
            st.success("OpenAI data-sharing preference saved.")
            st.rerun()
    with st.expander(
        "Manage OpenAI API key",
        icon=":material/key:",
        expanded=not key_available,
    ):
        _api_key_settings()

    st.subheader("Agent context")
    st.caption(
        "Candidate evidence now comes from Candidate Profile. Agent instructions "
        "control matching and writing behavior."
    )
    instructions = read_local_text(settings.agent_instructions_path)
    if not instructions:
        example_path = Path("agent_instructions.example.md")
        instructions = (
            example_path.read_text(encoding="utf-8") if example_path.is_file() else ""
        )
    st.info(
        "Professional facts are edited in Candidate Profile. The legacy facts file "
        "remains preserved and is imported into Additional facts."
    )
    edited_instructions = st.text_area(
        "Agent instructions — matching rules and writing style",
        instructions,
        height=380,
        key="agent_instructions_editor",
    )
    if st.button("Save Agent instructions"):
        try:
            saved = save_local_text(
                settings.agent_instructions_path, edited_instructions
            )
            st.success(f"Saved locally to {saved}")
        except Exception as exc:
            st.error(str(exc))

    st.subheader("Recent agent runs")
    runs = repository.list_recent()
    if not runs:
        st.info("No AI analysis has been run yet.")
    else:
        st.dataframe(
            [
                {
                    "ID": run.id,
                    "Application": run.application_id or "",
                    "Status": run.status,
                    "Model": run.model,
                    "Reasoning": run.reasoning_effort,
                    "Strategy language": run.communication_language,
                    "Input tokens": run.input_tokens,
                    "Output tokens": run.output_tokens,
                    "Created": run.created_at,
                    "Error": run.error_message[:160],
                }
                for run in runs
            ],
            width="stretch",
            hide_index=True,
        )


def _general_settings_page(settings: Settings) -> None:
    st.subheader("Application configuration")
    st.warning("Saving settings restarts the database connection on the next app run.")
    values: dict[str, str] = {}
    with st.form("settings"):
        for field_name in Settings.__dataclass_fields__:
            if field_name in {
                "strategy_language",
                "openai_data_sharing_enabled",
                "active_candidate_profile_id",
            }:
                values[field_name] = str(getattr(settings, field_name))
                continue
            values[field_name] = st.text_input(
                field_name.replace("_", " ").title(), str(getattr(settings, field_name))
            )
        submitted = st.form_submit_button("Save config.toml")
    if submitted:
        try:
            if values["default_application_language"] not in {"DE", "EN"}:
                raise ValueError("Default application language must be DE or EN.")
            save_settings(Settings(**values))
            st.success("Settings saved. Reload the app to apply them.")
        except Exception as exc:
            st.error(str(exc))


def settings_page(
    settings: Settings,
    repository: ApplicationRepository,
    agent_repository: AgentRunRepository,
) -> None:
    st.header("Settings")
    section = st.segmented_control(
        "Settings section",
        ("General", "AI Assistant", "Import"),
        default="General",
        required=True,
        key="settings_section",
        width="stretch",
    )
    if section == "AI Assistant":
        ai_assistant_page(settings, agent_repository, embedded=True)
    elif section == "Import":
        importer(repository, embedded=True)
    else:
        _general_settings_page(settings)


def _save_strategy_language(settings: Settings) -> None:
    selected = str(st.session_state.get("strategy_language_switch", "")).upper()
    if selected in STRATEGY_LANGUAGES and selected != settings.strategy_language:
        save_settings(replace(settings, strategy_language=selected))


def _request_shutdown() -> None:
    st.session_state["_jam_shutdown_requested"] = True


def _render_shutdown_page() -> None:
    st.space(120)
    with st.container(horizontal_alignment="center"):
        st.markdown(":material/power_settings_new:")
        st.title("JAM stopped", text_alignment="center")
        st.write(
            "The local JAM server has been shut down safely.",
            text_alignment="center",
        )
        st.caption("You can close this browser tab.", text_alignment="center")
    if not st.session_state.get("_jam_shutdown_scheduled"):
        st.session_state["_jam_shutdown_scheduled"] = True
        schedule_shutdown()
    st.stop()


def _sidebar_profile_selector(settings: Settings) -> None:
    active_path = _active_profile_path(settings)
    active_profile = load_candidate_profile(active_path)
    profiles = list_candidate_profiles(settings.candidate_profile_path)
    if not profiles and active_path == Path(settings.candidate_profile_path):
        active_profile.profile_id = "default"

    avatar_column, selector_column = st.columns(
        [0.75, 2.25], vertical_alignment="center"
    )
    with avatar_column:
        _profile_image(active_profile, 58)
    with selector_column, st.popover(
        profile_display_name(active_profile),
        icon=":material/arrow_drop_down:",
        type="tertiary",
        width="stretch",
    ):
        st.caption("Candidate profiles")
        for candidate in profiles:
            selected = candidate.profile_id == active_profile.profile_id
            if st.button(
                candidate.display_name,
                icon=(
                    ":material/check:"
                    if selected
                    else ":material/account_circle:"
                ),
                disabled=selected,
                key=f"select_candidate_profile_{candidate.profile_id}",
                width="stretch",
            ):
                save_settings(
                    replace(
                        settings,
                        active_candidate_profile_id=candidate.profile_id,
                    )
                )
                st.rerun()
        with st.form("create_candidate_profile", border=False):
            new_name = st.text_input(
                "New profile name",
                placeholder="Name of the candidate",
            )
            create_profile = st.form_submit_button(
                "Add new profile",
                icon=":material/person_add:",
                width="stretch",
            )
        if create_profile:
            try:
                profile, _ = create_candidate_profile(
                    settings.candidate_profile_path, new_name
                )
                save_settings(
                    replace(
                        settings,
                        active_candidate_profile_id=profile.profile_id,
                    )
                )
                st.session_state["main_navigation"] = "Candidate Profile"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _style_sidebar_navigation() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            padding-top: 1.25rem;
        }

        section[data-testid="stSidebar"] [data-testid="stImage"] img {
            width: 58px !important;
            height: 58px !important;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid rgba(255, 255, 255, 0.22);
        }

        section[data-testid="stSidebar"] [data-testid="stRadio"] > label {
            margin: 1.25rem 0 0.55rem;
            color: rgba(250, 250, 250, 0.62);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        section[data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 0.42rem;
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"] label[data-testid="stRadioOption"] {
            position: relative;
            box-sizing: border-box;
            width: 100%;
            min-height: 2.55rem;
            margin: 0;
            padding: 0.62rem 1.35rem 0.62rem 0.9rem;
            border-left: 3px solid transparent;
            border-radius: 0.35rem;
            background: rgba(255, 255, 255, 0.045);
            clip-path: polygon(
                0 0,
                calc(100% - 0.7rem) 0,
                100% 50%,
                calc(100% - 0.7rem) 100%,
                0 100%
            );
            transition:
                background-color 140ms ease,
                border-color 140ms ease,
                transform 140ms ease;
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"] label[data-testid="stRadioOption"]:hover {
            border-left-color: rgba(255, 75, 75, 0.55);
            background: rgba(255, 255, 255, 0.09);
            transform: translateX(0.16rem);
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"]
        label[data-testid="stRadioOption"][data-selected="true"] {
            border-left-color: #ff4b4b;
            background: linear-gradient(
                90deg,
                rgba(255, 75, 75, 0.3),
                rgba(255, 75, 75, 0.1)
            );
            box-shadow: inset 0 0 0 1px rgba(255, 75, 75, 0.18);
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"]
        label[data-testid="stRadioOption"] > div > div > div:first-child {
            display: none;
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"]
        label[data-testid="stRadioOption"] [data-testid="stMarkdownContainer"] p {
            margin: 0;
            color: rgba(250, 250, 250, 0.82);
            font-size: 0.93rem;
            font-weight: 600;
        }

        section[data-testid="stSidebar"]
        div[role="radiogroup"]
        label[data-testid="stRadioOption"][data-selected="true"]
        [data-testid="stMarkdownContainer"] p {
            color: #ffffff;
            font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run() -> None:
    st.set_page_config(page_title="JAM", page_icon="📁", layout="wide")
    if st.session_state.get("_jam_shutdown_requested"):
        _render_shutdown_page()
        return
    settings, repository, agent_repository, service = _context()
    _style_sidebar_navigation()
    st.sidebar.title("JAM")
    st.sidebar.caption("Job Application Management")
    with st.sidebar:
        _sidebar_profile_selector(settings)
    page = st.sidebar.radio(
        "Navigation",
        (
            "Dashboard",
            "Application Wizard",
            "Application List",
            "Candidate Profile",
            "Settings",
        ),
        key="main_navigation",
    )
    with st.sidebar:
        st.space("stretch")
        st.caption("Strategy language")
        st.segmented_control(
            "Strategy language",
            STRATEGY_LANGUAGES,
            default=(
                settings.strategy_language
                if settings.strategy_language in STRATEGY_LANGUAGES
                else "EN"
            ),
            required=True,
            key="strategy_language_switch",
            label_visibility="collapsed",
            width="stretch",
            persist_state="session",
            on_change=_save_strategy_language,
            args=(settings,),
        )
        st.button(
            "Quit JAM",
            icon=":material/power_settings_new:",
            width="stretch",
            key="quit_jam",
            on_click=_request_shutdown,
        )
    pages = {
        "Dashboard": lambda: dashboard(repository),
        "Application Wizard": lambda: new_application(
            settings, repository, agent_repository, service
        ),
        "Application List": lambda: application_list(
            settings, repository, agent_repository, service
        ),
        "Candidate Profile": lambda: candidate_profile_page(settings),
        "Settings": lambda: settings_page(
            settings, repository, agent_repository
        ),
    }
    pages[page]()
