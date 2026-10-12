from __future__ import annotations

import hashlib
import json
from typing import Any

from jam.domain.ai import AgentAnalysis, CoverLetterContent
from jam.security import get_openai_api_key

from .base import (
    BatchPollResult,
    CoverLetterProviderResult,
    ProviderResult,
    QueuedProviderResult,
)

SYSTEM_PROMPT = """You are JAM's application analyst for a senior technical candidate.

Analyze the job description and return only the requested structured result.

Rules:
- Extract metadata from explicit evidence. Use an empty value and low confidence
  when a field cannot be established.
- Evidence must be a short exact fragment from the supplied job description,
  or empty when no evidence exists.
- Never invent candidate experience, metrics, employers, certifications, or skills.
- Base every candidate claim only on Candidate facts.
- Follow Agent instructions for matching and writing style when they do not
  conflict with factuality, safety, output-schema, or approval boundaries.
- Explicitly list gaps, risks, and assumptions.
- Set cover_letter to null. Cover-letter content is generated only in a separate,
  user-requested step after the application is selected.
- Use the requested strategy language for match_summary, strengths,
  transferable_experience, gaps, risks, application_strategy, next_action, and
  assumptions.
- Use the application language for recommended_cv_changes. The strategy
  language never changes the application language.
- Keep metadata values faithful to the job description and evidence as a short
  exact fragment; do not translate proper names or evidence.
- The recommended CV changes are recommendations only. Do not claim that a
  document was edited.
- Do not request external actions or claim that an application was submitted.
- Be concise. Do not repeat the job description or Candidate facts.
- Each internal analysis field should normally contain no more than 150 words.
"""

