#!/usr/bin/env python3
"""
Holiday Updates Monitor

This script checks the modification dates of holiday files in the countries/ and financial/
directories and identifies files that may need updating based on configurable age thresholds.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from github import Auth, Github
    from github.GithubException import GithubException
except ImportError:
    Auth = None  # type: ignore
    Github = None  # type: ignore
    GithubException = None  # type: ignore


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class HolidayUpdatesChecker:
    """Check holiday file updates and manage GitHub issues."""

    def __init__(
        self,
        repo_path: str,
        files_path: str = "holidays",
        threshold_days: int = 180,
        github_token: Optional[str] = None,
        dry_run: bool = False,
    ):
        """
        Initialize the freshness checker.

        Args:
            repo_path: Path to the repository root
            files_path: Path to directory containing holiday files to check
            threshold_days: Days threshold for files (default: 180)
            github_token: GitHub token for API access
            dry_run: If True, don't create actual issues
        """
        self.repo_path = Path(repo_path)
        self.files_path = Path(files_path)
        self.threshold_days = threshold_days
        self.dry_run = dry_run

        # Configure git to trust the workspace directory (fixes dubious ownership issue in GitHub Actions)
        self._configure_git_safe_directory()

        self.github: Optional[Github] = None
        self.repo: Optional[Any] = None
        if github_token and Github is not None and Auth is not None:
            try:
                auth = Auth.Token(github_token)
                self.github = Github(auth=auth)
                self.repo = self.github.get_repo("vacanza/holidays")
                logger.debug("GitHub client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize GitHub client: {e}")
                self.github = None
                self.repo = None
        elif github_token and (Github is None or Auth is None):
            logger.warning("PyGithub not available, GitHub integration disabled")

    def _configure_git_safe_directory(self) -> None:
        """Configure git to trust the workspace directory."""
        try:
            safe_dir_result = subprocess.run(
                [
                    "git",
                    "config",
                    "--global",
                    "--add",
                    "safe.directory",
                    str(self.repo_path),
                ],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if safe_dir_result.returncode != 0:
                logger.warning(
                    f"Failed to configure safe directory: {safe_dir_result.stderr}"
                )
            else:
                logger.debug(f"Configured git safe directory: {self.repo_path}")
        except Exception as e:
            logger.warning(f"Error configuring git safe directory: {e}")

    def get_file_age_days(self, file_path: Path) -> int:
        """Get file age in days since last commit."""
        try:
            # Get the last commit date for this file using git log
            # Use relative path from repository root
            relative_path = file_path.relative_to(self.repo_path)

            # Debug logging
            logger.debug(f"Running git command for file: {relative_path}")
            logger.debug(f"Working directory: {self.repo_path}")
            logger.debug(f"File exists: {file_path.exists()}")

            # Check if git repository is properly initialized
            git_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if git_status.returncode != 0:
                logger.error(
                    f"Git repository not properly initialized: {git_status.stderr}"
                )
                raise RuntimeError(
                    f"Git repository not accessible: {git_status.stderr}"
                )

            # Try different git commands in order of preference
            git_commands = [
                [
                    "git",
                    "log",
                    "-1",
                    "--format=%ct",
                    "--follow",
                    "--",
                    str(relative_path),
                ],
                ["git", "log", "-1", "--format=%ct", "--", str(relative_path)],
                ["git", "log", "-1", "--format=%ct", "--all", "--", str(relative_path)],
            ]

            result = None
            for cmd in git_commands:
                try:
                    result = subprocess.run(
                        cmd,
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    if result.stdout.strip():
                        break
                except subprocess.CalledProcessError:
                    continue

            if not result or not result.stdout.strip():
                raise RuntimeError(
                    f"No git commit history found for file: {relative_path}"
                )

            # Convert Unix timestamp to datetime (UTC)
            last_commit_timestamp = int(result.stdout.strip())
            last_commit_date = datetime.fromtimestamp(
                last_commit_timestamp, tz=None
            )  # UTC
            current_time = datetime.now()
            age = current_time - last_commit_date

            # Calculate age in days with proper rounding
            age_days = round(age.total_seconds() / 86400)

            # Verbose logging for each file's commit date
            logger.info(
                f"File {relative_path}: last commit on {last_commit_date.strftime('%Y-%m-%d %H:%M:%S')} "
                f"({age_days} days ago)"
            )

            return age_days

        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting git commit date for {file_path}: {e}")
            logger.error(f"Git command stderr: {e.stderr}")
            logger.error(f"Git command stdout: {e.stdout}")
            logger.error(f"Git command return code: {e.returncode}")
            raise RuntimeError(
                f"Failed to get git commit date for {file_path}: {e}"
            ) from e
        except OSError as e:
            logger.error(f"Error accessing file {file_path}: {e}")
            raise RuntimeError(f"Failed to access file {file_path}: {e}") from e

    def get_last_commit_date(self, file_path: Path) -> datetime:
        """Get the last commit date for a file."""
        try:
            # Get the last commit date for this file using git log
            relative_path = file_path.relative_to(self.repo_path)
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "--", str(relative_path)],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            if result.stdout.strip():
                # Convert Unix timestamp to datetime
                last_commit_timestamp = int(result.stdout.strip())
                last_commit_date = datetime.fromtimestamp(last_commit_timestamp)

                # Verbose logging for each file's commit date
                logger.info(
                    f"File {relative_path}: last commit on {last_commit_date.strftime('%Y-%m-%d %H:%M:%S')}"
                )

                return last_commit_date
            else:
                raise RuntimeError(
                    f"No git commit history found for file: {relative_path}"
                )

        except subprocess.CalledProcessError as e:
            logger.error(f"Error getting last commit date for {file_path}: {e}")
            raise RuntimeError(
                f"Failed to get git commit date for {file_path}: {e}"
            ) from e
        except OSError as e:
            logger.error(f"Error accessing file {file_path}: {e}")
            raise RuntimeError(f"Failed to access file {file_path}: {e}") from e

    def extract_name_from_path(self, file_path: Path) -> str:
        """Extract a human-readable name from file path."""
        name = file_path.stem.replace("_", " ").title()
        return name

    def scan_directory(self, directory: Path, threshold_days: int) -> List[Dict]:
        """
        Scan a directory for outdated files.

        Args:
            directory: Directory to scan
            threshold_days: Age threshold in days

        Returns:
            List of dictionaries with file information
        """
        outdated_files: List[Dict] = []

        if not directory.exists():
            logger.warning(f"Directory does not exist: {directory}")
            return outdated_files

        logger.info(
            f"Scanning directory: {directory} (threshold: {threshold_days} days)"
        )

        # Count total files first
        all_files = list(directory.glob("*.py"))
        python_files = [f for f in all_files if f.name != "__init__.py"]
        logger.info(
            f"Found {len(python_files)} Python files to check (excluding __init__.py)"
        )

        for file_path in python_files:
            age_days = self.get_file_age_days(file_path)

            if age_days > threshold_days:
                # Get the last commit date for this file
                last_modified = self.get_last_commit_date(file_path)
                file_info = {
                    "path": str(file_path.relative_to(self.repo_path)),
                    "name": self.extract_name_from_path(file_path),
                    "age_days": age_days,
                    "last_modified": last_modified.isoformat(),
                    "threshold_days": threshold_days,
                    "directory_type": directory.name,
                }
                outdated_files.append(file_info)
                logger.info(
                    f"Outdated file found: {file_info['path']} ({age_days} days old)"
                )
            else:
                logger.info(
                    f"File {file_path.relative_to(self.repo_path)} is up to date ({age_days} days old, threshold: {threshold_days} days)"
                )

        logger.info(
            f"Directory scan complete: {len(outdated_files)} outdated files found out of {len(python_files)} total files"
        )
        return outdated_files

    def check_freshness(self) -> List[Dict]:
        """
        Check freshness of all holiday files.

        Returns:
            List of dictionaries containing outdated files
        """
        logger.info("Starting holiday updates check...")
        logger.info(f"Repository path: {self.repo_path}")
        logger.info(f"Files path: {self.files_path}")
        logger.info(f"Threshold days: {self.threshold_days}")

        files_dir = self.repo_path / self.files_path
        logger.info(f"Scanning files directory: {files_dir}")

        outdated_files = self.scan_directory(files_dir, self.threshold_days)

        logger.info(f"Found {len(outdated_files)} outdated files total")

        return outdated_files

    def create_issue_title(self, file_info: Dict) -> str:
        """Create a GitHub issue title for an outdated file."""
        return f"[Holiday Updates] Update required: {file_info['name']}"

    def create_issue_body(self, file_info: Dict) -> str:
        """Create a GitHub issue body for an outdated file."""
        last_modified = datetime.fromisoformat(file_info["last_modified"])
        formatted_date = last_modified.strftime("%B %d, %Y")

        # Use template from the same directory as this script
        template_path = Path(__file__).parent / "issue_body_template.md"
        try:
            with open(template_path, encoding="utf-8") as f:
                template = f.read()
        except FileNotFoundError:
            logger.error(f"Template file not found: {template_path}")
            return f"File {file_info['path']} needs updating (last modified: {formatted_date})"

        return template.format(
            path=file_info["path"],
            formatted_date=formatted_date,
            age_days=file_info["age_days"],
            threshold_days=file_info["threshold_days"],
            directory_type=file_info["directory_type"].title(),
            name=file_info["name"],
            overdue_days=file_info["age_days"] - file_info["threshold_days"],
        )

    def find_existing_issue(self, file_info: Dict) -> Optional[Any]:
        """Find existing open issue for a file."""
        if not self.repo:
            return None

        try:
            title = self.create_issue_title(file_info)
            issues = self.repo.get_issues(state="open")

            for issue in issues:
                if issue.title == title:
                    return issue
        except GithubException as e:
            logger.error(f"Error searching for existing issues: {e}")

        return None

    def create_github_issue(self, file_info: Dict) -> bool:
        """Create a GitHub issue for an outdated file."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create issue for: {file_info['path']}")
            return True

        if not self.repo:
            logger.error("GitHub repository not available")
            return False

        existing_issue = self.find_existing_issue(file_info)
        if existing_issue:
            logger.info(
                f"Existing issue found for {file_info['path']}: #{existing_issue.number}"
            )
            return True

        try:
            title = self.create_issue_title(file_info)
            body = self.create_issue_body(file_info)
            labels = ["holiday-updates", "maintenance", "data-update"]

            issue = self.repo.create_issue(title=title, body=body, labels=labels)

            logger.info(f"Created issue #{issue.number} for {file_info['path']}")
            return True

        except GithubException as e:
            logger.error(f"Failed to create issue for {file_info['path']}: {e}")
            return False

    def process_outdated_files(self, outdated_files: List[Dict]) -> Dict[str, int]:
        """
        Process outdated files and create GitHub issues.

        Returns:
            Dictionary with counts of issues created/updated
        """
        stats = {"created": 0, "skipped": 0, "errors": 0}

        for file_info in outdated_files:
            try:
                if self.create_github_issue(file_info):
                    stats["created"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error processing {file_info['path']}: {e}")
                stats["errors"] += 1

        return stats

    def run(self) -> Dict:
        """Run the complete freshness check and issue creation process."""
        logger.info("Starting holiday updates monitoring...")

        outdated_files = self.check_freshness()

        stats = self.process_outdated_files(outdated_files)

        logger.info("Updates check completed:")
        logger.info(f"  - Issues created: {stats['created']}")
        logger.info(f"  - Errors: {stats['errors']}")

        return {
            "outdated_files": outdated_files,
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }


def write_github_output(output_name: str, value: str) -> None:
    """Write output to GitHub Actions output file."""
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{output_name}={value}\n")


def main():
    """Main entry point."""
    # Read configuration from environment variables
    # In GitHub Actions Docker environment, the workspace is always mounted at /github/workspace
    repo_path = "/github/workspace"

    files_path = os.getenv("INPUT_FILES_PATH", "holidays")
    threshold_days = int(os.getenv("INPUT_THRESHOLD_DAYS", "180"))
    github_token = os.getenv("INPUT_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    dry_run = os.getenv("INPUT_DRY_RUN", "false").lower() == "true"

    # Debug information
    logger.info(f"Repository path: {repo_path}")
    logger.info(f"Files path: {files_path}")
    logger.info(f"Repository path exists: {os.path.exists(repo_path)}")

    if os.path.exists(repo_path):
        logger.info(f"Repository path contents: {os.listdir(repo_path)}")
        # Check if it's a git repository
        if (Path(repo_path) / ".git").exists():
            logger.info("Git repository found")
        else:
            logger.warning("No .git directory found in repository path")
    else:
        logger.error(f"Repository path does not exist: {repo_path}")
        sys.exit(1)

    checker = HolidayUpdatesChecker(
        repo_path=repo_path,
        files_path=files_path,
        threshold_days=threshold_days,
        github_token=github_token,
        dry_run=dry_run,
    )

    try:
        result = checker.run()

        # Write outputs for GitHub Actions
        write_github_output("outdated_files", str(len(result["outdated_files"])))
        write_github_output("outdated_files_count", str(len(result["outdated_files"])))
        write_github_output("issues_created", str(result["stats"]["created"]))

        # Print summary information
        print("📊 Summary:")
        print(f"  • Outdated files found: {len(result['outdated_files'])}")
        print(f"  • Issues created: {result['stats']['created']}")
        print(f"  • Errors: {result['stats']['errors']}")

        if result["outdated_files"]:
            print("\n📁 Outdated files:")
            for file_info in result["outdated_files"]:
                print(f"  • {file_info['path']} ({file_info['age_days']} days old)")

        if result["stats"]["errors"] > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
