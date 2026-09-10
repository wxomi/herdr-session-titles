#!/usr/bin/env python3
"""Keep Herdr agent rows labeled with each agent's real session title."""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time

SOURCE = "wxomi.session-titles"
HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
SOCKET_PATH = os.environ.get(
    "HERDR_SOCKET_PATH",
    os.path.expanduser("~/.config/herdr/herdr.sock"),
)
DEVIN_DB = os.path.expanduser("~/.local/share/devin/cli/sessions.db")
LOCK_DIR = os.path.expanduser("~/.local/share/devin/cli/session_locks")
KIRO_SESSIONS = os.path.expanduser("~/.kiro/sessions/cli")
AGY_HOME = os.path.expanduser("~/.gemini/antigravity-cli")
STATE_DIR = os.environ.get(
    "HERDR_PLUGIN_STATE_DIR",
    os.path.expanduser("~/.config/herdr/plugins/state/wxomi.session-titles"),
)
PID_FILE = os.path.join(STATE_DIR, "watch.pid")
WATCH_SECONDS = float(os.environ.get("HERDR_SESSION_TITLES_INTERVAL", "2"))
SYNC_TABS = os.environ.get("HERDR_SESSION_TITLES_SYNC_TABS", "false").lower() in (
    "true",
    "1",
    "yes",
)

GENERIC_CLI_TITLE = re.compile(
    r"^(devin|cursor|cursor-agent|agy|codex|claude|grok|pi|opencode|copilot|"
    r"kimi|cline|gemini|kiro|kiro-cli|agent)\b",
    re.I,
)
GENERIC_NAMES = {
    "agent",
    "cursor",
    "cursor-agent",
    "devin",
    "agy",
    "kiro",
    "kiro-cli",
    "claude",
    "codex",
    "gemini",
}
KIRO_SESSION_ID = re.compile(
    r"(?:Loaded session|session_id|--resume(?:-id)?=)\s*([0-9a-fA-F-]{36})",
    re.I,
)
NUMERIC_TAB = re.compile(r"^\d+$")
DEVIN_TAB_PREFIX = re.compile(r"^devin\s*[-:]\s*", re.I)
DEVIN_RESUME_ID = re.compile(r"(?:^|\s)-r\s+([A-Za-z0-9_-]+)")
DEVIN_RENAMED = re.compile(r"Session renamed to\s+(.+)$", re.I)
DEVIN_SESSION_RESET = re.compile(
    r"Started new session|(?:❯|❭|>)\s+/clear\b",
    re.I,
)
SLASH_COMMAND = re.compile(r"^/")
AGY_CONVERSATION_ID = re.compile(
    r"(?:--conversation=|conversation=)([0-9a-fA-F-]{36})"
)
AGY_ANNOTATION_TITLE = re.compile(r'^title:"((?:\\.|[^"\\])*)"', re.M)
SKIP_PROMPT = re.compile(
    r"^(Ask Devin to build|Other \(type|/ Type to search|\d+\s|·\s)",
    re.I,
)


