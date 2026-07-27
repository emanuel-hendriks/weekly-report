"""GitHub authentication module.

Resolves a GitHub Personal Access Token from file or `gh` CLI fallback.

Token file path: ~/.config/.github/.token
Fallback: subprocess call to `gh auth token` (deprecated, with warning).
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

TOKEN_DIR = pathlib.Path.home() / ".config" / ".github"
TOKEN_FILE_PATH = TOKEN_DIR / ".token"
PAT_CREATION_URL = "https://github.com/settings/tokens"


class GitHubAuthError(Exception):
    """Raised when no valid GitHub token can be obtained.

    The error message includes:
    - Expected file path
    - PAT creation URL
    - Format description
    """

    pass


def _read_token_file() -> str | None:
    """Read and parse token from ~/.config/.github/.token.

    Delegates to _read_token_file_at with the default token path.

    Returns:
        The parsed token string, or None if the file is missing,
        unreadable, or produces an empty value.
    """
    return _read_token_file_at(TOKEN_FILE_PATH)


def _gh_cli_fallback() -> str | None:
    """Attempt to get token via `gh auth token` subprocess.

    - 10-second timeout
    - Writes deprecation notice to stderr on success
    - Returns None on failure (non-zero exit, timeout, command not found)

    Returns:
        The token string from gh CLI, or None on failure.
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    except OSError:
        return None

    if result.returncode != 0:
        return None

    token = result.stdout.strip()
    if not token:
        return None

    # Write deprecation notice to stderr on success
    print(
        f"[DEPRECATION] gh CLI fallback used for GitHub token. "
        f"Please save your token to {TOKEN_FILE_PATH} instead.",
        file=sys.stderr,
    )

    return token


def get_github_token() -> str:
    """Resolve a GitHub token.

    Resolution order:
    1. Read from ~/.config/.github/.token (strip whitespace, handle
       GITHUB_TOKEN= prefix with optional quotes)
    2. Fallback: subprocess `gh auth token` (with 10s timeout,
       deprecation warning on stderr)

    Returns:
        Non-empty token string.

    Raises:
        GitHubAuthError: If both sources fail or produce empty token.
    """
    # Try token file first
    token = _read_token_file()
    if token:
        return token

    # Fallback to gh CLI
    token = _gh_cli_fallback()
    if token:
        return token

    # Both failed — raise with guidance
    raise GitHubAuthError(
        f"Error: GitHub token not found.\n"
        f"  Expected: {TOKEN_FILE_PATH}\n"
        f"  Format: plain text file with token value on a single line\n"
        f"  Create token: {PAT_CREATION_URL}\n"
        f"\n"
        f"  Save the token:\n"
        f'    echo "YOUR_TOKEN" > {TOKEN_FILE_PATH}'
    )


def get_github_token_for_org(org: str) -> str:
    """Resolve a GitHub token for a specific org.

    Resolution order:
    1. Read from ~/.config/.github/.token-{org} (org-specific token)
    2. Fallback: get_github_token() (default token)

    Args:
        org: GitHub organization name (e.g., "your-company-wam").

    Returns:
        Non-empty token string.

    Raises:
        GitHubAuthError: If no token can be resolved.
    """
    org_token_path = TOKEN_DIR / f".token-{org}"
    token = _read_token_file_at(org_token_path)
    if token:
        return token

    # Fallback to default token
    return get_github_token()


def _read_token_file_at(path: pathlib.Path) -> str | None:
    """Read and parse token from a given file path.

    Handles:
    - First non-empty line extraction
    - Whitespace trimming
    - GITHUB_TOKEN= prefix stripping (with optional single/double quotes)

    Returns:
        The parsed token string, or None if the file is missing,
        unreadable, or produces an empty value.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return None

    # Extract first non-empty line
    token_line: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            token_line = stripped
            break

    if token_line is None:
        return None

    # Handle GITHUB_TOKEN= prefix
    if token_line.startswith("GITHUB_TOKEN="):
        token_value = token_line[len("GITHUB_TOKEN="):]
        if (
            len(token_value) >= 2
            and token_value[0] in ("'", '"')
            and token_value[-1] == token_value[0]
        ):
            token_value = token_value[1:-1]
    else:
        token_value = token_line

    token_value = token_value.strip()
    if not token_value:
        return None

    return token_value
