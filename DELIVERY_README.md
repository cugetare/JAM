# JAM — virgin Windows package

This package contains no candidate profiles, application database, generated
applications, CVs, cover letters, API keys, or other personal data.

## Start

1. Extract the complete ZIP archive to a writable local folder.
2. Double-click `JAM.exe`.
3. Open **Candidate Profile** and import a CV or create a profile manually.
4. Configure document masters and templates under **Settings → General**.
5. Optionally configure an OpenAI API key and data-sharing preference under
   **Settings → AI Assistant**.

Keep `JAM.exe`, `.venv`, `jam`, and `streamlit_app.py` together. The launcher
uses the included private Python runtime and binds the web application only to
`127.0.0.1`.

LibreOffice is the preferred local DOCX-to-PDF converter and must be installed
separately. On Windows, Microsoft Word is used as a fallback. OpenAI features
require an API key and internet connection; local application tracking works
without them.

Runtime logs are written outside the package to `%LOCALAPPDATA%\JAM\jam.log`.
Use **Quit JAM** at the bottom of the sidebar to stop the local server safely.
After the large **JAM stopped** message appears, close the browser tab normally.
