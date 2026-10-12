# JAM — Job Application Manager

**Local-first Windows app for managing job applications end to end** — from a
pasted job description to an auditable, submission-ready PDF package.

JAM organizes job descriptions, working documents, submissions,
communications, follow-ups, and the German `Bewerbungsliste`. It uses
Streamlit for the UI, SQLite for structured data, and ordinary folders for
documents. An optional OpenAI analyst scores the match, proposes an
application strategy, and drafts CV recommendations and cover-letter content.
Every AI suggestion is previewed and must be explicitly accepted.

JAM **does not rewrite arbitrary DOCX content**. It creates safe working copies,
stores structured CV recommendations, and replaces only explicit `{{TOKEN}}`
fields in the supplied cover-letter templates. Master and submitted documents
are treated as immutable.

| | |
| --- | --- |
| **Status** | Working MVP, in personal use since July 2026 |
| **Author** | Dan Glogoveanu |
| **Stack** | Python 3.12 · Streamlit · SQLite · python-docx · openpyxl · OpenAI API |
| **Platform** | Windows (local, binds to `127.0.0.1` only) |

## Quick start

```powershell
git clone https://github.com/cugetare/JAM.git
cd JAM
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item config.example.toml config.toml   # then edit the paths
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

A packaged Windows build (no Python required) is published under
**Releases**, not in the repository.

## What works

- Create an application from a pasted job description
- Deterministic metadata and language suggestions (no API required)
- Optional OpenAI application analyst with validated structured output
- AI preview/diff and explicit acceptance before database changes
- Audited agent runs with model, status, token usage, and errors
- Validated application records with all requested matching/recommendation
  fields
- Configurable application root and master document paths
- Standard Windows-safe folder structure
- Copy-only, versioned CV and cover-letter working documents
- Exact pasted JD stored in SQLite and `00_JD/JD_original.txt`
- Missing/corrected JD restoration from an application selected in Application
  List, with a versioned backup before replacing non-empty JD content
- Duplicate detection by company/job ID and directory
- Dashboard, searchable application list, details editing, follow-ups, and
  status history
- CSV export
- Bewerbungsliste view inside Application List, with XLSX preview/update and
  duplicate prevention
- Existing-folder scan, preview, correction, and read-only import
- Markdown AI Brief export
- Deterministic cover-letter generation from explicit template tokens
- Version-aware finalization of the latest CV and cover-letter DOCX files into
  an auditable PDF package for manual upload
- Platform-safe file/folder opening helpers
- Versioned database initialization and filesystem operation log

## Install

Python 3.12 or newer is required. In PowerShell:

```powershell
cd D:\Projects\JAM
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Initial configuration

Copy the example and edit the paths:

```powershell
Copy-Item config.example.toml config.toml
notepad config.toml
```

All paths are configurable. No personal path is hardcoded in the application.
Relative paths are resolved from the directory containing `config.toml`.
Leaving a master document path empty simply skips that copy.

### Optional AI assistant

Open **Settings**, paste the OpenAI API key, and select **Save securely**. JAM
stores it in Windows Credential Manager for the current Windows user. It is
never written to `config.toml` or SQLite.

For a temporary override, set the key in the PowerShell process that starts
JAM:

