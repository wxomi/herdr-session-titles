"""Daemon process management, flock concurrency, and adaptive watch loop."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time

from session_titles.client import HerdrClient
from session_titles.config import (
    IDLE_WATCH_SECONDS,
    LOCK_FILE,
    PID_FILE,
    STATE_DIR,
    WATCH_SECONDS,
)
from session_titles.sync import sync_all


def acquire_watcher_lock() -> object | None:
    """Acquire exclusive non-blocking flock on LOCK_FILE.

    Returns the open file object if acquired, or None if held by another process.
    The OS automatically releases the flock when the process terminates for any reason.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        f = open(LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.seek(0)
            f.truncate()
            f.write(f"{os.getpid()}\n")
            f.flush()
            return f
        except (BlockingIOError, OSError):
            f.close()
            return None
    except OSError:
        return None


def already_watching() -> bool:
    """Check if another watcher process is currently running via non-blocking flock test."""
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        f = open(LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Acquired lock successfully: no watcher is running!
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()
            return False
        except (BlockingIOError, OSError):
            # Lock is held by another active process
            f.close()
            return True
    except OSError:
        return False


def get_watcher_status() -> dict:
    """Return current watcher running state and PID."""
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        f = open(LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()
            return {"running": False, "pid": None}
        except (BlockingIOError, OSError):
            # Lock is held: read PID
            f.seek(0)
            pid_str = f.read().strip()
            f.close()
            try:
                pid = int(pid_str)
            except ValueError:
                pid = None
            return {"running": True, "pid": pid}
    except OSError:
        return {"running": False, "pid": None}


def stop_watcher() -> bool:
    """Terminate running watcher process if active and clean up legacy PID file."""
    status = get_watcher_status()
    if status["running"] and status["pid"]:
        try:
            os.kill(status["pid"], signal.SIGTERM)
            time.sleep(0.3)
        except OSError:
            pass

    # Clean up legacy PID file if present
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
    return True


def watch(
    sync_tabs: bool = False,
    auto_route: bool | None = None,
    group_similar: bool | None = None,
    cleanup_unused: bool | None = None,
    client: HerdrClient | None = None,
) -> int:
    """Run continuous sync loop until interrupted or superseded by new Herdr server."""
    lock = acquire_watcher_lock()
    if lock is None:
        # Another watcher instance is already running
        return 0

    # Clean up legacy PID file
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    c = client or HerdrClient()
    initial_server = c.server_identity()
    consecutive_misses = 0

    try:
        while True:
            # Check Herdr socket lifecycle:
            curr_server = c.server_identity()
            if curr_server is not None:
                consecutive_misses = 0
                if initial_server is None:
                    initial_server = curr_server
                elif curr_server != initial_server:
                    # Socket inode changed: Herdr restarted or successor launched
                    break
            else:
                consecutive_misses += 1
                # If Herdr has been down/closed for > 15s (3-5 iterations), exit cleanly
                if consecutive_misses >= 5:
                    break

            has_active = sync_all(
                sync_tabs=sync_tabs,
                auto_route=auto_route,
                group_similar=group_similar,
                cleanup_unused=cleanup_unused,
                client=c,
            )

            # Adaptive sleeping: 2s when active agents running, 5s when idle
            sleep_duration = WATCH_SECONDS if has_active else IDLE_WATCH_SECONDS
            time.sleep(sleep_duration)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass
    return 0


def start_daemon(
    sync_tabs: bool = False,
    auto_route: bool | None = None,
    group_similar: bool | None = None,
    cleanup_unused: bool | None = None,
) -> int:
    """Launch watcher as a detached background daemon (setsid) without blocking terminal."""
    if already_watching():
        return 0
    cmd = [sys.executable, "-m", "session_titles", "--watch"]
    if sync_tabs:
        cmd.append("--sync-tabs")
    if auto_route is False:
        cmd.append("--no-auto-route")
    if group_similar is False:
        cmd.append("--no-group-similar")
    if cleanup_unused is False:
        cmd.append("--no-cleanup-unused")

    subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    return 0
