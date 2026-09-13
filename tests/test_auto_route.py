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
            "agents": [
                {"pane_id": "p1", "agent": "cursor", "workspace_id": "w_dev", "focused": False},
                {"pane_id": "p2", "agent": "cursor", "workspace_id": "w_dev_ag", "focused": True},
            ]
        }

        auto_route_agents(client, snap=snap)

        # p1 should move from w_dev to devel-agents (w_dev_ag)
        client.move_pane_to_workspace.assert_called_once_with("p1", "w_dev_ag", focus=False)

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


if __name__ == "__main__":
    unittest.main()
