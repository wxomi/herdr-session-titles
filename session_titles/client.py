"""Direct Unix domain socket client for Herdr JSON-RPC."""

from __future__ import annotations

import json
import os
import socket
import subprocess

from session_titles.config import HERDR, SOCKET_PATH


class HerdrClient:
    """Direct Unix domain socket client for Herdr JSON-RPC."""

    def __init__(self, sock_path: str | None = None):
        self.sock_path = sock_path or SOCKET_PATH
        self._new_workspace_initial_tabs: dict[str, str] = {}

    def is_available(self) -> bool:
        return bool(self.sock_path and os.path.exists(self.sock_path))

    def call(self, method: str, params: dict | None = None, req_id: str = "p") -> dict:
        if not self.is_available():
            return {}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.sock_path)
                payload = (
                    json.dumps({"id": req_id, "method": method, "params": params or {}})
                    + "\n"
                )
                s.sendall(payload.encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in chunk:
                        break
                    if not buf:
                        return {}
                return json.loads(buf.decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def snapshot(self) -> dict:
        res = self.call("session.snapshot")
        return (res.get("result") or {}).get("snapshot") or {}

    def read_pane(
        self, pane_id: str, lines: int = 250, source: str = "recent_unwrapped"
    ) -> str:
        res = self.call(
            "pane.read", {"pane_id": pane_id, "source": source, "lines": lines}
        )
        read_obj = (res.get("result") or {}).get("read") or {}
        return read_obj.get("text", "")

    def process_info(self, pane_id: str) -> dict:
        res = self.call("pane.process_info", {"pane_id": pane_id})
        return (res.get("result") or {}).get("process_info") or {}

    def report_metadata(
        self,
        pane_id: str,
        source: str,
        tokens: dict[str, str | None],
        title: str | None = None,
        display_agent: str | None = None,
    ) -> bool:
        params: dict = {"pane_id": pane_id, "source": source, "tokens": tokens}
        if title:
            params["title"] = title
        if display_agent:
            params["display_agent"] = display_agent
        res = self.call("pane.report_metadata", params)
        return "result" in res

    def create_tab(
        self,
        workspace_id: str,
        cwd: str | None = None,
        focus: bool = False,
    ) -> str | None:
        params: dict = {"workspace_id": workspace_id, "no_focus": not focus}
        if cwd:
            params["cwd"] = cwd
        res = self.call("tab.create", params)
        tab = (res.get("result") or {}).get("tab") or {}
        return tab.get("tab_id")

    def rename_tab(self, tab_id: str, label: str) -> bool:
        res = self.call("tab.rename", {"tab_id": tab_id, "label": label})
        return "result" in res

    def move_tab(self, tab_id: str, insert_index: int) -> bool:
        res = self.call("tab.move", {"tab_id": tab_id, "insert_index": insert_index})
        return "result" in res

    def close_tab(self, tab_id: str) -> bool:
        res = self.call("tab.close", {"tab_id": tab_id})
        return "result" in res

    def close_workspace(self, workspace_id: str) -> bool:
        res = self.call("workspace.close", {"workspace_id": workspace_id})
        return "result" in res

    def focus_workspace(self, workspace_id: str) -> bool:
        res = self.call("workspace.focus", {"workspace_id": workspace_id})
        return "result" in res

    def focus_tab(self, tab_id: str) -> bool:
        res = self.call("tab.focus", {"tab_id": tab_id})
        return "result" in res

    def move_pane_to_workspace(
        self, pane_id: str, workspace_id: str, focus: bool = False
    ) -> bool:
        res = self.call(
            "pane.move",
            {
                "pane_id": pane_id,
                "destination": {"type": "new_tab", "workspace_id": workspace_id},
                "focus": focus,
            },
        )
        ok = "result" in res
        if ok:
            init_tab = self._new_workspace_initial_tabs.pop(workspace_id, None)
            if init_tab:
                self.close_tab(init_tab)
            if focus:
                self.focus_workspace(workspace_id)
                move_res = (res.get("result") or {}).get("move_result") or {}
                created_tab = move_res.get("created_tab") or {}
                new_tab_id = created_tab.get("tab_id")
                if new_tab_id:
                    self.focus_tab(new_tab_id)
        return ok

    def get_or_create_workspace(self, name: str) -> str | None:
        res = self.call("workspace.list")
        workspaces = (res.get("result") or {}).get("workspaces") or []
        for ws in workspaces:
            if (ws.get("label") or "").lower() == name.lower():
                return ws.get("workspace_id")
        created = self.call("workspace.create", {"label": name, "no_focus": True})
        ws_info = (created.get("result") or {}).get("workspace") or {}
        ws_id = ws_info.get("workspace_id")
        if ws_id:
            tab_info = (created.get("result") or {}).get("tab") or {}
            init_tab = tab_info.get("tab_id") or ws_info.get("active_tab_id")
            if init_tab:
                self._new_workspace_initial_tabs[ws_id] = init_tab
        return ws_id


def run_herdr_cli(*args: str) -> dict:
    """Fallback CLI runner for when Herdr socket is temporarily unavailable."""
    proc = subprocess.run(
        [HERDR, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def read_output(pane_id: str, client: HerdrClient, lines: int = 250) -> str:
    """Read recent terminal output using socket first, CLI fallback second."""
    if client.is_available():
        text = client.read_pane(pane_id, lines=lines)
        if text:
            return text
    proc = subprocess.run(
        [
            HERDR,
            "pane",
            "read",
            pane_id,
            "--source",
            "recent-unwrapped",
            "--lines",
            str(lines),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout or ""
