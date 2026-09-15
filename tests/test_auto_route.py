import unittest
from unittest.mock import MagicMock
from session_titles.sync import auto_route_agents, target_workspace_for_agent


class TestAutoRouteAgents(unittest.TestCase):
    def test_target_workspace_resolution(self):
        workspaces_by_id = {
            "w_dev": {"label": "devel", "workspace_id": "w_dev"},
            "w_auc": {"label": "auction", "workspace_id": "w_auc"},
            "w_dev_agents": {"label": "devel-agents", "workspace_id": "w_dev_agents"},
        }

        # Agent in normal workspace 'devel' -> 'devel-agents'
        ag1 = {"pane_id": "p1", "workspace_id": "w_dev"}
        self.assertEqual(target_workspace_for_agent(ag1, workspaces_by_id), "devel-agents")

        # Agent already in 'devel-agents' -> None (no move)
        ag2 = {"pane_id": "p2", "workspace_id": "w_dev_agents"}
        self.assertIsNone(target_workspace_for_agent(ag2, workspaces_by_id))

        # Agent in 'auction' -> 'auction-agents'
        ag3 = {"pane_id": "p3", "workspace_id": "w_auc"}
        self.assertEqual(target_workspace_for_agent(ag3, workspaces_by_id), "auction-agents")

        # Regression: Agent in '~-agents' when '~' is closed must NEVER chain to '~-agents-agents'
        workspaces_without_home = {
            "w_dev": {"label": "devel", "workspace_id": "w_dev"},
            "w_home_agents": {"label": "~-agents", "workspace_id": "w_home_agents"},
            "w_dev_agents": {"label": "devel-agents", "workspace_id": "w_dev_agents"},
        }
        ag_home_agents = {"pane_id": "p4", "workspace_id": "w_home_agents"}
        self.assertIsNone(target_workspace_for_agent(ag_home_agents, workspaces_without_home))

    def test_auto_route_moves_to_paired_workspace(self):
        client = MagicMock()
        client.is_available.return_value = True
        client.call.return_value = {
            "result": {
                "workspaces": [
                    {"label": "devel", "workspace_id": "w_dev"},
                    {"label": "devel-agents", "workspace_id": "w_dev_ag"},
                ]
            }
        }
        client.get_or_create_workspace.side_effect = lambda name: f"id_{name}"

        snap = {
            "panes": [
                {"pane_id": "p1", "workspace_id": "w_dev"},
                {"pane_id": "p_shell", "workspace_id": "w_dev"},
            ],
            "agents": [
                {"pane_id": "p1", "agent": "cursor", "workspace_id": "w_dev", "focused": False},
                {"pane_id": "p2", "agent": "cursor", "workspace_id": "w_dev_ag", "focused": True},
            ]
        }

        auto_route_agents(client, snap=snap)

        # p1 should move from w_dev to devel-agents (w_dev_ag)
        client.move_pane_to_workspace.assert_called_once_with("p1", "w_dev_ag", focus=False)
        # Because w_dev still has p_shell, create_tab is not needed
        client.create_tab.assert_not_called()

    def test_auto_route_preserves_base_workspace_when_only_one_pane(self):
        client = MagicMock()
        client.is_available.return_value = True
        client.call.return_value = {
            "result": {
                "workspaces": [
                    {"label": "~", "workspace_id": "w_home", "pane_count": 1},
                    {"label": "~-agents", "workspace_id": "w_home_ag"},
                ]
            }
        }
        client.get_or_create_workspace.side_effect = lambda name: f"id_{name}"

        snap = {
            "panes": [
                {"pane_id": "p_only", "workspace_id": "w_home", "cwd": "/Users/test"},
            ],
            "agents": [
                {"pane_id": "p_only", "agent": "agy", "workspace_id": "w_home", "cwd": "/Users/test", "focused": True},
            ]
        }

        auto_route_agents(client, snap=snap)

        # Must spawn replacement shell before moving so Herdr doesn't delete ~
        client.create_tab.assert_called_once_with("w_home", cwd="/Users/test", focus=False)
        client.move_pane_to_workspace.assert_called_once_with("p_only", "w_home_ag", focus=True)

    def test_auto_route_restores_home_workspace_if_missing(self):
        client = MagicMock()
        client.is_available.return_value = True
        client.call.return_value = {
            "result": {
                "workspaces": [
                    {"label": "devel", "workspace_id": "w_dev"},
                    {"label": "~-agents", "workspace_id": "w_home_ag"},
                ]
            }
        }
        snap = {"agents": []}

        auto_route_agents(client, snap=snap)

        # workspace.create must be called for ~
        client.call.assert_any_call(
            "workspace.create",
            {"label": "~", "cwd": unittest.mock.ANY, "no_focus": True},
        )

    def test_orphan_agent_workspace_resolution(self):
        workspaces_by_id = {
            "w_dev": {"label": "devel", "workspace_id": "w_dev"},
            "w_home": {"label": "~", "workspace_id": "w_home"},
            "w_dev_agents": {"label": "devel-agents", "workspace_id": "w_dev_agents"},
            "w_auc_agents": {"label": "auction-agents", "workspace_id": "w_auc_agents"},
        }

        # Agent in orphan workspace 'auction-agents' with cwd in devel/auction
        ag_orphan = {
            "pane_id": "p_auc",
            "workspace_id": "w_auc_agents",
            "cwd": "/Users/test/Workspace/devel/auction",
        }
        self.assertEqual(
            target_workspace_for_agent(ag_orphan, workspaces_by_id),
            "devel-agents",
        )

        # Agent in ~ -> ~-agents
        ag_home = {"pane_id": "p_home", "workspace_id": "w_home"}
        self.assertEqual(
            target_workspace_for_agent(ag_home, workspaces_by_id),
            "~-agents",
        )

    def test_client_cleans_up_initial_tab_on_first_move(self):
        from session_titles.client import HerdrClient

        client = HerdrClient(sock_path=None)
        client.is_available = MagicMock(return_value=True)

        # Simulate workspace.list (empty) and workspace.create
        client.call = MagicMock(side_effect=[
            {"result": {"workspaces": []}},  # workspace.list
            {"result": {"workspace": {"workspace_id": "w_new", "active_tab_id": "t_init"}}},  # workspace.create
            {"result": {"type": "ok"}},  # pane.move
            {"result": {"type": "ok"}},  # tab.close
        ])

        ws_id = client.get_or_create_workspace("devel-agents")
        self.assertEqual(ws_id, "w_new")
        self.assertEqual(client._new_workspace_initial_tabs.get("w_new"), "t_init")

        moved = client.move_pane_to_workspace("p1", "w_new")
        self.assertTrue(moved)
        self.assertNotIn("w_new", client._new_workspace_initial_tabs)

    def test_move_pane_switches_workspace_when_focused(self):
        from session_titles.client import HerdrClient

        client = HerdrClient(sock_path=None)
        client.is_available = MagicMock(return_value=True)
        client.call = MagicMock(side_effect=[
            {
                "result": {
                    "type": "pane_move",
                    "move_result": {
                        "changed": True,
                        "created_tab": {"tab_id": "t_new_agent"},
                    },
                }
            },  # pane.move
            {"result": {"type": "workspace_info"}},  # workspace.focus
            {"result": {"type": "tab_info"}},  # tab.focus
        ])

        moved = client.move_pane_to_workspace("p1", "w_agents", focus=True)
        self.assertTrue(moved)
        client.call.assert_any_call("workspace.focus", {"workspace_id": "w_agents"})
        client.call.assert_any_call("tab.focus", {"tab_id": "t_new_agent"})


if __name__ == "__main__":
    unittest.main()