class HerdrClient:
    """Direct Unix domain socket client for Herdr JSON-RPC."""

    def __init__(self, sock_path: str | None = None):
        self.sock_path = sock_path or SOCKET_PATH

    def is_available(self) -> bool:
        return bool(self.sock_path and os.path.exists(self.sock_path))

    def call(self, method: str, params: dict | None = None, req_id: str = "p") -> dict:
        if not self.is_available():
            return {}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.sock_path)
                payload = (
                    json.dumps({"id": req_id, "method": method, "params": params or {}})
                    + "\n"
                )
                s.sendall(payload.encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in chunk:
                        break
                if not buf:
                    return {}
                return json.loads(buf.decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def snapshot(self) -> dict:
        res = self.call("session.snapshot")
        return (res.get("result") or {}).get("snapshot") or {}

    def read_pane(
        self, pane_id: str, lines: int = 250, source: str = "recent_unwrapped"
    ) -> str:
        res = self.call(
            "pane.read", {"pane_id": pane_id, "source": source, "lines": lines}
        )
        read_obj = (res.get("result") or {}).get("read") or {}
        return read_obj.get("text", "")

    def process_info(self, pane_id: str) -> dict:
        res = self.call("pane.process_info", {"pane_id": pane_id})
        return (res.get("result") or {}).get("process_info") or {}

    def report_metadata(
        self,
        pane_id: str,
        source: str,
        tokens: dict[str, str | None],
        title: str | None = None,
    ) -> bool:
        params: dict = {"pane_id": pane_id, "source": source, "tokens": tokens}
        if title:
            params["title"] = title
        res = self.call("pane.report_metadata", params)
        return "result" in res

    def rename_tab(self, tab_id: str, label: str) -> bool:
        res = self.call("tab.rename", {"tab_id": tab_id, "label": label})
        return "result" in res


CLIENT = HerdrClient()


def run(*args: str) -> dict:
    proc = subprocess.run(
        [HERDR, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


LEADING_IMAGE_PATH = re.compile(
    r"^(?:file://)?/[\w.\-/@~]+\.(?:png|jpg|jpeg|gif|webp|svg|bmp|tiff|heic|mp4|mov|webm)\b\s*",
    re.I,
)


def strip_leading_file_paths(text: str) -> str:
    current = text.strip()
    while True:
        stripped = LEADING_IMAGE_PATH.sub("", current).strip()
        if stripped == current:
            break
        current = stripped
    return current


def clean_prompt_for_title(text: str) -> str:
    cleaned = strip_leading_file_paths(text)
    if cleaned:
        return cleaned
    parts = text.strip().split()
    if parts:
        first = parts[0].strip().rstrip("/").split("/")[-1]
        if first:
            return first
    return text.strip()


def sanitize(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = title.replace(r"\n", " ").replace(r"\r", " ").replace(r"\t", " ")
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" ·-")
    if not cleaned:
        return None
    if len(cleaned) > 56:
        cleaned = cleaned[:53].rstrip() + "…"
    return cleaned


def tab_labels() -> dict[str, str]:
    payload = run("tab", "list")
    labels: dict[str, str] = {}
    for tab in (payload.get("result") or {}).get("tabs") or []:
        tab_id = tab.get("tab_id")
        label = tab.get("label")
        if tab_id and isinstance(label, str):
            labels[tab_id] = label
    return labels


def read_output(pane_id: str, lines: int = 250) -> str:
    if CLIENT.is_available():
        text = CLIENT.read_pane(pane_id, lines=lines)
        if text:
            return text
    proc = subprocess.run(
        [
            HERDR,
            "pane",
            "read",
            pane_id,
            "--source",
            "recent-unwrapped",
            "--lines",
            str(lines),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout or ""


def user_prompts(output: str) -> list[str]:
    found: list[str] = []
    for line in output.splitlines():
        match = re.match(r"^(?:❯|❭|>)\s+(.+)$", line.strip())
        if not match:
            continue
        text = match.group(1).strip()
        text = re.split(r"\s{2,}|\s·\s", text, maxsplit=1)[0].strip()
        if not text or SKIP_PROMPT.match(text) or SLASH_COMMAND.match(text):
            continue
        found.append(text)
    return found


def meaningful_terminal_title(title: str | None) -> str | None:
    if not title or not title.strip():
        return None
    cleaned = title.strip()
    if cleaned.lower() in GENERIC_NAMES:
        return None
    if GENERIC_CLI_TITLE.match(cleaned):
        return None
    if " --" in cleaned:
        return None
    return sanitize(cleaned)


def devin_tab_title(tab_label: str | None) -> str | None:
    if not tab_label:
        return None
    if DEVIN_TAB_PREFIX.match(tab_label):
        return sanitize(DEVIN_TAB_PREFIX.sub("", tab_label))
    return None


def connect_devin() -> sqlite3.Connection | None:
    if not os.path.exists(DEVIN_DB):
        return None
    try:
        con = sqlite3.connect(f"file:{DEVIN_DB}?mode=ro", uri=True, timeout=0.4)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


def pane_process_ids(pane_id: str) -> set[int]:
    info = {}
    if CLIENT.is_available():
        info = CLIENT.process_info(pane_id)
    if not info:
        payload = run("pane", "process-info", "--pane", pane_id)
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


def pick_newest_lock_session(pids: set[int], lock_dir: str) -> str | None:
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
    lines = output.splitlines()
    start = 0
    for index, line in enumerate(lines):
        if DEVIN_SESSION_RESET.search(line):
            start = index + 1
    return "\n".join(lines[start:])


def extract_devin_rename(output: str) -> str | None:
    lines = output_after_session_reset(output).splitlines()[-50:]
    titles: list[str] = []
    for line in lines:
        match = DEVIN_RENAMED.search(line.strip())
        if match:
            titles.append(match.group(1).strip())
    if not titles:
        return None
    return sanitize(titles[-1])


def resolve_devin_live_title(
    session_id: str | None,
    db_title: str | None,
    renamed: str | None,
) -> str | None:
    """Title for the process's current session; never leftover scrollback."""
    if session_id:
        return db_title or renamed or "New session"
    return renamed


def first_user_prompt_title(output: str) -> str | None:
    prompts = user_prompts(output)
    if not prompts:
        return None
    return sanitize(clean_prompt_for_title(prompts[0]))


def devin_resume_id(agent: dict) -> str | None:
    for field in ("terminal_title_stripped", "terminal_title"):
        value = agent.get(field)
        if not isinstance(value, str):
            continue
        match = DEVIN_RESUME_ID.search(value)
        if match:
            return match.group(1)
    return None


def devin_title_from_lock(pane_id: str) -> str | None:
    session_id = pick_newest_lock_session(pane_process_ids(pane_id), LOCK_DIR)
    if not session_id:
        return None
    return title_from_session_id(session_id)


def devin_title_from_db(output: str, cwd: str | None) -> str | None:
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
    if "Select a session to resume" not in output:
        return None
    for line in reversed(output.splitlines()):
        if "❭" not in line:
            continue
        match = re.search(r"❭\s+(.+)$", line)
        if not match:
            continue
        title = re.split(r"\s{2,}|\s·\s", match.group(1).strip(), maxsplit=1)[0]
        if title and not SKIP_PROMPT.match(title):
            return sanitize(title)
    return None


def agy_conversation_id(agent: dict) -> str | None:
    session = agent.get("agent_session")
    if isinstance(session, dict):
        value = session.get("value")
        if isinstance(value, str) and value:
            return value
    for field in ("terminal_title_stripped", "terminal_title"):
        value = agent.get(field)
        if isinstance(value, str):
            match = AGY_CONVERSATION_ID.search(value)
            if match:
                return match.group(1)
    return None


def extract_agy_title(agent: dict) -> str | None:
    conversation_id = agy_conversation_id(agent)
    if not conversation_id:
        return None

    annotation_path = os.path.join(
        AGY_HOME, "annotations", f"{conversation_id}.pbtxt"
    )
    try:
        with open(annotation_path, encoding="utf-8") as handle:
            match = AGY_ANNOTATION_TITLE.search(handle.read())
        if match:
            return sanitize(bytes(match.group(1), "utf-8").decode("unicode_escape"))
    except OSError:
        pass

    transcript_path = os.path.join(
        AGY_HOME,
        "brain",
        conversation_id,
        ".system_generated",
        "logs",
        "transcript.jsonl",
    )
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            for line in handle:
                if "USER_REQUEST" not in line:
                    continue
                try:
                    entry = json.loads(line)
                    content = entry.get("content", "") if isinstance(entry, dict) else line
                except (json.JSONDecodeError, AttributeError):
                    content = line
                request = re.search(
                    r"<USER_REQUEST>\s*(.+?)\s*</USER_REQUEST>", content, re.S
                )
                if request:
                    prompt = clean_prompt_for_title(request.group(1))
                    return sanitize(prompt)
                break
    except OSError:
        pass
    return None


def pid_ancestors(pid: int, limit: int = 10) -> set[int]:
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


def extract_kiro_title(pane_id: str, agent: dict) -> str | None:
    pane_pids = pane_process_ids(pane_id)
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

    output = read_output(pane_id, lines=80)
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


def title_for_pane(pane: dict, agent: dict, tab_label: str | None) -> str | None:
    kind = pane.get("agent") or agent.get("agent")
    terminal_title = meaningful_terminal_title(agent.get("terminal_title_stripped"))
    cwd = agent.get("cwd") or agent.get("foreground_cwd")

    if kind == "devin":
        output = read_output(pane["pane_id"])
        renamed = extract_devin_rename(output)
        session_id = pick_newest_lock_session(
            pane_process_ids(pane["pane_id"]), LOCK_DIR
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
        db_title = devin_title_from_db(output, cwd)
        if db_title:
            return db_title
        picker = extract_devin_picker_title(output)
        if picker:
            return picker
        return first_user_prompt_title(output) or "New session"

    if kind in ("kiro", "kiro-cli"):
        kiro_title = extract_kiro_title(pane["pane_id"], agent)
        if kiro_title:
            return kiro_title
        return "New session"

    if kind == "agy":
        agy_title = extract_agy_title(agent)
        if agy_title:
            return agy_title
        if agy_conversation_id(agent):
            return "New session"
        return first_user_prompt_title(read_output(pane["pane_id"])) or "New session"

    if terminal_title:
        return terminal_title
    if tab_label and not NUMERIC_TAB.match(tab_label):
        return sanitize(tab_label)
    return first_user_prompt_title(read_output(pane["pane_id"])) or "New session"


def current_token(agent: dict) -> str | None:
    tokens = agent.get("tokens") or {}
    value = tokens.get("session")
    return value if isinstance(value, str) and value else None


def agent_cwd(pane: dict, agent: dict) -> str | None:
    for source in (agent, pane):
        for key in ("foreground_cwd", "cwd"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def format_agent_path(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        path = os.path.realpath(os.path.expanduser(cwd))
    except OSError:
        return None
    home = os.path.realpath(os.path.expanduser("~"))
    if path == home:
        return "~"
    name = os.path.basename(path)
    return name or path


def format_agent_location(kind: str | None, cwd: str | None) -> str | None:
    if not kind:
        return None
    path = format_agent_path(cwd)
    if path:
        return f"{kind} · {path}"
    return kind


def report_tokens(
    pane_id: str,
    updates: dict[str, str | None],
    previous: dict[str, str | None],
) -> None:
    changed = False
    for name, value in updates.items():
        if value != previous.get(name):
            changed = True
            break
    if not changed:
        return

    title = updates.get("session")
    if CLIENT.is_available():
        if CLIENT.report_metadata(pane_id, SOURCE, updates, title=title):
            return

    # Fallback to CLI
    args = ["pane", "report-metadata", pane_id, "--source", SOURCE]
    if title:
        args.extend(["--title", title])
    for name, value in updates.items():
        if value:
            args.extend(["--token", f"{name}={value}"])
        else:
            args.extend(["--clear-token", name])
    run(*args)


def report_title(pane_id: str, title: str | None, previous: str | None) -> None:
    report_tokens(pane_id, {"session": title}, {"session": previous})


def sync_all(only_pane: str | None = None, sync_tabs: bool | None = None) -> None:
    do_sync_tabs = (
        SYNC_TABS
        if sync_tabs is None
        else sync_tabs
        or ("--sync-tabs" in sys.argv)
    )

    snap = CLIENT.snapshot() if CLIENT.is_available() else {}
    if snap:
        tabs = {
            t["tab_id"]: t.get("label", "")
            for t in snap.get("tabs", [])
            if isinstance(t, dict) and "tab_id" in t
        }
        tab_numbers = {
            t["tab_id"]: t.get("number")
            for t in snap.get("tabs", [])
            if isinstance(t, dict) and "tab_id" in t and t.get("number") is not None
        }
        panes_by_id = {
            p["pane_id"]: p
            for p in snap.get("panes", [])
            if isinstance(p, dict) and "pane_id" in p
        }
        agents = snap.get("agents", [])
    else:
        tabs = tab_labels()
        tab_numbers = {}
        panes_by_id = {}
        agents = []
        panes = (run("pane", "list").get("result") or {}).get("panes") or []
        for p in panes:
            pid = p.get("pane_id")
            if pid and p.get("agent"):
                ag = (run("agent", "get", pid).get("result") or {}).get("agent") or {}
                agents.append(ag)
                panes_by_id[pid] = p

    for agent in agents:
        pane_id = agent.get("pane_id")
        if not pane_id or (only_pane and pane_id != only_pane):
            continue
        pane = panes_by_id.get(pane_id) or agent
        tab_id = agent.get("tab_id") or pane.get("tab_id", "")
        tab_label = tabs.get(tab_id)
        title = title_for_pane(pane, agent, tab_label)
        location = format_agent_location(
            pane.get("agent") or agent.get("agent"),
            agent_cwd(pane, agent),
        )
        tokens = agent.get("tokens") or {}
        report_tokens(
            pane_id,
            {"session": title, "location": location, "path": None},
            {
                "session": tokens.get("session")
                if isinstance(tokens.get("session"), str)
                else None,
                "location": tokens.get("location")
                if isinstance(tokens.get("location"), str)
                else None,
                "path": tokens.get("path")
                if isinstance(tokens.get("path"), str)
                else None,
            },
        )
        if do_sync_tabs and tab_id and title:
            num = tab_numbers.get(tab_id)
            desired_tab = f"{num} · {title}" if num else title
            if tab_label != desired_tab:
                if CLIENT.is_available():
                    CLIENT.rename_tab(tab_id, desired_tab)
                else:
                    run("tab", "rename", tab_id, desired_tab)


def already_watching() -> bool:
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
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def watch(sync_tabs: bool = False) -> int:
    if already_watching():
        return 0
    write_pid()
    try:
        while True:
            sync_all(sync_tabs=sync_tabs)
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


def main(argv: list[str]) -> int:
    only_pane = None
    sync_tabs = "--sync-tabs" in argv or SYNC_TABS
    if "--watch" in argv:
        return watch(sync_tabs=sync_tabs)
    if len(argv) >= 3 and argv[1] == "--pane":
        only_pane = argv[2]
        if only_pane.startswith("$"):
            only_pane = None
    sync_all(only_pane, sync_tabs=sync_tabs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