COVER_LETTER_PROMPT = """You are JAM's cover-letter drafting assistant.

Return only the requested structured cover-letter content.

Rules:
- Base every candidate claim only on Candidate facts.
- Follow Agent instructions when consistent with factuality, safety, the output
  schema, and approval boundaries.
- Use the application language from the supplied context.
- Do not repeat the job description or Candidate facts.
- Each field must be polished prose without labels or placeholders.
- Each paragraph should normally contain 1-3 sentences.
- Keep optional_context empty unless the supplied facts justify it.
- Do not claim that a document was edited, sent, or submitted.
"""


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        reasoning_effort: str,
        max_output_tokens: int = 4000,
        api_key: str = "",
    ):
        resolved_api_key = api_key.strip() or get_openai_api_key()
        if not resolved_api_key:
            raise RuntimeError(
                "No OpenAI API key is available. Save one in JAM Settings or set "
                "OPENAI_API_KEY before starting the application."
            )
        from openai import OpenAI

        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.client = OpenAI(api_key=resolved_api_key, timeout=120.0, max_retries=2)

    @staticmethod
    def _cached_input(
        *,
        system_prompt: str,
        candidate_facts: str,
        agent_instructions: str,
        dynamic_context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str]:
        facts = (
            candidate_facts.strip()
            or "No Candidate facts were supplied. Keep all candidate claims cautious."
        )
        instructions = (
            agent_instructions.strip()
            or "Use the default matching and writing rules."
        )
        stable_material = f"{system_prompt}\n{facts}\n{instructions}"
        cache_key = "jam-" + hashlib.sha256(
            stable_material.encode("utf-8")
        ).hexdigest()[:48]
        return (
            [
                {"role": "developer", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Candidate facts:\n{facts}",
                        },
                        {
                            "type": "input_text",
                            "text": f"Agent instructions:\n{instructions}",
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": json.dumps(dynamic_context, ensure_ascii=False),
                },
            ],
            cache_key,
        )

    @staticmethod
    def _usage(response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        return (
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )

    def _analysis_request(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
    ) -> dict[str, Any]:
        language_names = {
            "EN": "English",
            "DE": "German",
            "RO": "Romanian",
        }
        normalized_strategy_language = strategy_language.upper().strip()
        if normalized_strategy_language not in language_names:
            raise ValueError("Strategy language must be EN, DE, or RO.")
        input_items, cache_key = self._cached_input(
            system_prompt=SYSTEM_PROMPT,
            candidate_facts=candidate_facts,
            agent_instructions=agent_instructions,
            dynamic_context={
                "task": "Analyze this application. Do not draft a cover letter.",
                "language_requirements": {
                    "strategy_discussion": (
                        f"{language_names[normalized_strategy_language]} "
                        f"({normalized_strategy_language})"
                    ),
                    "strategy_fields": [
                        "match_summary",
                        "strengths",
                        "transferable_experience",
                        "gaps",
                        "risks",
                        "application_strategy",
                        "next_action",
                        "assumptions",
                    ],
                    "cv_recommendations": (
                        "Use current_metadata.application_language, or the "
                        "application language determined from the JD."
                    ),
                    "application_language_is_independent": True,
                },
                "current_metadata": current_metadata,
                "job_description": job_description,
            },
        )
        return {
            "model": self.model,
            "reasoning": {"effort": self.reasoning_effort},
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "prompt_cache_key": cache_key,
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
            "input": input_items,
        }

    def analyze(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
    ) -> ProviderResult:
        if not job_description.strip():
            raise ValueError("A job description is required for AI analysis.")
        request = self._analysis_request(
            job_description=job_description,
            candidate_facts=candidate_facts,
            agent_instructions=agent_instructions,
            current_metadata=current_metadata,
            strategy_language=strategy_language,
        )
        response: Any = self.client.responses.parse(
            **request,
            text_format=AgentAnalysis,
        )
        analysis = response.output_parsed
        if analysis is None:
            raise RuntimeError("The model returned no structured analysis.")
        input_tokens, output_tokens = self._usage(response)
        return ProviderResult(
            analysis=analysis,
            response_id=str(getattr(response, "id", "") or ""),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def queue_analysis(
        self,
        *,
        run_id: int,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        current_metadata: dict[str, str],
        strategy_language: str = "EN",
    ) -> QueuedProviderResult:
        if not job_description.strip():
            raise ValueError("A job description is required for AI analysis.")
        from openai.lib._parsing._responses import type_to_text_format_param

        body = self._analysis_request(
            job_description=job_description,
            candidate_facts=candidate_facts,
            agent_instructions=agent_instructions,
            current_metadata=current_metadata,
            strategy_language=strategy_language,
        )
        body["text"] = {"format": type_to_text_format_param(AgentAnalysis)}
        request = {
            "custom_id": f"jam-run-{run_id}",
            "method": "POST",
            "url": "/v1/responses",
            "body": body,
        }
        jsonl = json.dumps(request, ensure_ascii=False) + "\n"
        uploaded = self.client.files.create(
            file=("jam-analysis-batch.jsonl", jsonl.encode("utf-8")),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={"jam_run_id": str(run_id)},
        )
        return QueuedProviderResult(batch_id=str(batch.id))

    @staticmethod
    def _response_output_text(body: dict[str, Any]) -> str:
        for item in body.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    return str(content["text"])
        return ""

    def poll_batch(self, batch_id: str) -> BatchPollResult:
        batch = self.client.batches.retrieve(batch_id)
        status = str(batch.status)
        if status in {"validating", "in_progress", "finalizing", "cancelling"}:
            return BatchPollResult(status=status)
        if status != "completed":
            return BatchPollResult(
                status=status,
                error=f"Batch {batch_id} ended with status {status}.",
            )
        if not batch.output_file_id:
            return BatchPollResult(
                status="failed",
                error=f"Batch {batch_id} completed without an output file.",
            )
        raw_output = self.client.files.content(batch.output_file_id).text
        records = [
            json.loads(line) for line in raw_output.splitlines() if line.strip()
        ]
        if not records:
            return BatchPollResult(
                status="failed",
                error=f"Batch {batch_id} returned an empty output file.",
            )
        record = records[0]
        if record.get("error"):
            return BatchPollResult(
                status="failed",
                error=json.dumps(record["error"], ensure_ascii=False),
            )
        response = record.get("response") or {}
        if int(response.get("status_code", 0)) != 200:
            return BatchPollResult(
                status="failed",
                error=json.dumps(response.get("body") or response, ensure_ascii=False),
            )
        body = response.get("body") or {}
        output_text = self._response_output_text(body)
        if not output_text:
            return BatchPollResult(
                status="failed",
                error=f"Batch {batch_id} returned no structured output text.",
            )
        analysis = AgentAnalysis.model_validate_json(output_text)
        usage = body.get("usage") or {}
        return BatchPollResult(
            status="completed",
            analysis=analysis,
            response_id=str(body.get("id", "") or ""),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )

    def generate_cover_letter(
        self,
        *,
        job_description: str,
        candidate_facts: str,
        agent_instructions: str,
        application_context: dict[str, str],
    ) -> CoverLetterProviderResult:
        if not job_description.strip():
            raise ValueError("A job description is required for cover-letter drafting.")
        input_items, cache_key = self._cached_input(
            system_prompt=COVER_LETTER_PROMPT,
            candidate_facts=candidate_facts,
            agent_instructions=agent_instructions,
            dynamic_context={
                "task": "Draft cover-letter content for this selected application.",
                "application_context": application_context,
                "job_description": job_description,
            },
        )
        response: Any = self.client.responses.parse(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=min(self.max_output_tokens, 2000),
            store=False,
            prompt_cache_key=cache_key,
            prompt_cache_options={"mode": "explicit", "ttl": "30m"},
            input=input_items,
            text_format=CoverLetterContent,
        )
        content = response.output_parsed
        if content is None:
            raise RuntimeError("The model returned no structured cover-letter content.")
        input_tokens, output_tokens = self._usage(response)
        return CoverLetterProviderResult(
            content=content,
            response_id=str(getattr(response, "id", "") or ""),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
