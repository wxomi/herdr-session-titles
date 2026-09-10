"""Session title extractor for Antigravity (Agy) sessions."""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from session_titles.config import (
    AGY_ANNOTATION_TITLE,
    AGY_CONVERSATION_ID,
    AGY_HOME,
)
from session_titles.client import read_output
from session_titles.extractors.base import BaseExtractor
from session_titles.sanitize import clean_prompt_for_title, first_user_prompt_title, sanitize

if TYPE_CHECKING:
    from session_titles.client import HerdrClient


def agy_conversation_id(agent: dict) -> str | None:
    """Extract Agy conversation UUID from agent session or terminal title."""
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
    """Read session title from Agy annotation (.pbtxt) or transcript (.jsonl)."""
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


class AgyExtractor(BaseExtractor):
    """Extractor for Antigravity (agy) AI sessions."""

    def matches(self, pane: dict, agent: dict) -> bool:
        return (pane.get("agent") or agent.get("agent")) == "agy"

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        agy_title = extract_agy_title(agent)
        if agy_title:
            return agy_title
        if agy_conversation_id(agent):
            return "New session"
        pane_id = pane.get("pane_id") or agent.get("pane_id", "")
        output = read_output(pane_id, client)
        return first_user_prompt_title(output) or "New session"
