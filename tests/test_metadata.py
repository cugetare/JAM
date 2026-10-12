from jam.services.metadata import extract_metadata, infer_language


def test_deterministic_metadata_extraction() -> None:
    text = """Company: Example Robotics
Job Title: Staff Software Engineer
Job ID: ER-12
Location: Hamburg
URL: https://jobs.example.invalid/er-12
Contact: recruiter@example.invalid
Responsibilities: build the platform and mentor engineers.
Requirements: experience with Python.
"""
    result = extract_metadata(text)
    assert result["company"] == "Example Robotics"
    assert result["job_title"] == "Staff Software Engineer"
    assert result["job_id"] == "ER-12"
    assert result["application_language"] == "EN"
    assert result["job_url"] == "https://jobs.example.invalid/er-12"
    assert result["contact_email"] == "recruiter@example.invalid"


def test_language_inference_defaults_to_german_on_tie() -> None:
    assert infer_language("Kurzer neutraler Text") == "DE"
