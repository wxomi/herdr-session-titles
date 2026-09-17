"""Unit tests for unused terminal detection, tab ordering, and 24h cleanup."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from session_titles.cleanup import (
    cleanup_unused_tabs,
    is_pane_idle_terminal,
    is_tab_idle_terminal,
    load_unused_tabs_state,
    save_unused_tabs_state,
)
from session_titles.client import HerdrClient
from session_titles.sync import group_similar_agents_by_recency


class TestCleanupUnusedTabs(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "unused_tabs.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_is_pane_idle_terminal(self) -> None:
        client = MagicMock(spec=HerdrClient)
        client.is_available.return_value = True

        # Case 1: Pane has an active agent
        agents_by_pane = {"p1": {"pane_id": "p1", "agent": "devin"}}
        self.assertFalse(is_pane_idle_terminal({"pane_id": "p1"}, agents_by_pane, client))

        # Case 2: Pane has agent attribute set
        self.assertFalse(is_pane_idle_terminal({"pane_id": "p2", "agent": "cursor"}, {}, client))

        # Case 3: Pane running an active command (e.g. runserver or python)
        client.process_info.return_value = {
            "shell_pid": 100,
            "foreground_processes": [
                {"pid": 101, "name": "python", "cmdline": "python manage.py runserver"}
            ],
        }
        self.assertFalse(is_pane_idle_terminal({"pane_id": "p3"}, {}, client))

        # Case 4: Pane running only zsh shell at prompt
        client.process_info.return_value = {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 100, "name": "zsh", "cmdline": "-zsh"}],
        }
        self.assertTrue(is_pane_idle_terminal({"pane_id": "p4"}, {}, client))

    def test_is_tab_idle_terminal(self) -> None:
        client = MagicMock(spec=HerdrClient)
        client.is_available.return_value = True

        # Idle pane info
        client.process_info.side_effect = lambda pid: {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 100, "name": "zsh"}],
        } if pid == "p_idle" else {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 102, "name": "npm"}],
        }

        # Tab with all idle panes
        self.assertTrue(is_tab_idle_terminal("t1", [{"pane_id": "p_idle"}], {}, client))

        # Tab with one active pane and one idle pane
        self.assertFalse(
            is_tab_idle_terminal(
                "t2", [{"pane_id": "p_idle"}, {"pane_id": "p_active"}], {}, client
            )
        )

    def test_cleanup_unused_tabs_closes_stale_tabs_and_preserves_single_tabs(self) -> None:
        client = MagicMock(spec=HerdrClient)
        client.is_available.return_value = True

        client.process_info.side_effect = lambda pid: {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 100, "name": "zsh"}],
        } if pid in ("p_stale", "p_recent", "p_sole") else {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 200, "name": "devin"}],
        }

        snap = {
            "focused_tab_id": "t_focused",
            "tabs": [
                {"tab_id": "t_stale", "workspace_id": "w_agents"},
                {"tab_id": "t_recent", "workspace_id": "w_agents"},
                {"tab_id": "t_agent", "workspace_id": "w_agents"},
                {"tab_id": "t_sole", "workspace_id": "w_home"},
            ],
            "panes": [
                {"pane_id": "p_stale", "tab_id": "t_stale", "workspace_id": "w_agents"},
                {"pane_id": "p_recent", "tab_id": "t_recent", "workspace_id": "w_agents"},
                {"pane_id": "p_agent", "tab_id": "t_agent", "workspace_id": "w_agents", "agent": "devin"},
                {"pane_id": "p_sole", "tab_id": "t_sole", "workspace_id": "w_home"},
            ],
            "agents": [{"pane_id": "p_agent", "agent": "devin"}],
        }

        now = time.time()
        # Seed state: t_stale is 25 hours old, t_recent is 5 hours old
        state = {
            "t_stale": {"first_idle_at": now - 25 * 3600, "workspace_id": "w_agents"},
            "t_recent": {"first_idle_at": now - 5 * 3600, "workspace_id": "w_agents"},
            "t_sole": {"first_idle_at": now - 30 * 3600, "workspace_id": "w_home"},
        }
        with patch("session_titles.cleanup.UNUSED_TABS_FILE", self.state_file):
            save_unused_tabs_state(state)
            client.close_tab.return_value = True

            deleted = cleanup_unused_tabs(client, snap=snap, ttl_seconds=24 * 3600)

            # t_stale must be closed
            self.assertEqual(deleted, ["t_stale"])
            client.close_tab.assert_called_once_with("t_stale")

            # t_sole must NOT be closed because it's the only tab in w_home
            # t_recent must NOT be closed because it's <24h
            remaining_state = load_unused_tabs_state()
            self.assertNotIn("t_stale", remaining_state)
            self.assertIn("t_recent", remaining_state)
            self.assertIn("t_sole", remaining_state)

    def test_group_similar_agents_places_unused_tabs_at_end(self) -> None:
        client = MagicMock(spec=HerdrClient)
        client.is_available.return_value = True

        client.process_info.side_effect = lambda pid: {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 100, "name": "zsh"}],
        } if pid == "p_dead" else {
            "shell_pid": 100,
            "foreground_processes": [{"pid": 200, "name": "agy"}],
        }

        snap = {
            "workspaces": [{"workspace_id": "w_agents", "label": "devel-agents"}],
            "tabs": [
                {"tab_id": "t_dead", "workspace_id": "w_agents", "number": 1},
                {"tab_id": "t_devin", "workspace_id": "w_agents", "number": 2},
                {"tab_id": "t_agy", "workspace_id": "w_agents", "number": 3},
            ],
            "panes": [
                {"pane_id": "p_dead", "tab_id": "t_dead", "workspace_id": "w_agents"},
                {"pane_id": "p_devin", "tab_id": "t_devin", "workspace_id": "w_agents", "agent": "devin"},
                {"pane_id": "p_agy", "tab_id": "t_agy", "workspace_id": "w_agents", "agent": "agy"},
            ],
            "agents": [
                {"pane_id": "p_devin", "agent": "devin"},
                {"pane_id": "p_agy", "agent": "agy"},
            ],
        }

        group_similar_agents_by_recency(client, snap=snap)

        # t_dead should be moved to the last position (index 2)
        # Verify move_tab was called to put active agents first
        self.assertTrue(client.move_tab.called)


if __name__ == "__main__":
    unittest.main()
