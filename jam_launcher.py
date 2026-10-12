from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "JAM"
PORT_RANGE = range(8501, 8511)


def find_project_root(start: Path | None = None) -> Path:
    executable_directory = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    initial = (start or executable_directory).resolve()
    candidates = (initial, initial.parent)
    for candidate in candidates:
        if (
            (candidate / "streamlit_app.py").is_file()
            and (candidate / ".venv" / "Scripts" / "pythonw.exe").is_file()
        ):
            return candidate
    raise FileNotFoundError(
        "JAM.exe must remain in the JAM project folder (or its dist folder), "
        "next to streamlit_app.py and the .venv directory."
    )


def runtime_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    directory = base / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def is_streamlit_ready(port: int, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout
        ) as response:
            return response.status == 200 and response.read().strip() == b"ok"
    except (OSError, urllib.error.URLError):
        return False


def available_port() -> int:
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port is available between 8501 and 8510.")


def read_running_port(state_file: Path) -> int | None:
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        port = int(state["port"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return port if is_streamlit_ready(port) else None


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, "JAM could not start", 0x10)


def readiness_check(project_root: Path) -> None:
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    result = subprocess.run(
        [str(pythonw), "-c", "import streamlit, jam"],
        cwd=project_root,
        check=False,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("The JAM Python environment is incomplete.")


def launch(project_root: Path) -> str:
    runtime = runtime_directory()
    state_file = runtime / "server.json"
    if running_port := read_running_port(state_file):
        url = f"http://127.0.0.1:{running_port}"
        webbrowser.open(url)
        return url

    port = available_port()
    url = f"http://127.0.0.1:{port}"
    log_path = runtime / "jam.log"
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    command = [
        str(pythonw),
        "-m",
        "streamlit",
        "run",
        str(project_root / "streamlit_app.py"),
        f"--server.port={port}",
        "--server.address=127.0.0.1",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            close_fds=True,
        )
    state_file.write_text(
        json.dumps(
            {
                "pid": process.pid,
                "port": port,
                "project_root": str(project_root),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    for _ in range(60):
        if is_streamlit_ready(port):
            webbrowser.open(url)
            return url
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError(
        f"JAM did not become ready. Details are available in {log_path}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local JAM application.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the installation without starting the application.",
    )
    arguments = parser.parse_args()
    try:
        project_root = find_project_root()
        if arguments.check:
            readiness_check(project_root)
        else:
            launch(project_root)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        if arguments.check:
            print(str(exc), file=sys.stderr)
        else:
            show_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