```powershell
$env:OPENAI_API_KEY="your-key"
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

An environment key takes priority over the saved credential. Under
**Settings → AI Assistant**, choose an analysis mode:

| Mode | Model | Reasoning | Use |
| --- | --- | --- | --- |
| Quick | Luna | low | Initial screening |
| Standard | Terra | low | Most applications |
| Deep | Terra | medium | Important or difficult applications |

The selected mode persists its underlying model and reasoning settings in
`config.toml`. Each historical run retains the settings it actually used.

Use **Candidate Profile** to maintain structured, verified experience,
competencies, education, certifications, languages, and additional facts.
DOCX import previews the extracted structure, archives an unchanged evidence
copy with its SHA-256 hash, and never overwrites the source. Each save creates
a versioned JSON backup.

The profile control at the top of the sidebar shows the active candidate's
photo and name. Its dropdown switches between locally configured profiles or
creates a new one. Each profile has independent CV data, evidence, additional
facts, and a local JPG/PNG/WebP photo; the active profile is persisted and is
the one used for AI analysis.

Use **Settings → AI Assistant** for Agent instructions, the API key, analysis
mode, and one persistent OpenAI data-sharing preference. When enabled, JAM may
send the selected JD and metadata, serialized Candidate Profile, Agent
instructions, and approved strategy. It does not upload DOCX files.

JAM keeps the reusable system prompt, serialized Candidate Profile, and Agent instructions
in a stable prefix and places an explicit prompt-cache breakpoint immediately
after them. Analysis output is strict structured JSON and is capped at 4,000
output tokens. The initial analysis produces matching, strengths, gaps, risks,
strategy, and CV recommendations; it deliberately leaves cover-letter content
empty.

For a saved application, **Generate cover-letter content** is a separate,
explicit action with its own preview and acceptance step. **Queue low-cost
analysis** submits a Luna/low request through the OpenAI Batch API. Use
**Check queued analysis** later to retrieve the result; JAM still requires
review and acceptance before changing application fields.

`bewerbungsliste_column_mapping` may contain a one-line JSON object mapping
workbook headings to application fields, for example:

```toml
bewerbungsliste_column_mapping = "{\"Firma\":\"company\",\"Rolle\":\"job_title\",\"Status\":\"status\"}"
```

The Settings screen can also create or update `config.toml`.

## Navigation

The sidebar contains only the primary destinations:

- **Dashboard**
- **Application Wizard**
- **Application List**
- **Candidate Profile**
- **Settings**

The **EN | DE | RO** selector at the bottom of the sidebar controls the
strategy-discussion language. It applies to the match explanation, strengths,
transferable experience, gaps, risks, strategy, assumptions, and next action.
It does not change the application language. CV recommendations and the cover
letter continue to use the application language.

Select a row in Application List to open the full application record; use
**Back to application list** to return. Bewerbungsliste is the secondary view
on the same page. AI Assistant and read-only folder Import are sections under
Settings.

## Run

Double-click `JAM.exe` in the project folder. It starts JAM without a PowerShell
window and opens the local application in the default browser. A second
double-click reopens the running instance instead of starting another one.
The launcher binds Streamlit only to `127.0.0.1`; its diagnostic log is stored
in `%LOCALAPPDATA%\JAM\jam.log`.

Use **Quit JAM** at the bottom of the sidebar to stop the local server. JAM
shows a final **JAM stopped** page, removes the launcher's active-server state,
and then shuts down. The browser tab remains open so the final message is not
lost and can be closed normally.

The equivalent developer command is:

```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

The core application remains local and works without a cloud account. AI
analysis is optional and requires an OpenAI API key.

## Guided application workflow

**Application Wizard** is the primary workflow:

1. Paste the complete JD and run the AI analysis.
2. Review the match score, assessment, extracted job details, and proposed
   strategy. Edit the strategy before continuing.
3. JAM saves the JD and analysis as soon as you choose to continue, then shows
   structured CV recommendations. The copied CV remains user-edited.
4. Generate and edit cover-letter content using the approved strategy, then
   create a new template-based DOCX version.
5. Review the working documents and finalize them into an auditable PDF
   package.
6. After manual upload, explicitly mark the application as applied.

The wizard can resume non-terminal applications from persisted database state.
Status changes through Reviewing, Preparing, Ready to Apply, and Applied are
timestamped in status history. The original all-fields form remains available
behind **Show advanced application form**.

To rebuild the Windows launcher:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
```

## Application directory structure

With a job ID:

```text
Applications/
└── Company_Name/
    └── JobID_Job_Title/
        ├── 00_JD/
        │   ├── JD_original.txt
        │   └── JD_metadata.json
        ├── 01_Application/
        │   ├── CV/
        │   └── Cover_Letter/
        ├── 02_Submission/
        │   ├── application_data.json
        │   └── confirmation/
        ├── 03_Communication/
        └── 04_Interview/
