"""Tests for check-holiday-updates action."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add the action directory to sys.path for imports
sys_path = os.path.join(
    os.path.dirname(__file__), "..", "..", ".github", "actions", "check-holiday-updates"
)
sys.path.insert(0, sys_path)

from check_holiday_updates import HolidayUpdatesChecker  # noqa: E402


class TestHolidayUpdatesChecker:
    """Test cases for HolidayUpdatesChecker class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        self.files_path = self.repo_path / "holidays"

        self.files_path.mkdir(parents=True)

        self.checker = HolidayUpdatesChecker(
            repo_path=str(self.repo_path),
            files_path="holidays",
            threshold_days=180,
            dry_run=True,
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_init_default_values(self):
        """Test initialization with default values."""
        checker = HolidayUpdatesChecker(repo_path=str(self.repo_path))
        assert checker.repo_path == Path(self.repo_path)
        assert checker.files_path == Path("holidays")
        assert checker.threshold_days == 180
        assert checker.dry_run is False
        assert checker.github is None
        assert checker.repo is None

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        checker = HolidayUpdatesChecker(
            repo_path=str(self.repo_path),
            files_path="custom/holidays",
            threshold_days=90,
            github_token="test_token",
            dry_run=True,
        )
        assert checker.files_path == Path("custom/holidays")
        assert checker.threshold_days == 90
        assert checker.dry_run is True

    @patch("check_holiday_updates.Auth")
    @patch("check_holiday_updates.Github")
    def test_init_with_github_token(self, mock_github_class, mock_auth_class):
        """Test initialization with GitHub token."""
        mock_github = Mock()
        mock_repo = Mock()
        mock_auth = Mock()
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github
        mock_auth_class.Token.return_value = mock_auth

        checker = HolidayUpdatesChecker(
            repo_path=str(self.repo_path), github_token="test_token"
        )

        assert checker.github is not None
        assert checker.repo is not None
        mock_auth_class.Token.assert_called_once_with("test_token")
        mock_github_class.assert_called_once_with(auth=mock_auth)
        mock_github.get_repo.assert_called_once_with("vacanza/holidays")

    @patch("check_holiday_updates.Github")
    def test_init_github_error(self, mock_github_class):
        """Test initialization with GitHub error."""
        mock_github_class.side_effect = Exception("API Error")

        checker = HolidayUpdatesChecker(
            repo_path=str(self.repo_path), github_token="test_token"
        )

        assert checker.github is None
        assert checker.repo is None

    def test_get_file_age_days(self):
        """Test getting file age in days."""
        test_file = self.repo_path / "test_file.py"
        test_file.write_text("# Test file")

        age = self.checker.get_file_age_days(test_file)
        assert age >= 0
        assert age < 1  # Should be less than 1 day

    def test_get_file_age_days_nonexistent(self):
        """Test getting age for nonexistent file."""
        nonexistent_file = self.repo_path / "nonexistent.py"
        age = self.checker.get_file_age_days(nonexistent_file)
        assert age == 0

    def test_extract_name_from_path(self):
        """Test extracting human-readable name from file path."""
        test_cases = [
            ("south_korea.py", "South Korea"),
            ("united_states.py", "United States"),
            ("new_zealand.py", "New Zealand"),
            ("test_file.py", "Test File"),
        ]

        for filename, expected in test_cases:
            file_path = Path(filename)
            result = self.checker.extract_name_from_path(file_path)
            assert result == expected

    def test_scan_directory_nonexistent(self):
        """Test scanning nonexistent directory."""
        nonexistent_dir = self.repo_path / "nonexistent"
        result = self.checker.scan_directory(nonexistent_dir, 180)
        assert result == []

    def test_scan_directory_empty(self):
        """Test scanning empty directory."""
        result = self.checker.scan_directory(self.files_path, 180)
        assert result == []

    def test_scan_directory_with_files(self):
        """Test scanning directory with files."""
        now = datetime.now()

        recent_file = self.files_path / "recent.py"
        recent_file.write_text("# Recent file")

        old_file = self.files_path / "old.py"
        old_file.write_text("# Old file")
        old_time = now - timedelta(days=200)
        old_file.touch()
        os.utime(old_file, (old_time.timestamp(), old_time.timestamp()))

        init_file = self.files_path / "__init__.py"
        init_file.write_text("# Init file")

        result = self.checker.scan_directory(self.files_path, 180)

        assert len(result) == 1
        assert result[0]["path"] == "holidays/old.py"
        assert result[0]["name"] == "Old"
        assert result[0]["age_days"] > 180
        assert result[0]["directory_type"] == "holidays"

    def test_check_freshness(self):
        """Test checking freshness of all directories."""
        test_file = self.files_path / "test_file.py"
        test_file.write_text("# Test file")

        result = self.checker.check_freshness()

        assert isinstance(result, list)

    def test_create_issue_title(self):
        """Test creating GitHub issue title."""
        file_info = {"name": "South Korea", "path": "holidays/countries/south_korea.py"}

        title = self.checker.create_issue_title(file_info)
        expected = "[Holiday Updates] Update required: South Korea"
        assert title == expected

    def test_create_issue_body(self):
        """Test creating GitHub issue body."""
        file_info = {
            "name": "South Korea",
            "path": "holidays/countries/south_korea.py",
            "age_days": 200,
            "threshold_days": 180,
            "last_modified": "2023-01-01T00:00:00",
            "directory_type": "countries",
        }

        # Test with template file (should find it from action directory)
        body = self.checker.create_issue_body(file_info)

        # Should use the full template
        assert "## Holiday Data Updates Alert" in body
        assert "**File:** `holidays/countries/south_korea.py`" in body
        assert "**Last Modified:** January 01, 2023" in body
        assert "**Age:** 200 days (threshold: 180 days)" in body
        assert "**Type:** Countries" in body
        assert "South Korea" in body
        assert "**Overdue by:** 20 days" in body

    def test_find_existing_issue_no_repo(self):
        """Test finding existing issue when no repo available."""
        file_info = {"name": "Test", "path": "test.py"}
        result = self.checker.find_existing_issue(file_info)
        assert result is None

    @patch("check_holiday_updates.GithubException")
    def test_find_existing_issue_error(self, mock_exception):
        """Test finding existing issue with GitHub error."""
        mock_repo = Mock()
        mock_repo.get_issues.side_effect = mock_exception("API Error")
        self.checker.repo = mock_repo

        file_info = {"name": "Test", "path": "test.py"}
        result = self.checker.find_existing_issue(file_info)
        assert result is None

    def test_create_github_issue_dry_run(self):
        """Test creating GitHub issue in dry run mode."""
        file_info = {"name": "Test", "path": "test.py"}
        result = self.checker.create_github_issue(file_info)
        assert result is True

    def test_create_github_issue_no_repo(self):
        """Test creating GitHub issue when no repo available."""
        self.checker.dry_run = False
        file_info = {"name": "Test", "path": "test.py"}
        result = self.checker.create_github_issue(file_info)
        assert result is False

    def test_create_github_issue_error(self):
        """Test creating GitHub issue with GitHub error."""
        self.checker.dry_run = False
        mock_repo = Mock()
        mock_repo.get_issues.return_value = []

        class MockGithubException(Exception):
            pass

        mock_repo.create_issue.side_effect = MockGithubException("API Error")
        self.checker.repo = mock_repo

        file_info = {
            "name": "Test",
            "path": "test.py",
            "last_modified": "2023-01-01T00:00:00",
            "age_days": 200,
            "threshold_days": 180,
            "directory_type": "countries",
        }

        with patch("check_holiday_updates.GithubException", MockGithubException):
            result = self.checker.create_github_issue(file_info)
            assert result is False

    def test_process_outdated_files(self):
        """Test processing outdated files."""
        outdated_files = [
            {"name": "File1", "path": "holidays/file1.py"},
            {"name": "File2", "path": "holidays/file2.py"},
            {"name": "File3", "path": "holidays/file3.py"},
        ]

        stats = self.checker.process_outdated_files(outdated_files)

        assert stats["created"] == 3  # All files processed in dry run
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

    def test_run_complete_process(self):
        """Test running the complete process."""
        result = self.checker.run()

        assert "outdated_files" in result
        assert "stats" in result
        assert "timestamp" in result
        assert isinstance(result["outdated_files"], list)


class TestMainFunction:
    """Test cases for main function and argument parsing."""

    @patch("check_holiday_updates.HolidayUpdatesChecker")
    @patch.dict(os.environ, {"INPUT_DRY_RUN": "true"})
    @patch("check_holiday_updates.os.path.exists")
    @patch("check_holiday_updates.os.listdir")
    def test_main_dry_run(self, mock_listdir, mock_exists, mock_checker_class):
        """Test main function with dry run."""
        mock_exists.return_value = True
        mock_listdir.return_value = [".git", "holidays"]

        mock_checker = Mock()
        mock_checker.run.return_value = {
            "outdated_files": [],
            "stats": {"errors": 0, "created": 0},
        }
        mock_checker_class.return_value = mock_checker

        from check_holiday_updates import main

        main()

        mock_checker_class.assert_called_once()
        mock_checker.run.assert_called_once()

    @patch("check_holiday_updates.HolidayUpdatesChecker")
    @patch.dict(os.environ, {"INPUT_DRY_RUN": "true"})
    @patch("check_holiday_updates.sys.exit")
    @patch("check_holiday_updates.os.path.exists")
    @patch("check_holiday_updates.os.listdir")
    def test_main_with_errors(
        self, mock_listdir, mock_exists, mock_exit, mock_checker_class
    ):
        """Test main function with errors."""
        mock_exists.return_value = True
        mock_listdir.return_value = [".git", "holidays"]

        mock_checker = Mock()
        mock_checker.run.return_value = {
            "outdated_files": [],
            "stats": {"errors": 1, "created": 0},
        }
        mock_checker_class.return_value = mock_checker

        from check_holiday_updates import main

        main()

        mock_exit.assert_called_once_with(1)


if __name__ == "__main__":
    pytest.main([__file__])
