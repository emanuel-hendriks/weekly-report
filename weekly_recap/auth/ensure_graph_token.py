#!/usr/bin/env python3
"""
Ensure a valid MS Graph access token is available.

Usage:
    python3 scripts/email-calendar/ensure_graph_token.py
    python3 scripts/email-calendar/ensure_graph_token.py --token   # print access_token to stdout

Exit codes:
    0 — token is valid (existing or just refreshed)
    1 — refresh failed, device code flow required
    2 — token file missing, device code flow required

When called with --token, prints ONLY the access_token to stdout (for use in
shell substitution). All status messages go to stderr.
"""

import json, pathlib, socket, ssl, sys, time, urllib.request, urllib.parse

# Prevent HTTP calls from hanging indefinitely in non-TTY environments (e.g. Kiro)
socket.setdefaulttimeout(10)

# Build an SSL context with certifi's CA bundle so we don't depend on the
# system cert store (which may be missing on macOS framework Python installs).
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = None  # fall back to default (works if system certs are present)

TOKEN_FILE = pathlib.Path.home() / ".ms-graph-tokens.json"
SCOPES = (
    "User.Read Calendars.ReadWrite Files.ReadWrite.All Schedule.Read.All "
    "Sites.ReadWrite.All Mail.Read Mail.ReadWrite Mail.Send "
    "Chat.ReadWrite ChannelMessage.Read.All ChannelMessage.Send "
    "Channel.ReadBasic.All Team.ReadBasic.All offline_access"
)


def _load_graph_config() -> tuple[str, str]:
    """Load MS Graph tenant_id and client_id from user-config.json."""
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("ms_graph_tenant_id", ""), config.get("ms_graph_client_id", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return "", ""

# Refresh 5 minutes before actual expiry to avoid race conditions
EXPIRY_BUFFER_SECONDS = 300

print_token_only = "--token" in sys.argv


def log(msg):
    """Print to stderr so stdout stays clean for --token mode."""
    print(msg, file=sys.stderr)


def load_tokens():
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, KeyError):
        return None


def token_is_fresh(tokens):
    """Check if access_token is likely still valid based on file mtime + expires_in."""
    try:
        mtime = TOKEN_FILE.stat().st_mtime
        expires_in = tokens.get("expires_in", 3600)
        remaining = (mtime + expires_in) - time.time()
        if remaining > EXPIRY_BUFFER_SECONDS:
            log(f"Token valid — ~{int(remaining / 60)}min remaining")
            return True
        else:
            log(f"Token expired or expiring soon ({int(remaining)}s remaining)")
            return False
    except Exception:
        return False


def quick_validate(access_token):
    """Optional: hit /me to confirm token actually works. Returns True/False."""
    req = urllib.request.Request(
        "https://graph.microsoft.com/v1.0/me?$select=displayName",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5, context=SSL_CTX)
        data = json.loads(resp.read())
        log(f"Token validated — user: {data.get('displayName', '?')}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log("Token rejected by Graph (401) — will refresh")
            return False
        log(f"Graph returned {e.code} — assuming token is OK (non-auth error)")
        return True
    except Exception as ex:
        log(f"Validation request failed ({ex}) — assuming token is OK")
        return True


def refresh_token(tokens):
    """Attempt to refresh using the refresh_token. Returns new tokens dict or None."""
    rt = tokens.get("refresh_token")
    if not rt:
        log("No refresh_token available")
        return None

    tenant_id, client_id = _load_graph_config()
    if not tenant_id or not client_id:
        log("MS Graph config missing from user-config.json")
        return None

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "scope": SCOPES,
    }).encode()

    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data=data,
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
        result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        result = json.loads(e.read())

    if "access_token" in result:
        new_tokens = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token", rt),
            "expires_in": result.get("expires_in", 3600),
            "scope": result.get("scope", ""),
        }
        TOKEN_FILE.write_text(json.dumps(new_tokens, indent=2))
        log("Token refreshed OK")
        return new_tokens

    err = result.get("error_description", result.get("error", "unknown"))
    log(f"Refresh failed: {err}")
    return None


def main():
    tokens = load_tokens()

    if tokens is None:
        log("Token file missing — run device code flow")
        sys.exit(2)

    # Fast path: check expiry from file metadata (no network call)
    if token_is_fresh(tokens):
        if print_token_only:
            print(tokens["access_token"])
        sys.exit(0)

    # Token looks expired — try refresh first (cheap network call)
    new_tokens = refresh_token(tokens)
    if new_tokens:
        if print_token_only:
            print(new_tokens["access_token"])
        sys.exit(0)

    # Refresh failed — last resort: validate current token anyway
    # (mtime heuristic might be wrong if file was copied/restored)
    if quick_validate(tokens["access_token"]):
        log("Token still works despite mtime — using it")
        if print_token_only:
            print(tokens["access_token"])
        sys.exit(0)

    log("Token invalid and refresh failed — run device code flow")
    sys.exit(1)


if __name__ == "__main__":
    main()
