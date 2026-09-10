"""Base extractor protocol for agent session titles."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from session_titles.client import HerdrClient


class BaseExtractor(abc.ABC):
    """Abstract base class for extracting a session title from an agent pane."""

    @abc.abstractmethod
    def matches(self, pane: dict, agent: dict) -> bool:
        """Return True if this extractor can handle the given agent or pane."""

    @abc.abstractmethod
    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        """Extract and return the session title, or None if not found."""
