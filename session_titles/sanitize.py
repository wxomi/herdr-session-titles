"""Text sanitization, prompt extraction, and path formatting utilities."""

from __future__ import annotations

import os
import re

from session_titles.config import (
    GENERIC_CLI_TITLE,
    GENERIC_NAMES,
    LEADING_IMAGE_PATH,
    SKIP_PROMPT,
    SLASH_COMMAND,
)


def strip_leading_file_paths(text: str) -> str:
    """Remove absolute file/screenshot paths prepended to prompts."""
    return LEADING_IMAGE_PATH.sub("", text.strip()).strip()


def clean_prompt_for_title(text: str) -> str:
    """Extract a concise title from raw prompt text, handling images/screenshots."""
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
    """Clean whitespace, strip escape sequences, and cap max length."""
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


def user_prompts(output: str) -> list[str]:
    """Parse user prompt lines (starting with ❯, ❭, or >) from terminal output."""
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


def first_user_prompt_title(output: str) -> str | None:
    """Return the first meaningful user prompt from terminal output as a title."""
    prompts = user_prompts(output)
    if not prompts:
        return None
    return sanitize(clean_prompt_for_title(prompts[0]))


def meaningful_terminal_title(title: str | None) -> str | None:
    """Filter out generic CLI titles or raw execution commands."""
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


def format_agent_path(cwd: str | None) -> str | None:
    """Format a working directory as ~ or the project basename."""
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
    """Combine agent type and working directory into a readable location string."""
    if not kind:
        return None
    path = format_agent_path(cwd)
    if path:
        return f"{kind} · {path}"
    return kind


def agent_cwd(pane: dict, agent: dict) -> str | None:
    """Resolve the working directory from agent or pane dictionaries."""
    for source in (agent, pane):
        for key in ("foreground_cwd", "cwd"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None
