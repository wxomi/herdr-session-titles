"""Unit tests for the extractor registry and dispatch chain."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from session_titles.client import HerdrClient
from session_titles.extractors import DEFAULT_EXTRACTORS, register_extractor, title_for_pane
from session_titles.extractors.base import BaseExtractor


class DummyExtractor(BaseExtractor):
    def matches(self, pane: dict, agent: dict) -> bool:
        return agent.get("agent") == "custom-agent"

    def extract(
        self,
        pane: dict,
        agent: dict,
        tab_label: str | None,
        client: HerdrClient,
    ) -> str | None:
        return "Custom Agent Task"


class ExtractorRegistryTests(unittest.TestCase):
    def test_custom_extractor_matches_and_extracts(self) -> None:
        mock_client = MagicMock(spec=HerdrClient)
        register_extractor(DummyExtractor(), prepend=True)

        pane = {"pane_id": "p1", "agent": "custom-agent"}
        agent = {"pane_id": "p1", "agent": "custom-agent"}

        title = title_for_pane(pane, agent, None, mock_client)
        self.assertEqual(title, "Custom Agent Task")

    def test_fallback_extractor_handles_unrecognized_agents(self) -> None:
        mock_client = MagicMock(spec=HerdrClient)
        mock_client.is_available.return_value = False

        pane = {"pane_id": "p2", "agent": "unknown-cli"}
        agent = {
            "pane_id": "p2",
            "agent": "unknown-cli",
            "terminal_title_stripped": "Feature #1234 refactoring",
        }

        title = title_for_pane(pane, agent, None, mock_client)
        self.assertEqual(title, "Feature #1234 refactoring")


if __name__ == "__main__":
    unittest.main()
