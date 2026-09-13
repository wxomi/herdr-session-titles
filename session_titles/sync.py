from __future__ import annotations
import collections
import os
import sys
import time

from session_titles.config import (
    AGENTS_WORKSPACE_NAME,
    AUTO_ROUTE_AGENTS,
    GENERIC_NAMES,
    GROUP_SIMILAR_AGENTS,
    SOURCE,
    SYNC_TABS,
)
from session_titles.client import HerdrClient, run_herdr_cli
from session_titles.extractors import title_for_pane
from session_titles.sanitize import agent_cwd, format_agent_location


_pane_activity: dict[str, float] = {}
_pane_revisions: dict[str, int] = {}


def target_workspace_for_agent(
    agent: dict,
    workspaces_by_id: dict[str, dict],
) -> str | None:
    """Determine the paired agent workspace name for a given agent pane."""
    base_workspaces = {
        ws.get("label"): ws
        for ws in workspaces_by_id.values()
        if ws.get("label")
        and not ws.get("label").endswith("-agents")
        and ws.get("label") != "agents"
    }

    current_ws_id = agent.get("workspace_id")
    current_ws = workspaces_by_id.get(current_ws_id, {})
    current_label = current_ws.get("label") or ""

    # 1. If already in a valid paired agent workspace, leave it there
    if current_label.endswith("-agents"):
        base_name = current_label[:-7]
        if not base_workspaces or base_name in base_workspaces:
            return None

    # 2. If in a normal base workspace (e.g. 'devel' or '~'), pair with '{label}-agents'
    if current_label in base_workspaces:
        return f"{current_label}-agents"

    # 3. Fallback for orphan agent workspaces or legacy 'agents': match against base workspaces
    cwd = agent.get("cwd") or ""
    if cwd and base_workspaces:
        norm_cwd = os.path.normpath(cwd)
        path_parts = norm_cwd.split(os.sep)
        for base_name in base_workspaces:
            if base_name != "~" and base_name in path_parts:
                return f"{base_name}-agents"

        home = os.path.expanduser("~")
        if (norm_cwd == home or norm_cwd.startswith(home)) and "~" in base_workspaces:
            return "~-agents"

    tokens = agent.get("tokens") or {}
    loc = tokens.get("location") or ""
    if "·" in loc:
        proj = loc.split("·", 1)[1].strip()
        for base_name in base_workspaces:
            if base_name.lower() == proj.lower():
                return f"{base_name}-agents"

    if current_label and current_label != "agents":
        return f"{current_label}-agents"

    return None


def auto_route_agents(
    client: HerdrClient,
    snap: dict | None = None,
) -> None:
    """Ensure all active agent panes are routed to their paired <workspace>-agents workspace."""
    if not client.is_available():
        return

    snapshot = snap if snap is not None else client.snapshot()
    if not snapshot:
        return

    agents = snapshot.get("agents", [])
    if not agents:
        return

    workspaces = (
        (client.call("workspace.list").get("result") or {}).get("workspaces") or []
    )
    workspaces_by_id = {
        ws["workspace_id"]: ws for ws in workspaces if "workspace_id" in ws
    }
    workspaces_by_name = {
        (ws.get("label") or "").lower(): ws["workspace_id"]
        for ws in workspaces
        if "workspace_id" in ws
    }
    base_workspaces = {
        ws.get("label"): ws
        for ws in workspaces_by_id.values()
        if ws.get("label")
        and not ws.get("label").endswith("-agents")
        and ws.get("label") != "agents"
    }

    moved = False
    for agent in agents:
        pid = agent.get("pane_id")
        current_ws_id = agent.get("workspace_id")
        if not pid or not current_ws_id:
            continue

        target_name = target_workspace_for_agent(agent, workspaces_by_id)
        if not target_name:
            continue

        target_ws_id = workspaces_by_name.get(target_name.lower())
        if not target_ws_id:
            target_ws_id = client.get_or_create_workspace(target_name)
            if target_ws_id:
                workspaces_by_name[target_name.lower()] = target_ws_id

        if target_ws_id and current_ws_id != target_ws_id:
            is_focused = bool(agent.get("focused"))
            if client.move_pane_to_workspace(pid, target_ws_id, focus=is_focused):
                agent["workspace_id"] = target_ws_id
                moved = True

    # Clean up empty orphan agent workspaces if any exist
    if moved and base_workspaces:
        orphan_workspaces = [
            ws
            for ws in workspaces
            if ws.get("label", "").endswith("-agents")
            and ws.get("label")[:-7] not in base_workspaces
        ]
        if orphan_workspaces:
            fresh_snap = client.snapshot()
            panes = fresh_snap.get("panes", [])
            for ow in orphan_workspaces:
                ow_id = ow.get("workspace_id")
                if ow_id:
                    remaining = [p for p in panes if p.get("workspace_id") == ow_id]
                    if not remaining:
                        client.close_workspace(ow_id)



