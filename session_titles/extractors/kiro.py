"""Session title extractor for Kiro CLI sessions."""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from typing import TYPE_CHECKING

from session_titles.config import (
    GENERIC_NAMES,
    KIRO_DASHBOARD_META,
    KIRO_PREFIX,
    KIRO_RENAMED,
    KIRO_SESSION_ID,
    KIRO_SESSIONS,
    KIRO_TAB_PREFIX,
    NUMERIC_TAB,
)
from session_titles.client import read_output
from session_titles.extractors.base import BaseExtractor
from session_titles.extractors.devin import pane_process_ids
from session_titles.sanitize import (
    agent_cwd,
    clean_prompt_for_title,
    first_user_prompt_title,
    sanitize,
)

if TYPE_CHECKING:
    from session_titles.client import HerdrClient

SPINNER_PREFIX = re.compile(
    r"^[\s\u2800-\u28ff\u25c0-\u25ff\u2700-\u27bf*•·\-\+~|/\\<>=!@#$%^&]+",
    re.UNICODE,
)


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


def kiro_title_from_terminal(title: str | None, cwd: str | None = None) -> str | None:
    """Extract renamed session title from Kiro terminal window title.

    Kiro updates the terminal window title via OSC escape sequences when
    the user runs `/title <name>` (e.g. 'kiro: Behaviour Changes' or
    '⠋ kiro: Behaviour Changes'). When no custom title is set, Kiro defaults
    to the working directory ('kiro: ~/work/repo/devel/auction') or command
    invocations ('kiro-cli chat --trust-all-tools').
    """
    if not title or not title.strip():
        return None
    raw = SPINNER_PREFIX.sub("", title.strip()).strip()
    if KIRO_PREFIX.match(raw):
        cleaned = KIRO_PREFIX.sub("", raw).strip()
    elif raw.lower().startswith(("kiro-cli", "kiro")):
        return None
    else:
        cleaned = raw

    if not cleaned:
        return None
    if cleaned.lower() in GENERIC_NAMES:
        return None
    if cleaned.startswith("--") or " --" in cleaned:
        return None
    if cleaned.lower() in ("chat", "term", "tui") or cleaned.lower().startswith("chat "):
        return None

    # Check path / cwd fallbacks
    if cleaned.startswith(("~", "/", "./", "../")) or cleaned == ".":
        return None
    if cwd:
        norm_cwd = os.path.normpath(os.path.expanduser(cwd))
        norm_cand = os.path.normpath(os.path.expanduser(cleaned))
        if norm_cand == norm_cwd or cleaned == os.path.basename(norm_cwd):
            return None
        parts = [p for p in norm_cwd.split(os.sep) if p]
        if cleaned.strip("/") in parts:
            return None
        cand_parts = [p for p in cleaned.split("/") if p]
        if len(cand_parts) > 1 and len(cand_parts) <= len(parts):
            if parts[-len(cand_parts):] == cand_parts:
                return None

    return sanitize(cleaned)


