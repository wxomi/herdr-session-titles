"""Daemon process management and periodic watch loop."""

from __future__ import annotations

import os
import time

from session_titles.config import PID_FILE, STATE_DIR, WATCH_SECONDS
from session_titles.client import HerdrClient
from session_titles.sync import sync_all


def already_watching() -> bool:
    """Check if another watcher process is currently active."""
    try:
        with open(PID_FILE, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
    except (OSError, ValueError):
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def write_pid() -> None:
    """Record current process ID in the plugin state directory."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def watch(sync_tabs: bool = False, client: HerdrClient | None = None) -> int:
    """Run continuous sync loop until interrupted."""
    if already_watching():
        return 0
    write_pid()
    c = client or HerdrClient()
    try:
        while True:
            sync_all(sync_tabs=sync_tabs, client=c)
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
