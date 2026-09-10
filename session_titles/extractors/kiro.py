"""Session title extractor for Kiro CLI sessions."""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

from session_titles.config import KIRO_SESSION_ID, KIRO_SESSIONS
from session_titles.client import read_output
from session_titles.extractors.base import BaseExtractor
from session_titles.extractors.devin import pane_process_ids
from session_titles.sanitize import first_user_prompt_title, sanitize

if TYPE_CHECKING:
    from session_titles.client import HerdrClient


def pid_ancestors(pid: int, limit: int = 10) -> set[int]:
    """Find parent processes up to limit hops."""
    found = {pid}
    current = pid
    for _ in range(limit):
        proc = subprocess.run(
            ["ps", "-p", str(current), "-o", "ppid="],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            parent = int(proc.stdout.strip() or "0")
        except ValueError:
            break
        if parent <= 1 or parent in found:
            break
        found.add(parent)
        current = parent
    return found


def kiro_title_from_id(session_id: str) -> str | None:
    """Read title property from Kiro's local session JSON file."""
    path = os.path.join(KIRO_SESSIONS, f"{session_id}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        title = data.get("title") if isinstance(data, dict) else None
        if isinstance(title, str) and title.strip():
            return sanitize(title)
    except (OSError, json.JSONDecodeError):
        pass
    return None


def extract_kiro_title(pane_id: str, agent: dict, client: HerdrClient) -> str | None:
    """Resolve session title from Kiro process lock, terminal output, or session store."""
    pane_pids = pane_process_ids(pane_id, client)
    if pane_pids and os.path.isdir(KIRO_SESSIONS):
        try:
            for name in os.listdir(KIRO_SESSIONS):
                if not name.endswith(".lock"):
                    continue
                path = os.path.join(KIRO_SESSIONS, name)
                try:
                    with open(path, encoding="utf-8") as handle:
                        payload = json.load(handle)
                    lock_pid = int(payload.get("pid") or 0)
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    continue
                if lock_pid and (pane_pids & pid_ancestors(lock_pid)):
                    title = kiro_title_from_id(name[: -len(".lock")])
                    if title:
                        return title
        except OSError:
            pass

    output = read_output(pane_id, client, lines=80)
    match = KIRO_SESSION_ID.search(output)
    if match:
        title = kiro_title_from_id(match.group(1))
        if title:
            return title

    session = agent.get("agent_session")
    if isinstance(session, dict):
        value = session.get("value")
        if isinstance(value, str) and value:
            title = kiro_title_from_id(value)
            if title:
                return title

    return first_user_prompt_title(output)


class KiroExtractor(BaseExtractor):
    """Extractor for Kiro AI sessions."""

    def matches(self, pane: dict, agent: dict) -> bool:
        return (pane.get("agent") or agent.get("agent")) in ("kiro", "kiro-cli")

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        pane_id = pane.get("pane_id") or agent.get("pane_id", "")
        kiro_title = extract_kiro_title(pane_id, agent, client)
        if kiro_title:
            return kiro_title
        return "New session"