def kiro_title_from_meta(session_id: str) -> str | None:
    """Read renamed session title from Kiro dashboard-meta.json sidecar."""
    meta_path = KIRO_DASHBOARD_META
    if not os.path.isfile(meta_path):
        parent_meta = os.path.join(
            os.path.dirname(KIRO_SESSIONS), "dashboard-meta.json"
        )
        if os.path.isfile(parent_meta):
            meta_path = parent_meta
        else:
            return None
    try:
        with open(meta_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            entry = data.get(session_id)
            if isinstance(entry, dict):
                title = entry.get("title")
                if isinstance(title, str) and title.strip():
                    return sanitize(clean_prompt_for_title(title))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def extract_kiro_rename(output: str) -> str | None:
    """Detect explicit rename or title confirmation in terminal scrollback."""
    if not isinstance(output, str) or not output.strip():
        return None
    matches = KIRO_RENAMED.findall(output)
    if matches:
        title = matches[-1].strip().strip('"').strip("'")
        if title:
            return sanitize(clean_prompt_for_title(title))
    return None


def kiro_title_from_tab(tab_label: str | None, cwd: str | None = None) -> str | None:
    """Extract custom title from Herdr tab label if renamed by user."""
    if not tab_label or not tab_label.strip():
        return None
    cleaned = tab_label.strip()
    if NUMERIC_TAB.match(cleaned):
        return None
    # Strip leading tab numbering (e.g. '61 · ...' or '1 - ...')
    cleaned = re.sub(r"^\d+\s*[·\-:]\s*", "", cleaned).strip()
    if not cleaned:
        return None
    if KIRO_TAB_PREFIX.match(cleaned):
        cleaned = KIRO_TAB_PREFIX.sub("", cleaned).strip()
    if not cleaned or cleaned.lower() in GENERIC_NAMES:
        return None
    if cleaned.startswith(("~", "/", "./", "../")) or cleaned == ".":
        return None
    if cwd:
        norm_cwd = os.path.normpath(os.path.expanduser(cwd))
        norm_cand = os.path.normpath(os.path.expanduser(cleaned))
        if norm_cand == norm_cwd or cleaned == os.path.basename(norm_cwd):
            return None
    return sanitize(cleaned)


def kiro_title_from_id(session_id: str) -> str | None:
    """Read title property from Kiro's local CLI or workspace session JSON file."""
    paths = [os.path.join(KIRO_SESSIONS, f"{session_id}.json")]
    workspace_pattern = os.path.join(
        os.path.dirname(KIRO_SESSIONS), "*", session_id, "session.json"
    )
    paths.extend(glob.glob(workspace_pattern))
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            title = data.get("title") if isinstance(data, dict) else None
            if isinstance(title, str) and title.strip():
                return sanitize(clean_prompt_for_title(title))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def extract_kiro_title(
    pane_id: str,
    agent: dict,
    client: HerdrClient,
    pane: dict | None = None,
    tab_label: str | None = None,
) -> str | None:
    """Resolve session title from explicit renames, Kiro process lock, terminal output, or session store."""
    p_dict = pane or {}
    a_dict = agent or {}
    cwd = agent_cwd(p_dict, a_dict)

    # 1. Explicit pane label if user renamed pane in Herdr
    pane_label = p_dict.get("label")
    if isinstance(pane_label, str) and pane_label.strip():
        cleaned_pane = pane_label.strip()
        if not NUMERIC_TAB.match(cleaned_pane) and cleaned_pane.lower() not in GENERIC_NAMES:
            sanitized_pane = sanitize(cleaned_pane)
            if sanitized_pane:
                return sanitized_pane

    # 2. Terminal title (explicit /title in kiro-cli, or kiro terminal title update)
    for field in ("terminal_title_stripped", "terminal_title"):
        for source in (p_dict, a_dict):
            val = source.get(field)
            if isinstance(val, str):
                term_title = kiro_title_from_terminal(val, cwd)
                if term_title:
                    return term_title

    # 3. Read output for explicit rename confirmations in scrollback
    raw_output = read_output(pane_id, client, lines=80)
    output = raw_output if isinstance(raw_output, str) else ""
    renamed = extract_kiro_rename(output)
    if renamed:
        return renamed

    # 4. Resolve session_id
    session_id: str | None = None
    pane_pids = pane_process_ids(pane_id, client)
    if pane_pids and os.path.isdir(KIRO_SESSIONS):
        lock_paths = [
            os.path.join(KIRO_SESSIONS, name)
            for name in os.listdir(KIRO_SESSIONS)
            if name.endswith(".lock")
        ]
        lock_paths.extend(
            glob.glob(os.path.join(os.path.dirname(KIRO_SESSIONS), "*", "*.lock"))
        )
        for path in lock_paths:
            try:
                with open(path, encoding="utf-8") as handle:
                    payload = json.load(handle)
                lock_pid = int(payload.get("pid") or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if lock_pid and (pane_pids & pid_ancestors(lock_pid)):
                session_id = os.path.splitext(os.path.basename(path))[0]
                break

    if not session_id and output:
        match = KIRO_SESSION_ID.search(output)
        if match:
            session_id = match.group(1)

    if not session_id:
        session = a_dict.get("agent_session")
        if isinstance(session, dict):
            value = session.get("value")
            if isinstance(value, str) and value:
                session_id = value

    if session_id:
        meta_title = kiro_title_from_meta(session_id)
        if meta_title:
            return meta_title
        json_title = kiro_title_from_id(session_id)
        if json_title:
            return json_title

    # 5. Tab label if explicitly renamed in Herdr
    tab_title = kiro_title_from_tab(tab_label, cwd)
    if tab_title:
        return tab_title

    # 6. Fallback to first user prompt in output
    return first_user_prompt_title(output)


class KiroExtractor(BaseExtractor):
    """Extractor for Kiro AI sessions."""

    def matches(self, pane: dict, agent: dict) -> bool:
        agent_kind = pane.get("agent") or agent.get("agent")
        if agent_kind in ("kiro", "kiro-cli"):
            return True
        for field in ("terminal_title", "terminal_title_stripped", "command"):
            val = (pane.get(field) or agent.get(field) or "").strip().lower()
            if val.startswith(("kiro", "kiro-cli")):
                return True
        return False

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        pane_id = pane.get("pane_id") or agent.get("pane_id", "")
        kiro_title = extract_kiro_title(
            pane_id, agent, client, pane=pane, tab_label=tab_label
        )
        if kiro_title:
            return kiro_title
        return "New session"
