"""Jira authentication module.

Reads the Jira API token from ~/.config/.jira/.token and constructs
Base64-encoded Basic auth credentials using the jira_username from config.
"""

from __future__ import annotations

import base64
import pathlib

TOKEN_FILE_PATH = pathlib.Path.home() / ".config" / ".jira" / ".token"
TOKEN_CREATE_URL = "https://id.atlassian.com/manage-profile/security/api-tokens"


class JiraAuthError(Exception):
    """Raised when Jira authentication cannot be prepared.

    Contains: expected file path, API token creation URL, format description,
    and I/O reason (if applicable).
    """

    pass


def _read_token_file() -> str:
    """Read and parse Jira API token from ~/.config/.jira/.token.

    Handles:
    - Whitespace trimming (leading/trailing, including newlines)
    - ``JIRA_API_TOKEN=`` prefix stripping (with optional ``export `` keyword)

    Returns:
        The parsed token string.

    Raises:
        JiraAuthError: If file is missing, unreadable, or empty after parsing.
    """
    if not TOKEN_FILE_PATH.exists():
        raise JiraAuthError(
            f"Jira API token file not found.\n"
            f"  Expected: {TOKEN_FILE_PATH}\n"
            f"  Format: plain text file with token value on a single line\n"
            f"  Create token: {TOKEN_CREATE_URL}\n"
            f"\n"
            f"  Save the token:\n"
            f'    echo "YOUR_TOKEN" > {TOKEN_FILE_PATH}'
        )

    try:
        content = TOKEN_FILE_PATH.read_text(encoding="utf-8")
    except OSError as e:
        raise JiraAuthError(
            f"Cannot read Jira API token file.\n"
            f"  Path: {TOKEN_FILE_PATH}\n"
            f"  Reason: {e}\n"
            f"  Format: plain text file with token value on a single line\n"
            f"  Create token: {TOKEN_CREATE_URL}"
        ) from e

    token = content.strip()

    # Handle 'export JIRA_API_TOKEN=...' prefix
    if token.startswith("export "):
        token = token[len("export ") :]

    # Handle 'JIRA_API_TOKEN=...' prefix
    if token.startswith("JIRA_API_TOKEN="):
        token = token[len("JIRA_API_TOKEN=") :]

    token = token.strip()

    if not token:
        raise JiraAuthError(
            f"Jira API token file is empty.\n"
            f"  Path: {TOKEN_FILE_PATH}\n"
            f"  Format: plain text file with token value on a single line\n"
            f"  Create token: {TOKEN_CREATE_URL}\n"
            f"\n"
            f"  Save the token:\n"
            f'    echo "YOUR_TOKEN" > {TOKEN_FILE_PATH}'
        )

    return token


def prepare_auth(config: dict) -> tuple[str, str]:
    """Prepare Jira Basic auth credentials.

    Args:
        config: Parsed user-config.json dict (must contain 'jira_username').

    Returns:
        Tuple of (base64_auth_header, email) where auth_header is the raw
        Base64 string without the "Basic " scheme prefix.

    Raises:
        JiraAuthError: If token file is missing/empty/unreadable or
            jira_username is missing/empty from config.
    """
    token = _read_token_file()

    # Validate jira_username from config
    if not isinstance(config, dict):
        raise JiraAuthError(
            "Invalid configuration: expected a dictionary.\n"
            "  Required field: 'jira_username' in user-config.json"
        )

    email = config.get("jira_username")

    if email is None:
        raise JiraAuthError(
            "Missing 'jira_username' in configuration.\n"
            "  Required: 'jira_username' field in user-config.json\n"
            "  This should be your Jira email address."
        )

    if not isinstance(email, str) or not email.strip():
        raise JiraAuthError(
            "Invalid 'jira_username' in configuration: value is empty or not a string.\n"
            "  Required: 'jira_username' field in user-config.json\n"
            "  This should be your Jira email address."
        )

    email = email.strip()

    # Construct Base64 auth header: base64("{email}:{token}")
    credentials = f"{email}:{token}"
    auth_header = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    return auth_header, email
