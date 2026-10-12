from __future__ import annotations

import pytest

from jam.security import credentials


class CredentialNotFound(Exception):
    winerror = 1168


class FakeCredentialManager:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    def CredWrite(self, value: dict[str, object], flags: int) -> None:
        assert flags == 0
        self.values[str(value["TargetName"])] = value

    def CredRead(self, target: str, credential_type: int, flags: int):
        assert credential_type == self.CRED_TYPE_GENERIC
        assert flags == 0
        try:
            return self.values[target]
        except KeyError as exc:
            raise CredentialNotFound from exc

    def CredDelete(self, target: str, credential_type: int, flags: int) -> None:
        assert credential_type == self.CRED_TYPE_GENERIC
        assert flags == 0
        try:
            del self.values[target]
        except KeyError as exc:
            raise CredentialNotFound from exc


@pytest.fixture
def credential_manager(monkeypatch: pytest.MonkeyPatch) -> FakeCredentialManager:
    manager = FakeCredentialManager()
    monkeypatch.setattr(credentials, "_load_win32cred", lambda: manager)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return manager


def test_saved_key_round_trip_and_delete(
    credential_manager: FakeCredentialManager,
) -> None:
    api_key = "sk-test-abcdefghijklmnopqrstuvwxyz"

    credentials.save_openai_api_key(api_key)

    saved = credential_manager.values[credentials.TARGET_NAME]
    assert saved["CredentialBlob"] == api_key
    assert isinstance(saved["CredentialBlob"], str)
    assert credentials.get_openai_api_key() == api_key
    assert credentials.stored_openai_api_key_exists()
    assert credentials.openai_api_key_source() == "Windows Credential Manager"
    assert credentials.delete_openai_api_key()
    assert not credentials.stored_openai_api_key_exists()
    assert not credentials.delete_openai_api_key()


def test_environment_key_takes_priority(
    credential_manager: FakeCredentialManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials.save_openai_api_key("sk-saved-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-environment-abcdefghijklmnopqrstuvwxyz")

    assert credentials.get_openai_api_key() == "sk-environment-abcdefghijklmnopqrstuvwxyz"
    assert credentials.openai_api_key_source() == "PowerShell environment"


@pytest.mark.parametrize("value", ["", "short", "sk-invalid key with spaces"])
def test_invalid_key_is_rejected(
    value: str, credential_manager: FakeCredentialManager
) -> None:
    with pytest.raises(ValueError):
        credentials.save_openai_api_key(value)