def get_pane_agent_kind(pane: dict, agents_by_pane: dict[str, dict]) -> str:
    """Determine the normalized agent kind (e.g. 'cursor', 'agy', 'devin')."""
    ag_obj = agents_by_pane.get(pane.get("pane_id", ""), {})
    agent = ag_obj.get("agent") or pane.get("agent")
    if agent and isinstance(agent, str) and agent.lower() != "unknown":
        return agent.lower().strip()

    tokens = pane.get("tokens") or ag_obj.get("tokens") or {}
    loc = tokens.get("location") or ""
    if "·" in loc:
        prefix = loc.split("·", 1)[0].strip().lower()
        if prefix in GENERIC_NAMES or prefix in (
            "devin",
            "cursor",
            "agy",
            "kiro",
            "claude",
            "codex",
        ):
            return prefix

    title = (pane.get("title") or pane.get("terminal_title") or "").lower()
    for name in ("cursor", "devin", "agy", "kiro", "claude", "codex"):
        if name in title:
            return name

    return "agent"


def group_similar_agents_by_recency(
    client: HerdrClient,
    snap: dict | None = None,
) -> None:
    """Group similar agents together in agent workspaces, sorted by recency."""
    if not client.is_available():
        return

    snapshot = snap if snap is not None else client.snapshot()
    if not snapshot:
        return

    now = time.time()
    panes = [p for p in snapshot.get("panes", []) if isinstance(p, dict)]
    tabs = [t for t in snapshot.get("tabs", []) if isinstance(t, dict)]
    workspaces = snapshot.get("workspaces", [])
    agents = snapshot.get("agents", [])

    agents_by_pane = {
        a["pane_id"]: a for a in agents if isinstance(a, dict) and "pane_id" in a
    }

    for p in panes:
        pid = p.get("pane_id")
        if not pid:
            continue
        rev = p.get("revision", 0)
        is_focused = bool(p.get("focused"))

        if pid not in _pane_activity:
            _pane_activity[pid] = now - 10000.0 + (rev if isinstance(rev, int) else 0)
            _pane_revisions[pid] = rev if isinstance(rev, int) else 0

        if is_focused:
            _pane_activity[pid] = now
        elif isinstance(rev, int) and rev > _pane_revisions.get(pid, 0):
            _pane_activity[pid] = now
            _pane_revisions[pid] = rev

    tab_panes: dict[str, list[dict]] = collections.defaultdict(list)
    for p in panes:
        tid = p.get("tab_id")
        if tid:
            tab_panes[tid].append(p)

    def tab_recency(tab_id: str) -> float:
        return max(
            (
                _pane_activity.get(p.get("pane_id", ""), 0.0)
                for p in tab_panes.get(tab_id, [])
            ),
            default=0.0,
        )

    def tab_agent_kind(tab_id: str) -> str:
        for p in tab_panes.get(tab_id, []):
            kind = get_pane_agent_kind(p, agents_by_pane)
            if kind:
                return kind
        return "agent"

    agent_workspaces = {
        ws.get("workspace_id")
        for ws in workspaces
        if ws.get("label", "").endswith("-agents") or ws.get("label") == "agents"
    }

    workspace_tabs: dict[str, list[dict]] = collections.defaultdict(list)
    for t in tabs:
        tid = t.get("tab_id")
        ws_id = t.get("workspace_id")
        if tid and ws_id in agent_workspaces:
            workspace_tabs[ws_id].append(t)

    for ws_id, ws_tabs in workspace_tabs.items():
        if len(ws_tabs) <= 1:
            continue

        groups: dict[str, list[dict]] = collections.defaultdict(list)
        for t in ws_tabs:
            kind = tab_agent_kind(t["tab_id"])
            groups[kind].append(t)

        for kind, kind_tabs in groups.items():
            kind_tabs.sort(key=lambda t: tab_recency(t["tab_id"]), reverse=True)

        sorted_kinds = sorted(
            groups.keys(),
            key=lambda k: max(
                (tab_recency(t["tab_id"]) for t in groups[k]), default=0.0
            ),
            reverse=True,
        )

        desired_tabs: list[dict] = []
        for k in sorted_kinds:
            desired_tabs.extend(groups[k])

        current_ids = [t["tab_id"] for t in ws_tabs]
        desired_ids = [t["tab_id"] for t in desired_tabs]

        if current_ids != desired_ids:
            ordered_ids = list(current_ids)
            for target_idx, desired_id in enumerate(desired_ids):
                curr_idx = ordered_ids.index(desired_id)
                if curr_idx != target_idx:
                    client.move_tab(desired_id, target_idx)
                    ordered_ids.pop(curr_idx)
                    ordered_ids.insert(target_idx, desired_id)


