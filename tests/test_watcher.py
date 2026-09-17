"""Unit tests for flock-based concurrency and watcher lifecycle."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from session_titles.cleanup import (
    _SHELL_START_TIME_CACHE,
    cleanup_unused_tabs,
    get_shell_start_time,
)
from session_titles.client import HerdrClient
from session_titles.watcher import (
    acquire_watcher_lock,
    already_watching,
    get_watcher_status,
)


class TestWatcherAndCaching(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_file = os.path.join(self.temp_dir.name, "watcher.lock")
        _SHELL_START_TIME_CACHE.clear()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        _SHELL_START_TIME_CACHE.clear()

    def test_flock_single_instance_concurrency(self) -> None:
        with patch("session_titles.watcher.LOCK_FILE", self.lock_file):
            # Initially no watcher is running
            self.assertFalse(already_watching())
            status = get_watcher_status()
            self.assertFalse(status["running"])
            self.assertIsNone(status["pid"])

            # First acquisition succeeds
            lock1 = acquire_watcher_lock()
            self.assertIsNotNone(lock1)

            # While lock1 is held, already_watching() is True
            self.assertTrue(already_watching())
            status = get_watcher_status()
            self.assertTrue(status["running"])
            self.assertEqual(status["pid"], os.getpid())

            # Second acquisition fails
            lock2 = acquire_watcher_lock()
            self.assertIsNone(lock2)

            # Releasing lock frees it
            lock1.close()
            self.assertFalse(already_watching())

    def test_shell_start_time_caching(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdout = "Tue Sep 15 21:34:49 2026\n"

        with patch("subprocess.run", return_value=mock_proc) as mock_subproc:
            t1 = get_shell_start_time(12345)
            self.assertIsNotNone(t1)
            self.assertEqual(mock_subproc.call_count, 1)

            # Second call for the same PID MUST use cache without invoking subprocess
            t2 = get_shell_start_time(12345)
            self.assertEqual(t1, t2)
            self.assertEqual(mock_subproc.call_count, 1)

    def test_client_server_identity(self) -> None:
        client = HerdrClient(self.lock_file)
        # File doesn't exist yet
        self.assertIsNone(client.server_identity())

        # Create file
        with open(self.lock_file, "w") as f:
            f.write("test")

        identity = client.server_identity()
        self.assertIsNotNone(identity)
        self.assertIsInstance(identity, tuple)
        self.assertEqual(len(identity), 2)


if __name__ == "__main__":
    unittest.main()
