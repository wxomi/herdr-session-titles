"""Unit tests for Antigravity (Agy) session title extraction."""

from __future__ import annotations

import unittest

from session_titles.extractors.agy import agy_conversation_id


class AgyConversationIdTests(unittest.TestCase):
    def test_prefers_herdr_session_over_stale_terminal_conversation(self) -> None:
        agent = {
            "terminal_title_stripped": (
                "agy --conversation=f4bcdff8-3bde-4fb7-a878-d039dcc5f218"
            ),
            "agent_session": {
                "agent": "agy",
                "kind": "id",
                "source": "herdr:antigravity_cli",
                "value": "ff1b1b9d-0acb-499e-a6e1-eb43e1ac1f63",
            },
            "cwd": "/Users/wxomi",
        }
        self.assertEqual(
            agy_conversation_id(agent),
            "ff1b1b9d-0acb-499e-a6e1-eb43e1ac1f63",
        )

    def test_ignores_cwd_last_conversation_cache(self) -> None:
        agent = {"cwd": "/Users/wxomi"}
        self.assertIsNone(agy_conversation_id(agent))


if __name__ == "__main__":
    unittest.main()
