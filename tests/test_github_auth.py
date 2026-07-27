"""Unit tests for GitHub auth error cases.

Tests cover:
- File missing with no gh CLI → GitHubAuthError raised with correct message
- File empty → treated as missing, fallback attempted
- File with PermissionError → fallback attempted
- gh CLI timeout (>10s) → returns None (GitHubAuthError raised by get_github_token)
- gh CLI not found → fallback fails gracefully
- gh CLI non-zero exit → fallback fails
- Deprecation notice written to stderr on gh fallback success

Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 6.3, 6.4, 6.5, 7.1, 7.2
"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from weekly_recap.auth.github_auth import (
    get_github_token,
    _read_token_file,
    _gh_cli_fallback,
    GitHubAuthError,
    TOKEN_FILE_PATH,
)


class TestGetGithubTokenErrors:
    """Test get_github_token() raises GitHubAuthError when both sources fail."""

    @patch("weekly_recap.auth.github_auth._gh_cli_fallback")
    @patch("weekly_recap.auth.github_auth._read_token_file")
    def test_file_missing_and_gh_not_found_raises_error(
        self, mock_read_file, mock_gh_fallback
    ):
        """File missing AND gh CLI not found → GitHubAuthError raised."""
        mock_read_file.return_value = None
        mock_gh_fallback.return_value = None

        with pytest.raises(GitHubAuthError) as exc_info:
            get_github_token()

        error_msg = str(exc_info.value)
        assert str(TOKEN_FILE_PATH) in error_msg
        assert "github.com/settings/tokens" in error_msg

    @patch("weekly_recap.auth.github_auth._gh_cli_fallback")
    @patch("weekly_recap.auth.github_auth._read_token_file")
    def test_file_missing_and_gh_nonzero_exit_raises_error(
        self, mock_read_file, mock_gh_fallback
    ):
        """File missing AND gh CLI returns non-zero → GitHubAuthError raised."""
        mock_read_file.return_value = None
        mock_gh_fallback.return_value = None

        with pytest.raises(GitHubAuthError) as exc_info:
            get_github_token()

        error_msg = str(exc_info.value)
        assert str(TOKEN_FILE_PATH) in error_msg

    @patch("weekly_recap.auth.github_auth._gh_cli_fallback")
    @patch("weekly_recap.auth.github_auth._read_token_file")
    def test_error_message_contains_path_and_url(
        self, mock_read_file, mock_gh_fallback
    ):
        """Error message includes expected file path and PAT creation URL."""
        mock_read_file.return_value = None
        mock_gh_fallback.return_value = None

        with pytest.raises(GitHubAuthError) as exc_info:
            get_github_token()

        error_msg = str(exc_info.value)
        assert str(TOKEN_FILE_PATH) in error_msg
        assert "https://github.com/settings/tokens" in error_msg
        assert "plain text" in error_msg


class TestReadTokenFile:
    """Test _read_token_file() edge cases."""

    @patch("weekly_recap.auth.github_auth.TOKEN_FILE_PATH")
    def test_empty_file_returns_none(self, mock_path):
        """File empty → treated as missing (returns None)."""
        mock_path.read_text.return_value = ""
        result = _read_token_file()
        assert result is None

    @patch("weekly_recap.auth.github_auth.TOKEN_FILE_PATH")
    def test_whitespace_only_file_returns_none(self, mock_path):
        """File with only whitespace → treated as missing."""
        mock_path.read_text.return_value = "   \n\n   \n"
        result = _read_token_file()
        assert result is None

    @patch("weekly_recap.auth.github_auth.TOKEN_FILE_PATH")
    def test_permission_error_returns_none(self, mock_path):
        """File with PermissionError → returns None (fallback attempted)."""
        mock_path.read_text.side_effect = PermissionError("Permission denied")
        result = _read_token_file()
        assert result is None

    @patch("weekly_recap.auth.github_auth.TOKEN_FILE_PATH")
    def test_file_not_found_returns_none(self, mock_path):
        """File not found → returns None."""
        mock_path.read_text.side_effect = FileNotFoundError("No such file")
        result = _read_token_file()
        assert result is None


class TestReadTokenFileTriggersGhFallback:
    """Test that when _read_token_file() returns None, get_github_token tries gh CLI."""

    @patch("weekly_recap.auth.github_auth._gh_cli_fallback")
    @patch("weekly_recap.auth.github_auth._read_token_file")
    def test_empty_file_triggers_fallback(self, mock_read_file, mock_gh_fallback):
        """Empty file → get_github_token tries gh CLI fallback."""
        mock_read_file.return_value = None
        mock_gh_fallback.return_value = "ghp_fallback_token"

        result = get_github_token()
        assert result == "ghp_fallback_token"
        mock_gh_fallback.assert_called_once()

    @patch("weekly_recap.auth.github_auth._gh_cli_fallback")
    @patch("weekly_recap.auth.github_auth._read_token_file")
    def test_permission_error_triggers_fallback(self, mock_read_file, mock_gh_fallback):
        """PermissionError on file → get_github_token tries gh CLI fallback."""
        mock_read_file.return_value = None
        mock_gh_fallback.return_value = "ghp_fallback_token"

        result = get_github_token()
        assert result == "ghp_fallback_token"
        mock_gh_fallback.assert_called_once()


class TestGhCliFallback:
    """Test _gh_cli_fallback() failure modes."""

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        """gh CLI timeout (>10s) → returns None."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh auth token", timeout=10)
        result = _gh_cli_fallback()
        assert result is None

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    def test_gh_not_found_returns_none(self, mock_run):
        """gh CLI not found (FileNotFoundError) → returns None."""
        mock_run.side_effect = FileNotFoundError("No such file or directory: 'gh'")
        result = _gh_cli_fallback()
        assert result is None

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    def test_nonzero_exit_returns_none(self, mock_run):
        """gh CLI non-zero exit code → returns None."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = _gh_cli_fallback()
        assert result is None

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    def test_empty_stdout_returns_none(self, mock_run):
        """gh CLI returns empty stdout → returns None."""
        mock_run.return_value = MagicMock(returncode=0, stdout="   \n")
        result = _gh_cli_fallback()
        assert result is None

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    def test_success_writes_deprecation_to_stderr(self, mock_run, capsys):
        """gh CLI success → deprecation notice written to stderr."""
        mock_run.return_value = MagicMock(returncode=0, stdout="ghp_valid_token\n")

        result = _gh_cli_fallback()

        assert result == "ghp_valid_token"
        captured = capsys.readouterr()
        assert "[DEPRECATION]" in captured.err
        assert str(TOKEN_FILE_PATH) in captured.err


class TestGhCliTimeoutRaisesError:
    """Test that gh CLI timeout results in GitHubAuthError from get_github_token."""

    @patch("weekly_recap.auth.github_auth.subprocess.run")
    @patch("weekly_recap.auth.github_auth.TOKEN_FILE_PATH")
    def test_timeout_raises_github_auth_error(self, mock_path, mock_run):
        """File missing + gh CLI timeout → GitHubAuthError raised."""
        mock_path.read_text.side_effect = FileNotFoundError("No such file")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh auth token", timeout=10)

        with pytest.raises(GitHubAuthError):
            get_github_token()
