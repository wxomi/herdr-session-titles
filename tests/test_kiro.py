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

    def test_kiro_title_from_terminal_title(self) -> None:
        from session_titles.extractors.kiro import kiro_title_from_terminal

        cwd = "/home/wxomi/work/repo/devel/auction"
        # Explicit user title set via /title
        self.assertEqual(
            kiro_title_from_terminal("kiro: Behaviour Changes", cwd),
            "Behaviour Changes",
        )
        # Working animation spinners
        self.assertEqual(
            kiro_title_from_terminal("⠋ kiro: Behaviour Changes", cwd),
            "Behaviour Changes",
        )
        self.assertEqual(
            kiro_title_from_terminal("◐ kiro: Fix Payment Processing", cwd),
            "Fix Payment Processing",
        )
        # Fallback directory paths should be ignored
        self.assertIsNone(
            kiro_title_from_terminal("kiro: ~/work/repo/devel/auction", cwd)
        )
        self.assertIsNone(
            kiro_title_from_terminal("kiro: auction", cwd)
        )
        self.assertIsNone(
            kiro_title_from_terminal("kiro: devel/auction", cwd)
        )
        self.assertIsNone(
            kiro_title_from_terminal("kiro: /home/wxomi/work/repo/devel/auction", cwd)
        )
        # CLI command execution should be ignored
        self.assertIsNone(
            kiro_title_from_terminal("kiro-cli chat --trust-all-tools", cwd)
        )
        self.assertIsNone(
            kiro_title_from_terminal("kiro-cli", cwd)
        )

    @patch("session_titles.extractors.kiro.pane_process_ids")
    @patch("session_titles.extractors.kiro.pid_ancestors")
    def test_extract_kiro_title_prefers_terminal_title_over_session_json(
        self, mock_ancestors: MagicMock, mock_pane_pids: MagicMock
    ) -> None:
        session_id = "active-session-renamed"
        lock_file = os.path.join(self.cli_dir, f"{session_id}.lock")
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": 9999}, f)

        # Initial prompt stored in session.json when session was created
        session_file = os.path.join(self.cli_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"title": "Initial raw prompt that should be overridden"}, f)

        mock_pane_pids.return_value = {1234}
        mock_ancestors.return_value = {1234, 9999}
        mock_client = MagicMock(spec=HerdrClient)

        # Pane has terminal_title updated by /title Behaviour Changes
        pane = {
            "terminal_title": "kiro: Behaviour Changes",
            "cwd": "/home/wxomi/work/repo/devel/auction",
        }
        agent = {"pane_id": "p1", "cwd": "/home/wxomi/work/repo/devel/auction"}

        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir):
            title = extract_kiro_title("p1", agent, mock_client, pane=pane)
            self.assertEqual(title, "Behaviour Changes")

    @patch("session_titles.extractors.kiro.pane_process_ids")
    @patch("session_titles.extractors.kiro.pid_ancestors")
    def test_extract_kiro_title_from_dashboard_meta(
        self, mock_ancestors: MagicMock, mock_pane_pids: MagicMock
    ) -> None:
        session_id = "session-with-meta"
        lock_file = os.path.join(self.cli_dir, f"{session_id}.lock")
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump({"pid": 9999}, f)

        session_file = os.path.join(self.cli_dir, f"{session_id}.json")
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({"title": "Old Prompt"}, f)

        # Sidecar dashboard-meta.json written by /sessions rename
        meta_file = os.path.join(self.temp_dir.name, "dashboard-meta.json")
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump({session_id: {"title": "Renamed in Sidecar"}}, f)

        mock_pane_pids.return_value = {1234}
        mock_ancestors.return_value = {1234, 9999}
        mock_client = MagicMock(spec=HerdrClient)

        with patch("session_titles.extractors.kiro.KIRO_SESSIONS", self.cli_dir), \
             patch("session_titles.extractors.kiro.KIRO_DASHBOARD_META", meta_file):
            title = extract_kiro_title("p1", {}, mock_client)
            self.assertEqual(title, "Renamed in Sidecar")

    @patch("session_titles.extractors.kiro.read_output")
    def test_extract_kiro_title_from_scrollback_rename(self, mock_read_output: MagicMock) -> None:
        mock_client = MagicMock(spec=HerdrClient)
        mock_read_output.return_value = (
            "Some prompt output\n"
            'Session renamed to "Clean Architecture RFC"\n'
            "Next prompt\n"
        )
        title = extract_kiro_title("p1", {}, mock_client)
        self.assertEqual(title, "Clean Architecture RFC")

    @patch("session_titles.extractors.kiro.read_output")
    def test_extract_kiro_title_from_tab_and_pane_labels(self, mock_read_output: MagicMock) -> None:
        mock_client = MagicMock(spec=HerdrClient)
        mock_read_output.return_value = ""

        # Explicit pane label
        pane = {"label": "Custom Pane Name"}
        title = extract_kiro_title("p1", {}, mock_client, pane=pane)
        self.assertEqual(title, "Custom Pane Name")

        # Explicit tab label
        title = extract_kiro_title("p1", {}, mock_client, tab_label="Custom Tab Name")
        self.assertEqual(title, "Custom Tab Name")

        # Numbered tab label (from sync_tabs)
        title = extract_kiro_title("p1", {}, mock_client, tab_label="61 · Synced Tab Title")
        self.assertEqual(title, "Synced Tab Title")


if __name__ == "__main__":
    unittest.main()
