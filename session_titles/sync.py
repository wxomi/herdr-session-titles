"""Core synchronization logic between Herdr sessions and UI tokens."""

from __future__ import annotations

import sys

from session_titles.config import SOURCE, SYNC_TABS
from session_titles.client import HerdrClient, run_herdr_cli
from session_titles.extractors import title_for_pane
from session_titles.sanitize import agent_cwd, format_agent_location


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
