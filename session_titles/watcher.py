"""Daemon process management and periodic watch loop."""

from __future__ import annotations

import os
import subprocess
import time

from session_titles.config import PID_FILE, STATE_DIR, WATCH_SECONDS
from session_titles.client import HerdrClient
from session_titles.sync import sync_all


def is_watcher_pid_alive(pid: int) -> bool:
    """Verify that the pid is actually alive and running session_titles."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
        cmd = proc.stdout.strip()
        return "session_titles" in cmd
    except Exception:
        return True


def already_watching() -> bool:
    """Check if another watcher process is currently active, cleaning up stale pidfiles."""
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    if is_watcher_pid_alive(pid):
        return True

    # Stale PID file: process is either gone or not session_titles. Clean it up.
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    return False


def stop_watcher() -> bool:
    """Terminate running watcher process if active and clean up PID file."""
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
    except (OSError, ValueError):
        return False
    if is_watcher_pid_alive(pid):
        try:
            os.kill(pid, 15)  # SIGTERM
            time.sleep(0.3)
        except OSError:
            pass
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    return True


def get_watcher_status() -> dict:
    """Return current watcher running state and PID."""
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
        alive = is_watcher_pid_alive(pid)
        return {"running": alive, "pid": pid if alive else None}
    except (OSError, ValueError):
        return {"running": False, "pid": None}


def write_pid() -> None:
    """Record current process ID in the plugin state directory."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def watch(
    sync_tabs: bool = False,
    auto_route: bool | None = None,
    group_similar: bool | None = None,
    cleanup_unused: bool | None = None,
    client: HerdrClient | None = None,
) -> int:
    """Run continuous sync loop until interrupted."""
    if already_watching():
        return 0
    write_pid()
    c = client or HerdrClient()
    try:
        while True:
            sync_all(
                sync_tabs=sync_tabs,
                auto_route=auto_route,
                group_similar=group_similar,
                cleanup_unused=cleanup_unused,
                client=c,
            )
            time.sleep(WATCH_SECONDS)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE, encoding="utf-8") as handle:
                    if handle.read().strip() == str(os.getpid()):
                        os.remove(PID_FILE)
        except OSError:
            pass
    return 0