def tab_labels(client: HerdrClient) -> dict[str, str]:
    """Retrieve mapping of tab IDs to their current labels."""
    if client.is_available():
        snap = client.snapshot()
        if snap:
            return {
                t["tab_id"]: t.get("label", "")
                for t in snap.get("tabs", [])
                if isinstance(t, dict) and "tab_id" in t
            }
    tabs = (run_herdr_cli("tab", "list").get("result") or {}).get("tabs") or []
    return {
        t["tab_id"]: t["label"]
        for t in tabs
        if t.get("tab_id") and isinstance(t.get("label"), str)
    }


def report_tokens(
    pane_id: str,
    updates: dict[str, str | None],
    previous: dict[str, str | None],
    client: HerdrClient,
) -> None:
    """Report updated metadata tokens to Herdr only if they have changed."""
    changed = False
    for name, value in updates.items():
        if value != previous.get(name):
            changed = True
            break
    if not changed:
        return

    title = updates.get("session")
    if client.is_available():
        if client.report_metadata(
            pane_id, SOURCE, updates, title=title, display_agent=title
        ):
            return

    # Fallback to CLI
    args = ["pane", "report-metadata", pane_id, "--source", SOURCE]
    if title:
        args.extend(["--title", title, "--display-agent", title])
    for name, value in updates.items():
        if value:
            args.extend(["--token", f"{name}={value}"])
        else:
            args.extend(["--clear-token", name])
    run_herdr_cli(*args)


def sync_all(
    only_pane: str | None = None,
    sync_tabs: bool | None = None,
    auto_route: bool | None = None,
    group_similar: bool | None = None,
    client: HerdrClient | None = None,
) -> None:
    """Scan all active panes, resolve session titles, and update sidebar/tabs."""
    c = client or HerdrClient()
    do_sync_tabs = (
        SYNC_TABS
        if sync_tabs is None
        else sync_tabs
        or ("--sync-tabs" in sys.argv)
    )
    do_auto_route = (
        AUTO_ROUTE_AGENTS
        if auto_route is None
        else auto_route
        or ("--auto-route" in sys.argv)
    )
    do_group_similar = (
        GROUP_SIMILAR_AGENTS
        if group_similar is None
        else group_similar
        or ("--group-similar" in sys.argv)
    )

    snap = c.snapshot() if c.is_available() else {}
    if snap:
        tabs = {
            t["tab_id"]: t.get("label", "")
            for t in snap.get("tabs", [])
            if isinstance(t, dict) and "tab_id" in t
        }
        tab_numbers = {
            t["tab_id"]: t.get("number")
            for t in snap.get("tabs", [])
            if isinstance(t, dict) and "tab_id" in t and t.get("number") is not None
        }
        panes_by_id = {
            p["pane_id"]: p
            for p in snap.get("panes", [])
            if isinstance(p, dict) and "pane_id" in p
        }
        agents = snap.get("agents", [])
    else:
        tabs = tab_labels(c)
        tab_numbers = {}
        panes_by_id = {}
        agents = []
        panes = (run_herdr_cli("pane", "list").get("result") or {}).get("panes") or []
        for p in panes:
            pid = p.get("pane_id")
            if pid and p.get("agent"):
                ag = (
                    (run_herdr_cli("agent", "get", pid).get("result") or {}).get("agent")
                    or {}
                )
                agents.append(ag)
                panes_by_id[pid] = p

    for agent in agents:
        pane_id = agent.get("pane_id")
        if not pane_id or (only_pane and pane_id != only_pane):
            continue
        pane = panes_by_id.get(pane_id) or agent
        tab_id = agent.get("tab_id") or pane.get("tab_id", "")
        tab_label = tabs.get(tab_id)
        title = title_for_pane(pane, agent, tab_label, c)
        location = format_agent_location(
            pane.get("agent") or agent.get("agent"),
            agent_cwd(pane, agent),
        )
        tokens = agent.get("tokens") or {}
        report_tokens(
            pane_id,
            {"session": title, "location": location, "path": None},
            {
                "session": (
                    tokens.get("session")
                    if isinstance(tokens.get("session"), str)
                    else None
                ),
                "location": (
                    tokens.get("location")
                    if isinstance(tokens.get("location"), str)
                    else None
                ),
                "path": (
                    tokens.get("path")
                    if isinstance(tokens.get("path"), str)
                    else None
                ),
            },
            c,
        )
        if do_sync_tabs and tab_id and title:
            num = tab_numbers.get(tab_id)
            desired_tab = f"{num} · {title}" if num else title
            if tab_label != desired_tab:
                if c.is_available():
                    c.rename_tab(tab_id, desired_tab)
                else:
                    run_herdr_cli("tab", "rename", tab_id, desired_tab)

    if do_auto_route and c.is_available() and not only_pane:
        auto_route_agents(c, snap)

    if do_group_similar and c.is_available() and not only_pane:
        group_similar_agents_by_recency(c, snap)
