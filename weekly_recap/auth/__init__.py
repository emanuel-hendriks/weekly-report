"""Shared authentication module for weekly-recap agent.

Public API:
    get_github_token() -> str | None
    get_github_token_for_org(org: str) -> str | None
    prepare_jira_auth(config: dict) -> tuple[str, str] | None
    ensure_graph_token (module re-export)
    setup_graph_token (module re-export)
"""

from __future__ import annotations

from weekly_recap.auth import ensure_graph_token, setup_graph_token  # noqa: F401
from weekly_recap.auth.github_auth import get_github_token as _get_github_token
from weekly_recap.auth.github_auth import get_github_token_for_org as _get_github_token_for_org
from weekly_recap.auth.jira_auth import prepare_auth as _prepare_jira_auth


def get_github_token() -> str | None:
    """Get GitHub token. Returns None on failure (no exception propagated)."""
    try:
        return _get_github_token()
    except Exception:
        return None


def get_github_token_for_org(org: str) -> str | None:
    """Get GitHub token for a specific org. Returns None on failure."""
    try:
        return _get_github_token_for_org(org)
    except Exception:
        return None


def prepare_jira_auth(config: dict) -> tuple[str, str] | None:
    """Prepare Jira auth. Returns None on failure (no exception propagated)."""
    try:
        return _prepare_jira_auth(config)
    except Exception:
        return None
