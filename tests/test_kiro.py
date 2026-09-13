"""Unit tests for Kiro session title extractor."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from session_titles.client import HerdrClient
from session_titles.extractors.kiro import (
    KiroExtractor,
    extract_kiro_title,
    kiro_title_from_id,
)


class KiroExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cli_dir = os.path.join(self.temp_dir.name, "cli")
        os.makedirs(self.cli_dir, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_kiro_title_from_cli_session_strips_leading_file_path(self) -> None:
        session_id = "test-session-1234"
        session_file = os.path.join(self.cli_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": session_id,
                    "title": "private/tmp/auction-handoff.XhiI0d/T45399-D39466-handoff.md can you also check which is best approch",
                },
                f,
            )

        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir):
            title = kiro_title_from_id(session_id)
            self.assertEqual(title, "can you also check which is best approch")

    def test_kiro_title_from_workspace_session(self) -> None:
        session_id = "test-workspace-5678"
        ws_dir = os.path.join(self.temp_dir.name, "4a3745c192c6fada", session_id)
        os.makedirs(ws_dir, exist_ok=True)
        session_file = os.path.join(ws_dir, "session.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": session_id,
                    "title": "Add crash course transcript",
                },
                f,
            )

        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir):
            title = kiro_title_from_id(session_id)
            self.assertEqual(title, "Add crash course transcript")

    def test_kiro_title_only_file_path_uses_basename(self) -> None:
        session_id = "test-session-file-only"
        session_file = os.path.join(self.cli_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": session_id,
                    "title": "private/tmp/auction-handoff.XhiI0d/T45399-D39466-handoff.md",
                },
                f,
            )

        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir):
            title = kiro_title_from_id(session_id)
            self.assertEqual(title, "T45399-D39466-handoff.md")

    def test_kiro_extractor_matches(self) -> None:
        extractor = KiroExtractor()
        # Direct agent field
        self.assertTrue(extractor.matches({"agent": "kiro"}, {}))
        self.assertTrue(extractor.matches({}, {"agent": "kiro-cli"}))

        # Terminal title field
        self.assertTrue(
            extractor.matches(
                {"agent": None, "terminal_title": "kiro-cli chat --trust-all-tools"},
                {},
            )
        )
        self.assertTrue(
            extractor.matches(
                {},
                {"agent": "unknown", "terminal_title_stripped": "kiro chat"},
            )
        )

        # Unrelated agent
        self.assertFalse(extractor.matches({"agent": "cursor"}, {}))
        self.assertFalse(extractor.matches({"agent": None, "terminal_title": "zsh"}, {}))

    @patch("session_titles.extractors.kiro.pane_process_ids")
    @patch("session_titles.extractors.kiro.pid_ancestors")
    def test_extract_kiro_title_from_lock_file(
        self, mock_ancestors: MagicMock, mock_pane_pids: MagicMock
    ) -> None:
        session_id = "active-lock-session"
        lock_file = os.path.join(self.cli_dir, f"{session_id}.lock")
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": 9999}, f)

        session_file = os.path.join(self.cli_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"title": "Fix memory leak in parser"}, f)

        mock_pane_pids.return_value = {1234}
        mock_ancestors.return_value = {1234, 9999}

        mock_client = MagicMock(spec=HerdrClient)
        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir):
            title = extract_kiro_title("p1", {}, mock_client)
            self.assertEqual(title, "Fix memory leak in parser")


if __name__ == "__main__":
    unittest.main()
