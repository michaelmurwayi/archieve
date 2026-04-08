# test_archive_files.py
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
import os

import archive_files as arch

class TestArchiveFiles(unittest.TestCase):

    @patch("archive_files.grp.getgrnam")
    @patch("archive_files.pwd.getpwall")
    def test_get_group_members(self, mock_getpwall, mock_getgrnam):
        # Setup group info
        mock_getgrnam.return_value.gr_mem = ["alice"]
        mock_getgrnam.return_value.gr_gid = 1007

        # Setup users with GID
        mock_getpwall.return_value = [MagicMock(pw_name="bob", pw_gid=1007)]
        members = arch.get_group_members("developers")
        self.assertIn("alice", members)
        self.assertIn("bob", members)

    @patch("archive_files.pwd.getpwnam")
    def test_get_user_home(self, mock_getpwnam):
        mock_getpwnam.return_value.pw_dir = "/home/alice"
        home = arch.get_user_home("alice")
        self.assertEqual(str(home), "/home/alice")

    @patch("archive_files.shutil.move")
    def test_archive_user_files(self, mock_move):
        # Create temporary home dir
        with tempfile.TemporaryDirectory() as tmp_home:
            home_dir = Path(tmp_home)
            # Create files and subdirs
            file1 = home_dir / "file1.txt"
            file1.write_text("hello")
            subdir = home_dir / "docs"
            subdir.mkdir()
            file2 = subdir / "file2.txt"
            file2.write_text("world")

            # Create temp archive dir
            with tempfile.TemporaryDirectory() as tmp_archive:
                archive_root = Path(tmp_archive)

                # Mock DB logger
                db_logger = MagicMock()
                db_logger.log_event = MagicMock()

                moved, skipped, errors = arch.archive_user_files(
                    group_name="developers",
                    username="alice",
                    home_dir=home_dir,
                    archive_root=archive_root,
                    db_logger=db_logger,
                )

                self.assertEqual(moved, 2)
                self.assertEqual(skipped, 0)
                self.assertEqual(errors, 0)

                # Check that shutil.move was called twice
                self.assertEqual(mock_move.call_count, 2)

    def test_destination_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.touch()
            self.assertTrue(arch.destination_already_exists(path))
            non_existing = Path(tmp) / "nofile.txt"
            self.assertFalse(arch.destination_already_exists(non_existing))

    @patch("archive_files.psycopg2.connect")
    def test_db_logger_connect_and_disable(self, mock_connect):
        # Mock successful connection
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db_config = {
            "host": "localhost",
            "port": "5432",
            "name": "archivedb",
            "user": "archiveuser",
            "password": "archivepass",
        }
        logger = arch.DBLogger(db_config)
        logger.connect()
        self.assertTrue(logger.enabled)
        logger.disable()
        self.assertFalse(logger.enabled)
        self.assertIsNone(logger.conn)

    @patch("archive_files.grp.getgrnam")
    def test_group_not_found(self, mock_getgrnam):
        mock_getgrnam.side_effect = KeyError()
        with self.assertRaises(ValueError):
            arch.get_group_members("nonexistentgroup")

    @patch("archive_files.pwd.getpwnam")
    def test_user_not_found(self, mock_getpwnam):
        mock_getpwnam.side_effect = KeyError()
        with self.assertRaises(ValueError):
            arch.get_user_home("nonexistentuser")


if __name__ == "__main__":
    unittest.main()