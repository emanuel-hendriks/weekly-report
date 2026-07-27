"""Unit tests for Jira auth error cases.

Tests cover:
- Token file missing → JiraAuthError with correct message and path
- Token file empty → JiraAuthError indicating no valid token
- Token file with I/O error → JiraAuthError with underlying reason
- Missing jira_username in config → JiraAuthError
- Empty jira_username → JiraAuthError
- Invalid JSON config (non-dict) → JiraAuthError

Requirements: 2.5, 2.6, 2.7, 2.8, 7.3, 7.4, 7.5, 7.6
"""

from unittest.mock import patch, PropertyMock

import pytest

from weekly_recap.auth.jira_auth import (
    prepare_auth,
    _read_token_file,
    JiraAuthError,
    TOKEN_FILE_PATH,
    TOKEN_CREATE_URL,
)


class TestReadTokenFileMissing:
    """Test _read_token_file() when token file does not exist."""

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_missing_file_raises_jira_auth_error(self, mock_path):
        """File missing → JiraAuthError raised."""
        mock_path.exists.return_value = False
        mock_path.__str__ = lambda self: str(TOKEN_FILE_PATH)

        with pytest.raises(JiraAuthError):
            _read_token_file()

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_missing_file_error_contains_path(self, mock_path):
        """File missing → error message includes expected file path."""
        mock_path.exists.return_value = False
        mock_path.__str__ = lambda self: str(TOKEN_FILE_PATH)

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert ".config/.jira/.token" in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_missing_file_error_contains_create_url(self, mock_path):
        """File missing → error message includes token creation URL."""
        mock_path.exists.return_value = False
        mock_path.__str__ = lambda self: str(TOKEN_FILE_PATH)

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert TOKEN_CREATE_URL in error_msg


class TestReadTokenFileEmpty:
    """Test _read_token_file() when token file is empty or whitespace only."""

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_empty_file_raises_jira_auth_error(self, mock_path):
        """File empty → JiraAuthError raised."""
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = ""

        with pytest.raises(JiraAuthError):
            _read_token_file()

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_whitespace_only_file_raises_jira_auth_error(self, mock_path):
        """File with only whitespace → JiraAuthError raised."""
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "   \n\n   \n"

        with pytest.raises(JiraAuthError):
            _read_token_file()

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_empty_file_error_contains_path(self, mock_path):
        """Empty file → error message includes path."""
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = ""
        mock_path.__fspath__ = lambda s: str(TOKEN_FILE_PATH)
        mock_path.__str__ = lambda s: str(TOKEN_FILE_PATH)

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert ".config/.jira/.token" in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_empty_file_error_contains_create_url(self, mock_path):
        """Empty file → error message includes token creation URL."""
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = ""

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert TOKEN_CREATE_URL in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_jira_token_prefix_empty_value_raises_error(self, mock_path):
        """File with JIRA_API_TOKEN= but no value → JiraAuthError."""
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = "JIRA_API_TOKEN="

        with pytest.raises(JiraAuthError):
            _read_token_file()


class TestReadTokenFileIOError:
    """Test _read_token_file() when file has I/O error."""

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_io_error_raises_jira_auth_error(self, mock_path):
        """I/O error on read → JiraAuthError raised."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")

        with pytest.raises(JiraAuthError):
            _read_token_file()

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_io_error_contains_reason(self, mock_path):
        """I/O error → error message includes underlying reason."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Permission denied")

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert "Permission denied" in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_io_error_contains_path(self, mock_path):
        """I/O error → error message includes file path."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Disk full")
        mock_path.__fspath__ = lambda s: str(TOKEN_FILE_PATH)
        mock_path.__str__ = lambda s: str(TOKEN_FILE_PATH)

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert ".config/.jira/.token" in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_io_error_contains_create_url(self, mock_path):
        """I/O error → error message includes token creation URL."""
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Some error")

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        error_msg = str(exc_info.value)
        assert TOKEN_CREATE_URL in error_msg

    @patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH")
    def test_io_error_chains_original_exception(self, mock_path):
        """I/O error → JiraAuthError chains the original OSError."""
        original_error = OSError("Disk failure")
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = original_error

        with pytest.raises(JiraAuthError) as exc_info:
            _read_token_file()

        assert exc_info.value.__cause__ is original_error


class TestPrepareAuthMissingUsername:
    """Test prepare_auth() when jira_username is missing from config."""

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_missing_jira_username_raises_error(self, mock_read_token):
        """Config without jira_username key → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth({})

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_missing_jira_username_error_message(self, mock_read_token):
        """Config without jira_username → error mentions the field."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError) as exc_info:
            prepare_auth({})

        error_msg = str(exc_info.value)
        assert "jira_username" in error_msg


class TestPrepareAuthEmptyUsername:
    """Test prepare_auth() when jira_username is empty."""

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_empty_jira_username_raises_error(self, mock_read_token):
        """Empty string jira_username → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth({"jira_username": ""})

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_whitespace_jira_username_raises_error(self, mock_read_token):
        """Whitespace-only jira_username → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth({"jira_username": "   "})

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_empty_username_error_mentions_field(self, mock_read_token):
        """Empty jira_username → error mentions the field."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError) as exc_info:
            prepare_auth({"jira_username": ""})

        error_msg = str(exc_info.value)
        assert "jira_username" in error_msg


class TestPrepareAuthInvalidConfig:
    """Test prepare_auth() when config is not a dict (invalid JSON config)."""

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_non_dict_config_raises_error(self, mock_read_token):
        """Non-dict config (e.g. a string) → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth("not a dict")

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_none_config_raises_error(self, mock_read_token):
        """None config → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth(None)

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_list_config_raises_error(self, mock_read_token):
        """List config → JiraAuthError."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError):
            prepare_auth([])

    @patch("weekly_recap.auth.jira_auth._read_token_file")
    def test_invalid_config_error_message(self, mock_read_token):
        """Invalid config → error mentions expected dict/dictionary."""
        mock_read_token.return_value = "valid_token"

        with pytest.raises(JiraAuthError) as exc_info:
            prepare_auth("not a dict")

        error_msg = str(exc_info.value)
        assert "dictionary" in error_msg.lower() or "dict" in error_msg.lower()
