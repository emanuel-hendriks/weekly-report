#!/usr/bin/env python3
"""Preflight check for weekly-recap agent.

Validates that the environment is fully configured and ready to generate recaps.
Exit code 0 = ready. Exit code 1 = not ready (output explains what's missing).

The agent MUST run this before every recap generation.
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PreflightResult:
    """Result of a preflight check run."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return len(self.errors) == 0


def check_setup_complete(root: Path) -> str | None:
    """Check that .setup-complete sentinel exists."""
    if not (root / ".setup-complete").exists():
        return "SETUP_NOT_RUN: Setup has not been completed. Run: ./setup.sh"
    return None


def check_user_config(root: Path) -> str | None:
    """Check that user-config.json exists and has real values."""
    config_path = root / "user-config.json"
    if not config_path.exists():
        return "CONFIG_MISSING: user-config.json not found. Copy the template: cp user-config.json.template user-config.json"

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "CONFIG_MISSING: user-config.json is not valid JSON. Fix or recreate from template."

    placeholders = []
    if config.get("name", "") in ("", "Your Name"):
        placeholders.append("name")
    if config.get("jira_username", "") in ("", "your.email@company.com", "your.email@company.com"):
        placeholders.append("jira_username")
    if config.get("github_handle", "") in ("", "your-github-handle"):
        placeholders.append("github_handle")
    if config.get("calendar_email", "") in ("", "your.email@company.com", "your.email@company.com"):
        placeholders.append("calendar_email")
    if not config.get("github_orgs", []):
        placeholders.append("github_orgs")
    if not config.get("ms_graph_tenant_id", ""):
        placeholders.append("ms_graph_tenant_id")
    if not config.get("ms_graph_client_id", ""):
        placeholders.append("ms_graph_client_id")

    if placeholders:
        return f"CONFIG_PLACEHOLDER: user-config.json contains placeholder values in fields: {','.join(placeholders)}. Update with your real data."

    # Validate format of personal fields
    invalid = []
    jira_user = config.get("jira_username", "")
    if "@" not in jira_user:
        invalid.append(f"jira_username ('{jira_user}' is not a valid email)")
    github_handle = config.get("github_handle", "")
    if " " in github_handle or "@" in github_handle:
        invalid.append(f"github_handle ('{github_handle}' should be a GitHub username, not an email)")
    calendar_email = config.get("calendar_email", "")
    if calendar_email and "@" not in calendar_email:
        invalid.append(f"calendar_email ('{calendar_email}' is not a valid email)")

    if invalid:
        return f"CONFIG_INVALID: user-config.json has invalid values: {'; '.join(invalid)}"
    return None


def check_github_auth() -> tuple[str, str]:
    """Check GitHub authentication via token file or gh CLI fallback.

    Returns:
        (status, message) where status is "ready", "invalid", or "missing".
    """
    # Step 1: Check token file
    token_file = Path.home() / ".config" / ".github" / ".token"
    if token_file.exists():
        try:
            content = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            content = ""
        if content:
            return ("ready", "GitHub token file found")
        else:
            return ("invalid", "GH_TOKEN_INVALID: token file exists but is empty (~/.config/.github/.token)")

    # Step 2: Fallback to gh CLI
    if shutil.which("gh"):
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return ("ready", "gh CLI authenticated (token file recommended)")
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Step 3: Neither available
    return (
        "missing",
        "GH_TOKEN_MISSING: No GitHub authentication found. "
        "Create a personal access token at https://github.com/settings/tokens "
        "and save it to ~/.config/.github/.token",
    )


def check_gh_cli() -> tuple[str | None, str | None]:
    """Check GitHub CLI is installed and authenticated. Returns (error, warning).

    .. deprecated::
        Use check_github_auth() instead. This function is kept for backward
        compatibility but is no longer called in the default preflight flow.
    """
    if not shutil.which("gh"):
        return "GH_CLI_MISSING: GitHub CLI (gh) not found. Install from https://cli.github.com/", None

    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return "GH_AUTH_FAILED: GitHub CLI is not authenticated. Run: gh auth login", None
    except (subprocess.TimeoutExpired, OSError):
        return "GH_AUTH_FAILED: GitHub CLI auth check timed out or failed. Run: gh auth login", None

    return None, None


def check_python3() -> str | None:
    """Check Python 3 is available."""
    if not shutil.which("python3"):
        return "PYTHON3_MISSING: Python 3 is required. Install from https://www.python.org/downloads/"
    return None


def check_jira_token() -> str | None:
    """Check Jira API token file exists and is non-empty."""
    token_path = Path.home() / ".config" / ".jira" / ".token"
    if not token_path.exists():
        return (
            "JIRA_TOKEN_MISSING: Jira API token not found at ~/.config/.jira/.token. "
            "Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens "
            "and save it to ~/.config/.jira/.token"
        )
    try:
        content = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return "JIRA_TOKEN_MISSING: Cannot read ~/.config/.jira/.token (permission error)"
    if not content:
        return "JIRA_TOKEN_MISSING: Jira token file exists but is empty (~/.config/.jira/.token)"
    return None


def check_ms_graph_token() -> str | None:
    """Check MS Graph token file exists."""
    token_path = Path.home() / ".ms-graph-tokens.json"
    if not token_path.exists():
        return "MS_GRAPH_TOKEN: MS Graph token file missing (~/.ms-graph-tokens.json). Run: python3 -m weekly_recap.auth.setup_graph_token"
    return None


def run_preflight(root: Path | None = None, fast: bool = False) -> PreflightResult:
    """Run all preflight checks and return the result.

    Args:
        root: Project root directory. Defaults to the repo root.
        fast: If True, skip slow network checks (gh auth, acli auth).
              Used when called internally from generate (fetchers will
              fail with clear errors if auth is broken).
    """
    if root is None:
        root = ROOT

    result = PreflightResult()

    # 1. Setup complete
    err = check_setup_complete(root)
    if err:
        result.errors.append(err)

    # 2. User config
    err = check_user_config(root)
    if err:
        result.errors.append(err)

    if not fast:
        # 3-4. GitHub auth (token file first, gh CLI fallback)
        gh_status, gh_message = check_github_auth()
        if gh_status == "invalid":
            result.errors.append(gh_message)
        elif gh_status == "missing":
            result.errors.append(gh_message)
        # "ready" → no error

        # 5. Python 3
        err = check_python3()
        if err:
            result.errors.append(err)
    else:
        # Fast mode: just check token file or gh on PATH (no auth verification)
        token_file = Path.home() / ".config" / ".github" / ".token"
        if not token_file.exists() and not shutil.which("gh"):
            result.errors.append(
                "GH_TOKEN_MISSING: No GitHub authentication found. "
                "Create a personal access token at https://github.com/settings/tokens "
                "and save it to ~/.config/.github/.token"
            )

    # 6. Jira token file
    err = check_jira_token()
    if err:
        result.errors.append(err)

    # 7. MS Graph token
    err = check_ms_graph_token()
    if err:
        result.errors.append(err)

    return result


def main(quiet: bool = False) -> int:
    """CLI entry point. Prints status and returns exit code.

    Args:
        quiet: If True, suppress output on success. On failure, always prints.
    """
    result = run_preflight()

    if result.ready:
        if not quiet:
            print("✅ READY")
            if result.warnings:
                print()
                for w in result.warnings:
                    print(f"⚠️  {w}")
        return 0
    else:
        if not quiet:
            print("❌ NOT_READY")
            print()
            for e in result.errors:
                print(f"❌ {e}")
            if result.warnings:
                print()
                for w in result.warnings:
                    print(f"⚠️  {w}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
