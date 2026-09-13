"""Command line interface entrypoint for session_titles."""

from __future__ import annotations

import sys

from session_titles.config import AUTO_ROUTE_AGENTS, SYNC_TABS
from session_titles.sync import sync_all
from session_titles.watcher import watch


def main(argv: list[str] | None = None) -> int:
    """CLI entry point dispatching between one-shot sync and background watcher."""
    args = argv if argv is not None else sys.argv

    if "--help" in args or "-h" in args:
        print(
            "Usage: python3 -m session_titles [--watch] [--pane PANE_ID] "
            "[--sync-tabs] [--auto-route] [--no-auto-route]"
        )
        return 0

    sync_tabs = "--sync-tabs" in args or SYNC_TABS
    auto_route = "--no-auto-route" not in args and (
        "--auto-route" in args or AUTO_ROUTE_AGENTS
    )
    if "--watch" in args:
        return watch(sync_tabs=sync_tabs, auto_route=auto_route)

    only_pane = None
    if len(args) >= 3 and args[1] == "--pane":
        only_pane = args[2]
        if only_pane.startswith("$"):
            only_pane = None

    sync_all(only_pane=only_pane, sync_tabs=sync_tabs, auto_route=auto_route)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
