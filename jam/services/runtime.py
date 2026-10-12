from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path


def runtime_state_file() -> Path:
    base = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    return base / "JAM" / "server.json"


def schedule_shutdown(
    delay_seconds: float = 3.0,
    *,
    state_file: Path | None = None,
    exit_function: Callable[[int], object] = os._exit,
) -> threading.Timer:
    target = state_file or runtime_state_file()

    def stop_server() -> None:
        try:
            try:
                state = json.loads(target.read_text(encoding="utf-8"))
                recorded_pid = int(state.get("pid", -1))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                recorded_pid = -1
            if recorded_pid == os.getpid():
                target.unlink(missing_ok=True)
        finally:
            exit_function(0)

    timer = threading.Timer(delay_seconds, stop_server)
    timer.daemon = True
    timer.start()
    return timer
