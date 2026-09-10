"""Registry and dispatcher for agent title extractors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from session_titles.extractors.agy import AgyExtractor
from session_titles.extractors.base import BaseExtractor
from session_titles.extractors.devin import DevinExtractor
from session_titles.extractors.fallback import FallbackExtractor
from session_titles.extractors.kiro import KiroExtractor

if TYPE_CHECKING:
    from session_titles.client import HerdrClient

DEFAULT_EXTRACTORS: list[BaseExtractor] = [
    DevinExtractor(),
    KiroExtractor(),
    AgyExtractor(),
    FallbackExtractor(),
]


def register_extractor(extractor: BaseExtractor, prepend: bool = True) -> None:
    """Register a new extractor in the extractor chain."""
    if prepend:
        DEFAULT_EXTRACTORS.insert(0, extractor)
    else:
        # Insert before FallbackExtractor
        DEFAULT_EXTRACTORS.insert(len(DEFAULT_EXTRACTORS) - 1, extractor)


def title_for_pane(
    pane: dict,
    agent: dict,
    tab_label: str | None,
    client: HerdrClient,
    extractors: list[BaseExtractor] | None = None,
) -> str | None:
    """Run matching extractors in sequence until one resolves a title."""
    chain = extractors or DEFAULT_EXTRACTORS
    for extractor in chain:
        if extractor.matches(pane, agent):
            title = extractor.extract(pane, agent, tab_label, client)
            if title:
                return title
    return None
