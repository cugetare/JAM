# Changelog

All notable changes to JAM are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Project overview, quick start, provenance and license in the README
- Release notes under `docs/releases/`

### Changed
- `.gitignore` now excludes personal config, local data and build/delivery output

## [0.1.0] — 2026-07-28

First working release. See [release notes](docs/releases/v0.1.0.md).

### Added
- Application Wizard: JD → AI analysis → CV recommendations → cover letter → PDF package → applied
- Optional OpenAI analyst with structured output, preview/diff, explicit acceptance and audited runs
- Quick / Standard / Deep analysis modes and a Batch API queue
- Candidate Profile with DOCX import, SHA-256 evidence and multiple local profiles
- Versioned, copy-only CV and cover-letter working documents
- Token-based cover-letter generation (DE/EN templates)
- Auditable PDF finalization via LibreOffice, with a Word fallback
- Bewerbungsliste XLSX preview/update with duplicate prevention
- Dashboard, application list, status history, follow-ups, CSV and AI-brief export
- Read-only import of existing application folders
- EN | DE | RO strategy language
- Windows launcher (`JAM.exe`) and virgin Windows x64 package

[Unreleased]: https://github.com/cugetare/JAM/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cugetare/JAM/releases/tag/v0.1.0