```

Without a job ID, the leaf name is
`YYYY-MM_Job_Title_Location`. Invalid Windows filename characters and reserved
device names are sanitized.

PDF finalization prefers a local LibreOffice installation and uses an isolated
headless profile for each conversion. On Windows, Microsoft Word remains a
fallback if LibreOffice is unavailable or cannot convert a document. Save and
close the selected DOCX files before finalizing. JAM treats the sources as
read-only and validates that each output is a readable PDF with at least one
page. The finalization manifest records which converter produced each PDF.

Working files use `_v01`, `_v02`, and so on. Creating a new version copies the
current working file; it does not modify the previous one. A filename containing
`_submitted` is rejected as a version source.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests cover directory naming, duplicate prevention, safe master copying,
application creation, status history, Excel preservation/deduplication,
metadata extraction, document versioning, and read-only folder import.

## Data and backup

The SQLite database and applications directory together form the complete
record. Back up both while JAM is closed:

- `data/jam.sqlite3` (or the configured database)
- the configured `applications_root`
- the configured Bewerbungsliste workbook
- `config.toml`

Use File History, an encrypted external drive, or another versioned local backup.
Do not rely on the database alone: documents live in the filesystem.

## Safety behavior

- Existing application directories are never silently reused.
- Copy operations use exclusive destinations and never overwrite.
- Master files are read-only sources.
- Submitted files are not regenerated.
- Import records paths without changing existing content.
- Failed multi-file creation leaves the partial directory in place for audit
  and recovery rather than silently deleting it.
- There is no permanent-delete feature in this MVP.
- AI suggestions are previewed and never applied automatically.
- AI analysis never generates, overwrites, or submits a document.
- Agent inputs are represented by a SHA-256 audit hash; structured results and
  usage are stored locally in `agent_runs`.
- Finalization never modifies source DOCX files. Each run creates a new
  timestamped package with both PDFs and a manifest containing source/output
  paths, sizes, timestamps, page counts, and SHA-256 hashes.
- Moving an application into `Applied` or a later submitted status fills
  `application_date` from the transition date only when that field is empty.

## Cover-letter template fields

The included German and English masters support:

```text
{{COMPANY_NAME}}
{{CONTACT_LINE}}
{{COMPANY_ADDRESS_LINE_1}}
{{COMPANY_ADDRESS_LINE_2}}
{{DATE}}
{{SUBJECT_LINE}}
{{SALUTATION}}
{{MOTIVATION_PARAGRAPH}}
{{RELEVANT_EXPERIENCE_PARAGRAPH}}
{{VALUE_PROPOSITION_PARAGRAPH}}
{{OPTIONAL_CONTEXT_PARAGRAPH}}
{{CLOSING_PARAGRAPH}}
```

Generation always creates a new version and removes blank optional paragraphs.
Unknown or unresolved tokens stop generation with an error.

## Known limitations

- Only explicit cover-letter tokens are replaced; arbitrary DOCX editing and
  CV rewriting remain intentionally unsupported.
- PDF generation requires LibreOffice or, on Windows, Microsoft Word.
- Metadata extraction is intentionally conservative and expects labelled fields
  where possible; the optional AI analyst handles less structured JDs.
- Workbook formatting is preserved for existing cells and unrelated sheets, but
  new rows do not clone every custom row style.
- Import inference cannot understand every legacy naming convention; candidates
  should be reviewed and corrected before import.
- File-opening buttons launch a local OS handler and therefore require the
  Streamlit process to run on the Windows desktop.
- Schema migrations are explicit and preserve existing application and status
  history. Back up the database before each application upgrade.

## Roadmap

1. Build a representative JD evaluation set and measure extraction accuracy.
2. Add selective field acceptance instead of only accepting the complete AI result.
3. Add visual comparison for generated template versions.
4. Add opt-in CV text extraction and matching with an explicit send preview.
5. Add opt-in email/calendar connectors and automatic follow-up reminders.

## Fictional sample

[`examples/fictional_application.json`](examples/fictional_application.json)
contains placeholder-only sample data. Importing it is not automatic, so JAM
will not create sample records in a real database without an explicit user
action.


## Provenance

JAM was designed and built by Dan Glogoveanu as a personal project in
July 2026 (first working build and Windows package: 24–28 July 2026). The
repository was published to GitHub on 12 October 2026; development history
before that date was kept locally.

JAM is the conceptual basis for **CareerPilot**, a product developed by
Group 5 of the Ironhack AI Product Management bootcamp (October 2026), where
it was presented to the team as prior work.

## License

Copyright © 2026 Dan Glogoveanu. All rights reserved.

This source code is shared for reference only. No license is granted to use,
copy, modify, or distribute it without written permission from the author.
