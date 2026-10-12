from __future__ import annotations

import os
import sys
from types import ModuleType

TARGET_NAME = "JAM/OpenAI API Key"
CREDENTIAL_USERNAME = "OPENAI_API_KEY"


def _load_win32cred() -> ModuleType:
    if sys.platform != "win32":
        raise RuntimeError("Windows Credential Manager is available only on Windows.")
    import win32cred

    return win32cred


def _validate_key(api_key: str) -> str:
    value = api_key.strip()
    if len(value) < 20 or any(character.isspace() for character in value):
        raise ValueError("Enter a complete OpenAI API key without spaces.")
    return value


def save_openai_api_key(api_key: str) -> None:
    value = _validate_key(api_key)
    win32cred = _load_win32cred()
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": TARGET_NAME,
            "UserName": CREDENTIAL_USERNAME,
            "CredentialBlob": value,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "OpenAI API key stored locally for JAM",
        },
        0,
    )


def _stored_openai_api_key() -> str:
    win32cred = _load_win32cred()
    try:
        credential = win32cred.CredRead(
            TARGET_NAME, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception as exc:
        if getattr(exc, "winerror", None) == 1168:
            return ""
        raise RuntimeError(f"Windows Credential Manager could not be read: {exc}") from exc
    blob = credential.get("CredentialBlob", b"")
    if isinstance(blob, str):
        return blob.strip()
    if isinstance(blob, bytes):
        try:
            return blob.decode("utf-16-le").rstrip("\x00").strip()
        except UnicodeDecodeError:
            return blob.decode("utf-8").strip()
    return ""


def stored_openai_api_key_exists() -> bool:
    return bool(_stored_openai_api_key())


def get_openai_api_key() -> str:
    environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
    return environment_key or _stored_openai_api_key()


def openai_api_key_source() -> str:
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "PowerShell environment"
    if stored_openai_api_key_exists():
        return "Windows Credential Manager"
    return ""


def delete_openai_api_key() -> bool:
    win32cred = _load_win32cred()
    try:
        win32cred.CredDelete(TARGET_NAME, win32cred.CRED_TYPE_GENERIC, 0)
        return True
    except Exception as exc:
        if getattr(exc, "winerror", None) == 1168:
            return False
        raise RuntimeError(f"Windows Credential Manager could not delete the key: {exc}") from exc
