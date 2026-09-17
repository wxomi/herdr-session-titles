"""Management, tracking, and automatic cleanup of unused terminal tabs."""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import TYPE_CHECKING

from session_titles.config import (
    STATE_DIR,
    UNUSED_TAB_TTL_SECONDS,
    UNUSED_TABS_FILE,
)

if TYPE_CHECKING:
    from session_titles.client import HerdrClient

SHELL_NAMES = frozenset(
    {"zsh", "bash", "sh", "fish", "-zsh", "-bash", "-sh", "-fish"}
)


def get_shell_start_time(pid: int) -> float | None:
    """Retrieve process start time via ps as a Unix timestamp."""
    if not pid or pid <= 1:
        return None
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            check=False,
        )
        out = proc.stdout.strip()
        if out:
            # Format: 'Tue Sep 15 21:34:49 2026'
            return time.mktime(time.strptime(out))
    except Exception:
        pass
    return None


def is_pane_idle_terminal(
    pane: dict,
    agents_by_pane: dict[str, dict],
    client: HerdrClient,
) -> bool:
    """Check if a pane is an idle shell with no agent and no active foreground command."""
    pid = pane.get("pane_id")
    if not pid:
        return True
    if pid in agents_by_pane:
        return False

    agent_field = pane.get("agent")
    if agent_field and str(agent_field).lower() not in ("none", "unknown", ""):
        return False

    if not client.is_available():
        return False

    info = client.process_info(pid)
    if not info:
        return False

    fg = info.get("foreground_processes", [])
    shell_pid = info.get("shell_pid")

    # If foreground_processes is empty, shell is idle
    if not fg:
        return True

    # If any non-shell process is in foreground, it is an active command
    for proc in fg:
        proc_pid = proc.get("pid")
        proc_name = (proc.get("name") or "").lower()
        if proc_pid != shell_pid and proc_name not in SHELL_NAMES:
            return False

    return True


def is_tab_idle_terminal(
    tab_id: str,
    tab_panes: list[dict],
    agents_by_pane: dict[str, dict],
    client: HerdrClient,
) -> bool:
    """Check if all panes in a tab are idle terminal shells."""
    if not tab_panes:
        return False
    return all(
        is_pane_idle_terminal(p, agents_by_pane, client) for p in tab_panes
    )


def load_unused_tabs_state() -> dict[str, dict]:
    """Read tracked unused tab state from JSON file."""
    if not os.path.exists(UNUSED_TABS_FILE):
        return {}
    try:
        with open(UNUSED_TABS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_unused_tabs_state(state: dict[str, dict]) -> None:
    """Save tracked unused tab state to JSON file."""
    os.makedirs(STATE_DIR, exist_ok=True)
    temp_path = f"{UNUSED_TABS_FILE}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_path, UNUSED_TABS_FILE)
    except OSError:
        pass


def cleanup_unused_tabs(
    client: HerdrClient,
    snap: dict | None = None,
    ttl_seconds: float | None = None,
) -> list[str]:
    """Track idle terminal tabs and close any that have exceeded the TTL."""
    if not client.is_available():
        return []

    snapshot = snap if snap is not None else client.snapshot()
    if not snapshot:
        return []

    ttl = ttl_seconds if ttl_seconds is not None else UNUSED_TAB_TTL_SECONDS
    now = time.time()
    tabs = [t for t in snapshot.get("tabs", []) if isinstance(t, dict)]
    panes = [p for p in snapshot.get("panes", []) if isinstance(p, dict)]
    agents = snapshot.get("agents", [])
    focused_tab_id = snapshot.get("focused_tab_id")

    agents_by_pane = {
        a["pane_id"]: a for a in agents if isinstance(a, dict) and "pane_id" in a
    }

    tab_panes: dict[str, list[dict]] = {}
    for p in panes:
        tid = p.get("tab_id")
        if tid:
            tab_panes.setdefault(tid, []).append(p)

    tabs_by_workspace: dict[str, list[dict]] = {}
    for t in tabs:
        ws_id = t.get("workspace_id")
        if ws_id:
            tabs_by_workspace.setdefault(ws_id, []).append(t)

    state = load_unused_tabs_state()
    current_tab_ids = {t.get("tab_id") for t in tabs if t.get("tab_id")}

    # Remove stale tabs from state that no longer exist
    for tid in list(state.keys()):
        if tid not in current_tab_ids:
            state.pop(tid, None)

    # Inspect all existing tabs
    for t in tabs:
        tid = t.get("tab_id")
        if not tid:
            continue
        panes_in_tab = tab_panes.get(tid, [])
        is_idle = is_tab_idle_terminal(tid, panes_in_tab, agents_by_pane, client)

        if is_idle:
            if tid not in state:
                # Find oldest shell start time among panes in this tab
                start_times: list[float] = []
                for p in panes_in_tab:
                    pid = p.get("pane_id")
                    info = client.process_info(pid)
                    spid = info.get("shell_pid")
                    if spid:
                        st = get_shell_start_time(spid)
                        if st and st <= now:
                            start_times.append(st)
                first_idle = min(start_times) if start_times else now
                state[tid] = {
                    "first_idle_at": first_idle,
                    "workspace_id": t.get("workspace_id"),
                }
        else:
            # Active tab: reset tracking
            state.pop(tid, None)

    # Auto-delete eligible unused tabs
    closed_tab_ids: list[str] = []
    for tid, info in list(state.items()):
        first_idle = info.get("first_idle_at", now)
        ws_id = info.get("workspace_id")
        if now - first_idle < ttl:
            continue

        # SAFETY GUARD 1: Do not close the focused tab
        if tid == focused_tab_id:
            continue

        # SAFETY GUARD 2: Never close the only remaining tab in a workspace
        ws_tabs = tabs_by_workspace.get(ws_id, [])
        remaining_count = len([t for t in ws_tabs if t.get("tab_id") not in closed_tab_ids])
        if remaining_count <= 1:
            continue

        # SAFETY GUARD 3: Re-verify that tab is still idle
        panes_in_tab = tab_panes.get(tid, [])
        if not is_tab_idle_terminal(tid, panes_in_tab, agents_by_pane, client):
            state.pop(tid, None)
            continue

        if client.close_tab(tid):
            closed_tab_ids.append(tid)
            state.pop(tid, None)

    save_unused_tabs_state(state)
    return closed_tab_ids
