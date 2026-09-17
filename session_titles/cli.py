"""Command line interface entrypoint for session_titles."""

from __future__ import annotations

import sys
import time

from session_titles.config import (
    AUTO_ROUTE_AGENTS,
    CLEANUP_UNUSED_TABS,
    GROUP_SIMILAR_AGENTS,
    SYNC_TABS,
)
from session_titles.sync import sync_all
from session_titles.watcher import get_watcher_status, stop_watcher, watch


def main(argv: list[str] | None = None) -> int:
    """CLI entry point dispatching between one-shot sync and background watcher."""
    args = argv if argv is not None else sys.argv

    if "--help" in args or "-h" in args:
        print(
            "Usage: python3 -m session_titles [--watch] [--restart] [--stop] [--status]\n"
            "                                 [--pane PANE_ID] [--sync-tabs]\n"
            "                                 [--auto-route] [--no-auto-route]\n"
            "                                 [--group-similar] [--no-group-similar]\n"
            "                                 [--cleanup-unused] [--no-cleanup-unused]"
        )
        return 0

    if "--status" in args:
        status = get_watcher_status()
        if status["running"]:
            print(f"Watcher is running (PID {status['pid']}).")
        else:
            print("Watcher is not running.")
        return 0

    if "--stop" in args:
        stop_watcher()
        print("Watcher stopped.")
        return 0

    sync_tabs = "--sync-tabs" in args or SYNC_TABS
    auto_route = "--no-auto-route" not in args and (
        "--auto-route" in args or AUTO_ROUTE_AGENTS
    )
    group_similar = "--no-group-similar" not in args and (
        "--group-similar" in args or GROUP_SIMILAR_AGENTS
    )
    cleanup_unused = "--no-cleanup-unused" not in args and (
        "--cleanup-unused" in args or CLEANUP_UNUSED_TABS
    )

    if "--restart" in args:
        stop_watcher()
        time.sleep(0.3)
        return watch(
            sync_tabs=sync_tabs,
            auto_route=auto_route,
            group_similar=group_similar,
            cleanup_unused=cleanup_unused,
        )

    if "--watch" in args:
        return watch(
            sync_tabs=sync_tabs,
            auto_route=auto_route,
            group_similar=group_similar,
            cleanup_unused=cleanup_unused,
        )

    only_pane = None
    if len(args) >= 3 and args[1] == "--pane":
        only_pane = args[2]
        if only_pane.startswith("$"):
            only_pane = None

    sync_all(
        only_pane=only_pane,
        sync_tabs=sync_tabs,
        auto_route=auto_route,
        group_similar=group_similar,
        cleanup_unused=cleanup_unused,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
