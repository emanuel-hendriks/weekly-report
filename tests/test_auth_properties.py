# Feature: auth-consolidation, Property 1: GitHub token parsing correctness
"""Property-based tests for auth consolidation.

Validates: Requirements 1.1, 1.2, 1.3, 1.9
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from weekly_recap.auth.github_auth import _read_token_file

# Strategy: non-empty strings without newlines (tokens are extracted from first non-empty line)
# Include alphanumeric + common PAT characters like underscores, hyphens
token_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=100,
)


@given(token=token_strategy)
@settings(max_examples=100)
def test_github_token_bare(token: str) -> None:
    """Property 1: bare token in file is parsed correctly.

    **Validates: Requirements 1.1, 1.2**
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(token + "\n")
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch(
            "weekly_recap.auth.github_auth.TOKEN_FILE_PATH", tmp_path
        ):
            result = _read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(token=token_strategy)
@settings(max_examples=100)
def test_github_token_with_prefix(token: str) -> None:
    """Property 1: GITHUB_TOKEN=value format is parsed correctly.

    **Validates: Requirements 1.3**
    """
    content = f"GITHUB_TOKEN={token}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch(
            "weekly_recap.auth.github_auth.TOKEN_FILE_PATH", tmp_path
        ):
            result = _read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(token=token_strategy)
@settings(max_examples=100)
def test_github_token_with_double_quotes(token: str) -> None:
    """Property 1: GITHUB_TOKEN="value" format is parsed correctly.

    **Validates: Requirements 1.3**
    """
    content = f'GITHUB_TOKEN="{token}"\n'
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch(
            "weekly_recap.auth.github_auth.TOKEN_FILE_PATH", tmp_path
        ):
            result = _read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(token=token_strategy)
@settings(max_examples=100)
def test_github_token_with_single_quotes(token: str) -> None:
    """Property 1: GITHUB_TOKEN='value' format is parsed correctly.

    **Validates: Requirements 1.3**
    """
    content = f"GITHUB_TOKEN='{token}'\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch(
            "weekly_recap.auth.github_auth.TOKEN_FILE_PATH", tmp_path
        ):
            result = _read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(
    token=token_strategy,
    leading_ws=st.text(alphabet=" \t", min_size=0, max_size=5),
    trailing_ws=st.text(alphabet=" \t", min_size=0, max_size=5),
    leading_newlines=st.integers(min_value=0, max_value=3),
    trailing_newlines=st.integers(min_value=0, max_value=3),
)
@settings(max_examples=100)
def test_github_token_with_whitespace_padding(
    token: str,
    leading_ws: str,
    trailing_ws: str,
    leading_newlines: int,
    trailing_newlines: int,
) -> None:
    """Property 1: token with whitespace/newline padding is parsed correctly.

    **Validates: Requirements 1.2, 1.9**
    """
    # Build content with leading empty lines, whitespace around token, trailing newlines
    content = "\n" * leading_newlines + leading_ws + token + trailing_ws + "\n" * trailing_newlines
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch(
            "weekly_recap.auth.github_auth.TOKEN_FILE_PATH", tmp_path
        ):
            result = _read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


# Feature: auth-consolidation, Property 3: Jira Basic auth encoding roundtrip
# Validates: Requirements 2.3, 2.9

import base64
import string

from weekly_recap.auth.jira_auth import prepare_auth

# Strategy for email: non-empty ASCII strings typical in email addresses
_email_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + "@._-",
    min_size=1,
)

# Strategy for token: non-empty text without newlines (tokens are single-line)
_token_strategy = st.text(
    alphabet=string.ascii_letters + string.digits + "+-_=./!@#$%^&*()",
    min_size=1,
)


@given(email=_email_strategy, token=_token_strategy)
@settings(max_examples=100)
def test_jira_basic_auth_encoding_roundtrip(email: str, token: str) -> None:
    """Property 3: base64-encoding of {email}:{token} roundtrips correctly.

    For any non-empty (email, token) pair:
    - Mocking _read_token_file to return the token
    - Calling prepare_auth({"jira_username": email})
    - Base64-decoding the first returned element should equal "{email}:{token}"
    - The second returned element should equal the (stripped) email

    **Validates: Requirements 2.3, 2.9**
    """
    with patch(
        "weekly_recap.auth.jira_auth._read_token_file", return_value=token
    ):
        auth_header, returned_email = prepare_auth({"jira_username": email})

    # Verify base64 roundtrip: decode auth_header and check it matches email:token
    decoded = base64.b64decode(auth_header).decode("utf-8")
    assert decoded == f"{email}:{token}", (
        f"Expected '{email}:{token}', got '{decoded}'"
    )

    # Verify returned email matches input (after strip)
    assert returned_email == email.strip()


# Feature: auth-consolidation, Property 2: Jira token parsing correctness
# **Validates: Requirements 2.1, 2.4**

from weekly_recap.auth.jira_auth import _read_token_file as _jira_read_token_file

# Strategy: non-empty strings without newlines, using same safe alphabet as token_strategy
_jira_token_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=100,
)


@given(token=_jira_token_strategy)
@settings(max_examples=100)
def test_jira_token_bare(token: str) -> None:
    """Property 2: Bare token written to file is parsed correctly.

    **Validates: Requirements 2.1**
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(token + "\n")
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH", tmp_path):
            result = _jira_read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(token=_jira_token_strategy)
@settings(max_examples=100)
def test_jira_token_with_prefix(token: str) -> None:
    """Property 2: Token with JIRA_API_TOKEN= prefix is parsed correctly.

    **Validates: Requirements 2.4**
    """
    content = f"JIRA_API_TOKEN={token}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH", tmp_path):
            result = _jira_read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(token=_jira_token_strategy)
@settings(max_examples=100)
def test_jira_token_with_export_prefix(token: str) -> None:
    """Property 2: Token with export JIRA_API_TOKEN= prefix is parsed correctly.

    **Validates: Requirements 2.4**
    """
    content = f"export JIRA_API_TOKEN={token}\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH", tmp_path):
            result = _jira_read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)


@given(
    token=_jira_token_strategy,
    leading_ws=st.text(alphabet=" \t", min_size=0, max_size=5),
    trailing_ws=st.text(alphabet=" \t\n", min_size=0, max_size=5),
)
@settings(max_examples=100)
def test_jira_token_with_whitespace(
    token: str, leading_ws: str, trailing_ws: str
) -> None:
    """Property 2: Token with leading/trailing whitespace is parsed correctly.

    **Validates: Requirements 2.1**
    """
    content = leading_ws + token + trailing_ws
    with tempfile.NamedTemporaryFile(mode="w", suffix=".token", delete=False) as f:
        f.write(content)
        f.flush()
        tmp_path = Path(f.name)

    try:
        with patch("weekly_recap.auth.jira_auth.TOKEN_FILE_PATH", tmp_path):
            result = _jira_read_token_file()
        assert result == token, f"Expected {token!r}, got {result!r}"
    finally:
        tmp_path.unlink(missing_ok=True)
