from __future__ import annotations

import re


def infer_language(text: str) -> str:
    de_markers = (" der ", " die ", " und ", " erfahrung", "aufgaben", "anforderungen", "m/w/d")
    en_markers = (" the ", " and ", " experience", "responsibilities", "requirements")
    lowered = f" {text.lower()} "
    de_score = sum(lowered.count(marker) for marker in de_markers)
    en_score = sum(lowered.count(marker) for marker in en_markers)
    return "DE" if de_score >= en_score else "EN"


def extract_metadata(text: str) -> dict[str, str]:
    patterns = {
        "job_id": r"(?im)^\s*(?:job|stellen|reference|referenz)[ -]?(?:id|nr\.?|number)?\s*[:#]\s*(.+?)\s*$",
        "location": r"(?im)^\s*(?:location|standort|ort)\s*:\s*(.+?)\s*$",
        "company": r"(?im)^\s*(?:company|unternehmen|firma)\s*:\s*(.+?)\s*$",
        "job_title": r"(?im)^\s*(?:job title|position|stelle|titel)\s*:\s*(.+?)\s*$",
    }
    result = {"application_language": infer_language(text)}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            result[key] = match.group(1).strip()
    url_match = re.search(r"https?://[^\s<>\"]+", text)
    if url_match:
        result["job_url"] = url_match.group(0).rstrip(".,);]")
    email_match = re.search(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        text,
        flags=re.IGNORECASE,
    )
    if email_match:
        result["contact_email"] = email_match.group(0)
    return result
