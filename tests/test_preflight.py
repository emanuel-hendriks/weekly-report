"""Tests for weekly_recap/preflight.py — preflight check logic."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from weekly_recap.preflight import (
    PreflightResult,
    check_github_auth,
    check_jira_token,
    check_ms_graph_token,
    check_python3,
    check_setup_complete,
    check_user_config,
    run_preflight,
)


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    """Create a minimal valid project root."""
    (tmp_path / ".setup-complete").touch()
    config = {
        "name": "Test User",
        "jira_url": "https://test.atlassian.net",
        "jira_username": "test@company.com",
        "github_handle": "testuser",
        "github_orgs": ["test-org"],
        "jira_projects": ["TEST"],
        "jira_assets_workspace_id": "test-workspace-id",
        "calendar_email": "test@company.com",
        "ms_graph_tenant_id": "test-tenant-id",
        "ms_graph_client_id": "test-client-id",
    }
    (tmp_path / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


# --- check_setup_complete ---


class TestCheckSetupComplete:
    def test_passes_when_sentinel_exists(self, fake_root: Path):
        assert check_setup_complete(fake_root) is None

    def test_fails_when_sentinel_missing(self, tmp_path: Path):
        result = check_setup_complete(tmp_path)
        assert result is not None
        assert "SETUP_NOT_RUN" in result


# --- check_user_config ---


class TestCheckUserConfig:
    def test_passes_with_valid_config(self, fake_root: Path):
        assert check_user_config(fake_root) is None

    def test_fails_when_file_missing(self, tmp_path: Path):
        result = check_user_config(tmp_path)
        assert result is not None
        assert "CONFIG_MISSING" in result

    def test_fails_with_invalid_json(self, tmp_path: Path):
        (tmp_path / "user-config.json").write_text("not json{{{", encoding="utf-8")
        result = check_user_config(tmp_path)
        assert result is not None
        assert "CONFIG_MISSING" in result
        assert "not valid JSON" in result

    def test_fails_with_placeholder_name(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["name"] = "Your Name"
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "CONFIG_PLACEHOLDER" in result
        assert "name" in result

    def test_fails_with_empty_name(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["name"] = ""
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "name" in result

    def test_fails_with_placeholder_jira_username(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["jira_username"] = "your.email@company.com"
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "jira_username" in result

    def test_fails_with_placeholder_github_handle(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["github_handle"] = "your-github-handle"
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "github_handle" in result

    def test_fails_with_empty_github_orgs(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["github_orgs"] = []
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "github_orgs" in result

    def test_reports_multiple_placeholder_fields(self, fake_root: Path):
        config = json.loads((fake_root / "user-config.json").read_text())
        config["name"] = ""
        config["github_handle"] = ""
        (fake_root / "user-config.json").write_text(json.dumps(config), encoding="utf-8")
        result = check_user_config(fake_root)
        assert result is not None
        assert "name" in result
        assert "github_handle" in result


# --- check_python3 ---


class TestCheckPython3:
    def test_passes_when_python3_available(self):
        # python3 is available since we're running this test with it
        assert check_python3() is None

    @patch("shutil.which", return_value=None)
    def test_fails_when_python3_missing(self, mock_which):
        result = check_python3()
        assert result is not None
        assert "PYTHON3_MISSING" in result


# --- check_ms_graph_token ---


class TestCheckMsGraphToken:
    def test_passes_when_token_exists(self, tmp_path: Path):
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            (tmp_path / ".ms-graph-tokens.json").write_text("{}", encoding="utf-8")
            assert check_ms_graph_token() is None

    def test_fails_when_token_missing(self, tmp_path: Path):
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            result = check_ms_graph_token()
            assert result is not None
            assert "MS_GRAPH_TOKEN" in result


# --- PreflightResult ---


class TestPreflightResult:
    def test_ready_when_no_errors(self):
        r = PreflightResult()
        assert r.ready is True

    def test_ready_with_warnings_only(self):
        r = PreflightResult(warnings=["some warning"])
        assert r.ready is True

    def test_not_ready_with_errors(self):
        r = PreflightResult(errors=["some error"])
        assert r.ready is False


# --- run_preflight (integration-style with mocked externals) ---


class TestRunPreflight:
    @patch("weekly_recap.preflight.check_github_auth", return_value=("ready", "GitHub token file found"))
    @patch("weekly_recap.preflight.check_jira_token", return_value=None)
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value=None)
    def test_all_pass(self, mock_graph, mock_jira, mock_gh, fake_root: Path):
        result = run_preflight(fake_root)
        assert result.ready is True
        assert result.errors == []

    @patch("weekly_recap.preflight.check_github_auth", return_value=("missing", "GH_TOKEN_MISSING: ..."))
    @patch("weekly_recap.preflight.check_jira_token", return_value=None)
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value=None)
    def test_fails_when_gh_missing(self, mock_graph, mock_jira, mock_gh, fake_root: Path):
        result = run_preflight(fake_root)
        assert result.ready is False
        assert any("GH_TOKEN_MISSING" in e for e in result.errors)

    @patch("weekly_recap.preflight.check_github_auth", return_value=("ready", "GitHub token file found"))
    @patch("weekly_recap.preflight.check_jira_token", return_value=None)
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value="MS_GRAPH_TOKEN: ...")
    def test_fails_when_token_missing(self, mock_graph, mock_jira, mock_gh, fake_root: Path):
        result = run_preflight(fake_root)
        assert result.ready is False
        assert any("MS_GRAPH_TOKEN" in e for e in result.errors)

    @patch("weekly_recap.preflight.check_github_auth", return_value=("ready", "GitHub token file found"))
    @patch("weekly_recap.preflight.check_jira_token", return_value=None)
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value=None)
    def test_fails_when_setup_not_run(self, mock_graph, mock_jira, mock_gh, tmp_path: Path):
        # No .setup-complete, no user-config.json
        result = run_preflight(tmp_path)
        assert result.ready is False
        assert any("SETUP_NOT_RUN" in e for e in result.errors)
        assert any("CONFIG_MISSING" in e for e in result.errors)

    @patch("weekly_recap.preflight.check_github_auth", return_value=("invalid", "GH_TOKEN_INVALID: token file exists but is empty"))
    @patch("weekly_recap.preflight.check_jira_token", return_value=None)
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value=None)
    def test_fails_when_gh_token_invalid(self, mock_graph, mock_jira, mock_gh, fake_root: Path):
        result = run_preflight(fake_root)
        assert result.ready is False
        assert any("GH_TOKEN_INVALID" in e for e in result.errors)

    @patch("weekly_recap.preflight.check_github_auth", return_value=("ready", "GitHub token file found"))
    @patch("weekly_recap.preflight.check_jira_token", return_value="JIRA_TOKEN_MISSING: ...")
    @patch("weekly_recap.preflight.check_ms_graph_token", return_value=None)
    def test_fails_when_jira_token_missing(self, mock_graph, mock_jira, mock_gh, fake_root: Path):
        result = run_preflight(fake_root)
        assert result.ready is False
        assert any("JIRA_TOKEN_MISSING" in e for e in result.errors)


# --- check_github_auth ---


class TestCheckGithubAuth:
    def test_ready_when_token_file_exists_and_nonempty(self, tmp_path: Path):
        token_dir = tmp_path / ".config" / ".github"
        token_dir.mkdir(parents=True)
        (token_dir / ".token").write_text("ghp_abc123\n", encoding="utf-8")

        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            status, message = check_github_auth()
            assert status == "ready"
            assert "token file found" in message

    def test_invalid_when_token_file_exists_but_empty(self, tmp_path: Path):
        token_dir = tmp_path / ".config" / ".github"
        token_dir.mkdir(parents=True)
        (token_dir / ".token").write_text("  \n  ", encoding="utf-8")

        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            status, message = check_github_auth()
            assert status == "invalid"
            assert "GH_TOKEN_INVALID" in message

    def test_ready_when_token_file_missing_but_gh_cli_authenticated(self, tmp_path: Path):
        # No token file exists
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            with patch("shutil.which", return_value="/usr/local/bin/gh"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value.returncode = 0
                    status, message = check_github_auth()
                    assert status == "ready"
                    assert "gh CLI authenticated" in message

    def test_missing_when_neither_available(self, tmp_path: Path):
        # No token file, no gh CLI
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            with patch("shutil.which", return_value=None):
                status, message = check_github_auth()
                assert status == "missing"
                assert "GH_TOKEN_MISSING" in message
                assert "~/.config/.github/.token" in message
                assert "https://github.com/settings/tokens" in message

    def test_missing_when_gh_cli_exists_but_not_authenticated(self, tmp_path: Path):
        # No token file, gh CLI present but auth fails
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            with patch("shutil.which", return_value="/usr/local/bin/gh"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value.returncode = 1
                    status, message = check_github_auth()
                    assert status == "missing"
                    assert "GH_TOKEN_MISSING" in message


# --- check_jira_token ---


class TestCheckJiraToken:
    def test_passes_when_token_exists_and_nonempty(self, tmp_path: Path):
        token_dir = tmp_path / ".config" / ".jira"
        token_dir.mkdir(parents=True)
        (token_dir / ".token").write_text("ATATT3xFfGF0xxx\n", encoding="utf-8")

        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            assert check_jira_token() is None

    def test_fails_when_token_file_missing(self, tmp_path: Path):
        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            result = check_jira_token()
            assert result is not None
            assert "JIRA_TOKEN_MISSING" in result
            assert "~/.config/.jira/.token" in result
            assert "https://id.atlassian.com/manage-profile/security/api-tokens" in result

    def test_fails_when_token_file_empty(self, tmp_path: Path):
        token_dir = tmp_path / ".config" / ".jira"
        token_dir.mkdir(parents=True)
        (token_dir / ".token").write_text("  \n  ", encoding="utf-8")

        with patch("weekly_recap.preflight.Path.home", return_value=tmp_path):
            result = check_jira_token()
            assert result is not None
            assert "JIRA_TOKEN_MISSING" in result
            assert "empty" in result
