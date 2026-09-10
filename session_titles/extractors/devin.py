"""Session title extractor for Devin CLI sessions."""

from __future__ import annotations

import os
import re
import sqlite3
from typing import TYPE_CHECKING

from session_titles.config import (
    DEVIN_DB,
    DEVIN_RENAMED,
    DEVIN_RESUME_ID,
    DEVIN_SESSION_RESET,
    DEVIN_TAB_PREFIX,
    LOCK_DIR,
    SKIP_PROMPT,
)
from session_titles.client import read_output, run_herdr_cli
from session_titles.extractors.base import BaseExtractor
from session_titles.sanitize import (
    agent_cwd,
    first_user_prompt_title,
    sanitize,
    user_prompts,
)

if TYPE_CHECKING:
    from session_titles.client import HerdrClient


def connect_devin() -> sqlite3.Connection | None:
    """Connect to Devin's local SQLite database in read-only mode."""
    if not os.path.exists(DEVIN_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{DEVIN_DB}?mode=ro", uri=True, timeout=0.4)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def pane_process_ids(pane_id: str, client: HerdrClient) -> set[int]:
    """Resolve process IDs associated with a pane."""
    info = {}
    if client.is_available():
        info = client.process_info(pane_id)
    if not info:
        payload = run_herdr_cli("pane", "process-info", "--pane", pane_id)
        info = (payload.get("result") or {}).get("process_info") or {}
    ids: set[int] = set()
    for key in ("foreground_process_group_id", "shell_pid"):
        value = info.get(key)
        if isinstance(value, int):
            ids.add(value)
    for proc in info.get("foreground_processes") or []:
        pid = proc.get("pid")
        if isinstance(pid, int):
            ids.add(pid)
    return ids


def title_from_session_id(session_id: str) -> str | None:
    """Look up session title in Devin's SQLite sessions table."""
    con = connect_devin()
    if con is None:
        return None
    try:
        row = con.execute(
            "SELECT title FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row:
            return sanitize(row["title"])
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None


def pick_newest_lock_session(pids: set[int], lock_dir: str = LOCK_DIR) -> str | None:
    """Return the session id whose lock matches pids and has the newest mtime.

    Devin leaves stale lock files behind when a process forks or switches
    sessions, so several locks can share one PID. The current session is
    the most recently written lock.
    """
    if not pids or not os.path.isdir(lock_dir):
        return None
    newest: tuple[float, str] | None = None
    try:
        for name in os.listdir(lock_dir):
            if not name.endswith(".lock"):
                continue
            path = os.path.join(lock_dir, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    raw = handle.read().strip()
                lock_pid = int(raw.split()[0])
                mtime = os.path.getmtime(path)
            except (OSError, ValueError, IndexError):
                continue
            if lock_pid not in pids:
                continue
            if newest is None or mtime >= newest[0]:
                newest = (mtime, name[: -len(".lock")])
    except OSError:
        return None
    return newest[1] if newest else None


def output_after_session_reset(output: str) -> str:
    """Strip scrollback prior to the most recent /clear or session reset."""
    parts = DEVIN_SESSION_RESET.split(output)
    return parts[-1] if parts else output


def extract_devin_rename(output: str) -> str | None:
    """Detect explicit /rename-session confirmations in terminal output."""
    matches = DEVIN_RENAMED.findall(output_after_session_reset(output))
    return sanitize(matches[-1].strip()) if matches else None


def resolve_devin_live_title(
    session_id: str | None,
    db_title: str | None,
    renamed: str | None,
) -> str | None:
    """Title for the process's current session; never leftover scrollback."""
    if session_id:
        return db_title or renamed or "New session"
    return renamed


def devin_resume_id(agent: dict) -> str | None:
    """Extract session ID from commandline flags like -r <session_id>."""
    for field in ("terminal_title_stripped", "terminal_title"):
        value = agent.get(field)
        if not isinstance(value, str):
            continue
        match = DEVIN_RESUME_ID.search(value)
        if match:
            return match.group(1)
    return None


def devin_tab_title(tab_label: str | None) -> str | None:
    """Extract title from tab label if prefixed with devin - ..."""
    if not tab_label:
        return None
    if DEVIN_TAB_PREFIX.match(tab_label):
        return sanitize(DEVIN_TAB_PREFIX.sub("", tab_label))
    return None


def devin_title_from_db(output: str, cwd: str | None) -> str | None:
    """Match recent terminal prompts to Devin's prompt_history table."""
    prompts = user_prompts(output)
    if not prompts:
        return None
    con = connect_devin()
    if con is None:
        return None
    try:
        for prompt in reversed(prompts):
            rows = list(
                con.execute(
                    """
                    SELECT p.timestamp, s.title, s.working_directory
                    FROM prompt_history p
                    JOIN sessions s ON s.id = p.session_id
                    WHERE p.content = ? AND s.title IS NOT NULL AND s.title != ''
                    ORDER BY p.timestamp DESC
                    LIMIT 8
                    """,
                    (prompt,),
                )
            )
            matched = []
            for row in rows:
                if cwd and row["working_directory"]:
                    try:
                        if os.path.realpath(row["working_directory"]) != os.path.realpath(
                            cwd
                        ):
                            continue
                    except OSError:
                        pass
                matched.append((row["timestamp"], row["title"]))
            if matched:
                return sanitize(matched[0][1])
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None


def extract_devin_picker_title(output: str) -> str | None:
    """Extract highlighted session title when Devin is in interactive resume picker."""
    if "Select a session to resume" not in output:
        return None
    for match in reversed(re.findall(r"❭\s+(.+)$", output, re.M)):
        title = re.split(r"\s{2,}|\s·\s", match.strip(), maxsplit=1)[0]
        if title and not SKIP_PROMPT.match(title):
            return sanitize(title)
    return None


class DevinExtractor(BaseExtractor):
    """Extractor for Devin AI sessions."""

    def matches(self, pane: dict, agent: dict) -> bool:
        return (pane.get("agent") or agent.get("agent")) == "devin"

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        pane_id = pane.get("pane_id") or agent.get("pane_id", "")
        output = read_output(pane_id, client)
        cwd = agent_cwd(pane, agent)

        renamed = extract_devin_rename(output)
        session_id = pick_newest_lock_session(
            pane_process_ids(pane_id, client), LOCK_DIR
        )
        db_title = title_from_session_id(session_id) if session_id else None
        live = resolve_devin_live_title(session_id, db_title, renamed)
        if live:
            return live

        if DEVIN_SESSION_RESET.search(output):
            return "New session"

        resume_id = devin_resume_id(agent)
        if resume_id:
            resume_title = title_from_session_id(resume_id)
            if resume_title:
                return resume_title

        tab_title = devin_tab_title(tab_label)
        if tab_title:
            return tab_title

        matched_db_title = devin_title_from_db(output, cwd)
        if matched_db_title:
            return matched_db_title

        picker = extract_devin_picker_title(output)
        if picker:
            return picker

        return first_user_prompt_title(output) or "New session"
