"""Unit tests for Devin session title extraction."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from session_titles.extractors.devin import (
    extract_devin_rename,
    pick_newest_lock_session,
    resolve_devin_live_title,
)


class PickNewestLockSessionTests(unittest.TestCase):
    def test_same_pid_uses_newest_lock_not_an_older_session(self) -> None:
        with tempfile.TemporaryDirectory() as lock_dir:
            older = os.path.join(lock_dir, "butternut-crowd.lock")
            newer = os.path.join(lock_dir, "miniature-server.lock")
            with open(older, "w", encoding="utf-8") as handle:
                handle.write("70547\n")
            os.utime(older, (1_700_000_000, 1_700_000_000))
            time.sleep(0.02)
            with open(newer, "w", encoding="utf-8") as handle:
                handle.write("70547\n")
            with open(
                os.path.join(lock_dir, "unrelated.lock"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write("1\n")

            self.assertEqual(
                pick_newest_lock_session({70547}, lock_dir),
                "miniature-server",
            )


class ExtractDevinRenameTests(unittest.TestCase):
    def test_uses_confirmed_rename_not_the_previous_title(self) -> None:
        output = """
> /fork
✔ Session forked
> /rename-session Employer matching rule
✔ Session renamed to Employer matching rule
"""
        self.assertEqual(
            extract_devin_rename(output),
            "Employer matching rule",
        )

    def test_uses_the_latest_rename_in_the_buffer(self) -> None:
        output = """
> /rename-session matt pocock
✔ Session renamed to matt pocock
> /rename-session Employer matching rule
✔ Session renamed to Employer matching rule
"""
        self.assertEqual(
            extract_devin_rename(output),
            "Employer matching rule",
        )

    def test_ignores_rename_from_before_clear(self) -> None:
        output = """
> /rename-session timeline
✔ Session renamed to timeline
> /clear
✓ Started new session
> Ask Devin to build features, fix bugs, or work on your code
"""
        self.assertIsNone(extract_devin_rename(output))

    def test_keeps_rename_after_clear(self) -> None:
        output = """
> /rename-session timeline
✔ Session renamed to timeline
✓ Started new session
> /rename-session Main Blockers T35299
✔ Session renamed to Main Blockers T35299
"""
        self.assertEqual(
            extract_devin_rename(output),
            "Main Blockers T35299",
        )


class ResolveDevinLiveTitleTests(unittest.TestCase):
    def test_clear_without_title_is_new_session(self) -> None:
        self.assertEqual(
            resolve_devin_live_title(
                session_id="sour-haddock",
                db_title=None,
                renamed=None,
            ),
            "New session",
        )

    def test_lock_db_title_wins(self) -> None:
        self.assertEqual(
            resolve_devin_live_title(
                session_id="axiomatic-reaction",
                db_title="timeline",
                renamed=None,
            ),
            "timeline",
        )

    def test_rename_used_when_new_lock_has_no_db_row(self) -> None:
        self.assertEqual(
            resolve_devin_live_title(
                session_id="opposite-marmoset",
                db_title=None,
                renamed="Main Blockers T35299",
            ),
            "Main Blockers T35299",
        )


if __name__ == "__main__":
    unittest.main()
