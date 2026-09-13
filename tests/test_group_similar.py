import unittest
from unittest.mock import MagicMock
from session_titles.sync import get_pane_agent_kind, group_similar_agents_by_recency


class TestGroupSimilarAgents(unittest.TestCase):
    def test_get_pane_agent_kind(self):
        self.assertEqual(
            get_pane_agent_kind({"agent": "cursor"}, {}),
            "cursor",
        )
        self.assertEqual(
            get_pane_agent_kind({"pane_id": "p1"}, {"p1": {"agent": "agy"}}),
            "agy",
        )
        self.assertEqual(
            get_pane_agent_kind({"tokens": {"location": "devin · myrepo"}}, {}),
            "devin",
        )
        self.assertEqual(
            get_pane_agent_kind({"terminal_title": "claude-agent-run"}, {}),
            "claude",
        )

    def test_grouping_and_recency_order(self):
        client = MagicMock()
        client.is_available.return_value = True

        snap = {
            "workspaces": [
                {"workspace_id": "w_normal", "label": "devel"},
                {"workspace_id": "w_agents", "label": "devel-agents"},
            ],
            "tabs": [
                # Interleaved tabs in devel-agents
                {"tab_id": "t_cur1", "workspace_id": "w_agents"},
                {"tab_id": "t_agy1", "workspace_id": "w_agents"},
                {"tab_id": "t_cur2", "workspace_id": "w_agents"},
                {"tab_id": "t_dev1", "workspace_id": "w_agents"},
                {"tab_id": "t_agy2", "workspace_id": "w_agents"},
                # Tab in normal workspace
                {"tab_id": "t_norm", "workspace_id": "w_normal"},
            ],
            "panes": [
                # agy2 is currently focused (highest recency)
                {"pane_id": "p_agy2", "tab_id": "t_agy2", "agent": "agy", "focused": True, "revision": 10},
                {"pane_id": "p_agy1", "tab_id": "t_agy1", "agent": "agy", "focused": False, "revision": 5},
                # cur1 has revision 50
                {"pane_id": "p_cur1", "tab_id": "t_cur1", "agent": "cursor", "focused": False, "revision": 50},
                {"pane_id": "p_cur2", "tab_id": "t_cur2", "agent": "cursor", "focused": False, "revision": 20},
                # dev1 has revision 1
                {"pane_id": "p_dev1", "tab_id": "t_dev1", "agent": "devin", "focused": False, "revision": 1},
                {"pane_id": "p_norm", "tab_id": "t_norm", "focused": False, "revision": 100},
            ],
            "agents": [
                {"pane_id": "p_agy2", "agent": "agy"},
                {"pane_id": "p_agy1", "agent": "agy"},
                {"pane_id": "p_cur1", "agent": "cursor"},
                {"pane_id": "p_cur2", "agent": "cursor"},
                {"pane_id": "p_dev1", "agent": "devin"},
            ],
        }

        group_similar_agents_by_recency(client, snap=snap)

        # agy group is most recent (focused), so [t_agy2, t_agy1]
        # cursor group is next (revision 50 > 1), so [t_cur1, t_cur2]
        # devin group is last, so [t_dev1]
        # Expected order: t_agy2, t_agy1, t_cur1, t_cur2, t_dev1
        self.assertTrue(client.move_tab.called)
        # Verify t_norm in normal workspace was never touched
        moved_tabs = [call[0][0] for call in client.move_tab.call_args_list]
        self.assertNotIn("t_norm", moved_tabs)
        # Verify t_agy2 was moved to position 0
        client.move_tab.assert_any_call("t_agy2", 0)


if __name__ == "__main__":
    unittest.main()
