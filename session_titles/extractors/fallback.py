"""Fallback session title extractor for Cursor, Claude, and generic panes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from session_titles.config import NUMERIC_TAB
from session_titles.client import read_output
from session_titles.extractors.base import BaseExtractor
from session_titles.sanitize import (
    first_user_prompt_title,
    meaningful_terminal_title,
    sanitize,
)

if TYPE_CHECKING:
    from session_titles.client import HerdrClient


class FallbackExtractor(BaseExtractor):
    """Fallback extractor that resolves titles from terminal titles, tab labels, or prompts."""

    def matches(self, pane: dict, agent: dict) -> bool:
        return True  # Catch-all at the end of the extractor chain

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        terminal_title = meaningful_terminal_title(agent.get("terminal_title_stripped"))
        if terminal_title:
            return terminal_title

        if tab_label and not NUMERIC_TAB.match(tab_label):
            return sanitize(tab_label)

        pane_id = pane.get("pane_id") or agent.get("pane_id", "")
        output = read_output(pane_id, client)
        return first_user_prompt_title(output) or "New session"
