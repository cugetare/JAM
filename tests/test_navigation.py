from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from jam.config import load_settings


def _app(tmp_path: Path, monkeypatch) -> AppTest:
    monkeypatch.chdir(tmp_path)
    entrypoint = Path(__file__).parents[1] / "streamlit_app.py"
    return AppTest.from_file(str(entrypoint), default_timeout=15).run()


def test_sidebar_contains_only_primary_destinations(
    tmp_path: Path, monkeypatch
) -> None:
    app = _app(tmp_path, monkeypatch)

    assert app.sidebar.radio[0].options == [
        "Dashboard",
        "Application Wizard",
        "Application List",
        "Candidate Profile",
        "Settings",
    ]
    assert any(button.label == "Quit JAM" for button in app.sidebar.button)
    assert not app.exception


def test_strategy_language_switch_is_persistent_and_independent(
    tmp_path: Path, monkeypatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    language_switch = next(
        item
        for item in app.sidebar.segmented_control
        if item.label == "Strategy language"
    )

    assert language_switch.options == ["EN", "DE", "RO"]
    language_switch.set_value("RO").run()

    assert load_settings(tmp_path / "config.toml").strategy_language == "RO"
    assert load_settings(tmp_path / "config.toml").default_application_language == "DE"
    assert not app.exception


def test_secondary_tools_are_nested_in_primary_pages(
    tmp_path: Path, monkeypatch
) -> None:
    app = _app(tmp_path, monkeypatch)

    app.sidebar.radio[0].set_value("Settings").run()
    settings_section = next(
        item for item in app.segmented_control if item.label == "Settings section"
    )
    assert settings_section.options == ["General", "AI Assistant", "Import"]

    settings_section.set_value("AI Assistant").run()
    assert any(item.value == "AI Assistant" for item in app.subheader)
    assert not app.exception

    next(
        item for item in app.segmented_control if item.label == "Settings section"
    ).set_value("Import").run()
    assert any(item.value == "Import existing folders" for item in app.subheader)
    assert not app.exception

    app.sidebar.radio[0].set_value("Application List").run()
    list_view = next(
        item for item in app.segmented_control if item.label == "List view"
    )
    assert list_view.options == ["Applications", "Bewerbungsliste"]
    list_view.set_value("Bewerbungsliste").run()
    assert any(item.value == "Bewerbungsliste" for item in app.subheader)
    assert not app.exception
