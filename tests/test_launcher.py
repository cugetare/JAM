from __future__ import annotations

import json
from pathlib import Path

import jam_launcher


def test_find_project_root_accepts_project_and_dist(tmp_path: Path) -> None:
    project = tmp_path / "JAM"
    (project / ".venv" / "Scripts").mkdir(parents=True)
    (project / ".venv" / "Scripts" / "pythonw.exe").touch()
    (project / "streamlit_app.py").touch()

    assert jam_launcher.find_project_root(project) == project
    assert jam_launcher.find_project_root(project / "dist") == project


def test_read_running_port_requires_healthy_streamlit(
    tmp_path: Path, monkeypatch
) -> None:
    state = tmp_path / "server.json"
    state.write_text(json.dumps({"port": 8503}), encoding="utf-8")
    monkeypatch.setattr(jam_launcher, "is_streamlit_ready", lambda port: port == 8503)

    assert jam_launcher.read_running_port(state) == 8503

    monkeypatch.setattr(jam_launcher, "is_streamlit_ready", lambda port: False)
    assert jam_launcher.read_running_port(state) is None
