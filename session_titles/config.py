"""Configuration, file paths, and regular expressions for session_titles."""

from __future__ import annotations

import os
import re

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
AUTO_ROUTE_AGENTS = os.environ.get(
    "HERDR_AUTO_ROUTE_AGENTS", "true"
).lower() in ("true", "1", "yes")
AGENTS_WORKSPACE_NAME = os.environ.get("HERDR_AGENTS_WORKSPACE", "agents")

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
NUMERIC_TAB = re.compile(r"^\d+$")
SLASH_COMMAND = re.compile(r"^/")
SKIP_PROMPT = re.compile(
    r"^(Ask Devin to build|Other \(type|/ Type to search|\d+\s|·\s)",
    re.I,
)
LEADING_IMAGE_PATH = re.compile(
    r"^(?:(?:file://)?/[\w.\-/@~]+\.(?:png|jpg|jpeg|gif|webp|svg|bmp|tiff|heic|mp4|mov|webm)\b\s*)+",
    re.I,
)
DEVIN_TAB_PREFIX = re.compile(r"^devin\s*[-:]\s*", re.I)
DEVIN_RESUME_ID = re.compile(r"(?:^|\s)-r\s+([A-Za-z0-9_-]+)")
DEVIN_RENAMED = re.compile(r"Session renamed to\s+(.+)$", re.I)
DEVIN_SESSION_RESET = re.compile(
    r"Started new session|(?:❯|❭|>)\s+/clear\b",
    re.I,
)
KIRO_SESSION_ID = re.compile(
    r"(?:Loaded session|session_id|--resume(?:-id)?=)\s*([0-9a-fA-F-]{36})",
    re.I,
)
AGY_CONVERSATION_ID = re.compile(
    r"(?:--conversation=|conversation=)([0-9a-fA-F-]{36})"
)
AGY_ANNOTATION_TITLE = re.compile(r'^title:"((?:\\.|[^"\\])*)"', re.M)
