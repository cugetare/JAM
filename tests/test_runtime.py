from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from jam.services.runtime import schedule_shutdown


def test_schedule_shutdown_removes_own_state_and_exits(tmp_path: Path) -> None:
    state_file = tmp_path / "server.json"
    state_file.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    exited = threading.Event()
    exit_codes: list[int] = []

    schedule_shutdown(
        0.01,
        state_file=state_file,
        exit_function=lambda code: (exit_codes.append(code), exited.set()),
    )

    assert exited.wait(timeout=1)
    assert exit_codes == [0]
    assert not state_file.exists()


def test_schedule_shutdown_does_not_remove_another_process_state(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "server.json"
    state_file.write_text(json.dumps({"pid": os.getpid() + 1000}), encoding="utf-8")
    exited = threading.Event()

    schedule_shutdown(
        0.01,
        state_file=state_file,
        exit_function=lambda _code: exited.set(),
    )

    assert exited.wait(timeout=1)
    assert state_file.exists()
