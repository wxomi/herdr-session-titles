"""Unit tests for text sanitization, prompt cleaning, and path formatting."""

from __future__ import annotations

import os
import unittest

from session_titles.sanitize import (
    clean_prompt_for_title,
    format_agent_location,
    format_agent_path,
    meaningful_terminal_title,
    sanitize,
    strip_leading_file_paths,
)


class PromptCleaningTests(unittest.TestCase):
    def test_strip_leading_image_path_extracts_actual_prompt(self) -> None:
        raw = (
            "/Users/wxomi/Desktop/Snapzy/Snapzy_2026-09-10_22-49-32_248.png "
            "cursor is working but it's not showing in left bar"
        )
        self.assertEqual(
            clean_prompt_for_title(raw),
            "cursor is working but it's not showing in left bar",
        )

    def test_strip_leading_document_path_extracts_actual_prompt(self) -> None:
        raw = (
            "private/tmp/auction-handoff.XhiI0d/T45399-D39466-handoff.md "
            "can you also check which is best approch"
        )
        self.assertEqual(
            clean_prompt_for_title(raw),
            "can you also check which is best approch",
        )

    def test_strip_relative_file_only_uses_basename(self) -> None:
        raw = "private/tmp/auction-handoff.XhiI0d/T45399-D39466-handoff.md"
        self.assertEqual(
            clean_prompt_for_title(raw),
            "T45399-D39466-handoff.md",
        )

    def test_only_image_path_uses_basename(self) -> None:
        raw = "/Users/wxomi/Desktop/Snapzy/Snapzy_2026-09-10_22-49-32_248.png"
        self.assertEqual(
            clean_prompt_for_title(raw),
            "Snapzy_2026-09-10_22-49-32_248.png",
        )

    def test_sanitize_removes_literal_escaped_newlines(self) -> None:
        self.assertEqual(
            sanitize(r"\n/Users/wxomi/Desktop/Snapzy cursor is working"),
            "/Users/wxomi/Desktop/Snapzy cursor is working",
        )

    def test_sanitize_caps_long_titles(self) -> None:
        long_title = "a" * 80
        sanitized = sanitize(long_title)
        self.assertIsNotNone(sanitized)
        self.assertTrue(len(sanitized) <= 56)
        self.assertTrue(sanitized.endswith("…"))


class FormatAgentPathTests(unittest.TestCase):
    def test_home_shows_tilde(self) -> None:
        self.assertEqual(format_agent_path(os.path.expanduser("~")), "~")

    def test_project_uses_basename(self) -> None:
        self.assertEqual(
            format_agent_path("/Users/wxomi/Workspace/code/work/instahyre/devel"),
            "devel",
        )

    def test_location_combines_agent_and_path(self) -> None:
        self.assertEqual(
            format_agent_location(
                "devin",
                "/Users/wxomi/Workspace/code/work/instahyre/devel",
            ),
            "devin · devel",
        )

    def test_location_without_path(self) -> None:
        self.assertEqual(format_agent_location("devin", None), "devin")


class MeaningfulTerminalTitleTests(unittest.TestCase):
    def test_generic_agent_names_ignored(self) -> None:
        for name in ("devin", "cursor", "agy", "kiro", "claude"):
            self.assertIsNone(meaningful_terminal_title(name))

    def test_meaningful_title_preserved(self) -> None:
        self.assertEqual(
            meaningful_terminal_title("Fix auth token refresh bug"),
            "Fix auth token refresh bug",
        )


if __name__ == "__main__":
    unittest.main()
