#!/usr/bin/env python3
"""
MS Graph token setup via device code flow.

Run this to authenticate with Microsoft Graph and save the token.
After that, ensure_graph_token.py handles automatic refresh.

Usage:
    python3 scripts/setup_graph_token.py
"""

import json, pathlib, ssl, time, urllib.request, urllib.parse

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = None

TOKEN_FILE = pathlib.Path.home() / ".ms-graph-tokens.json"
SCOPES = (
    "User.Read Calendars.ReadWrite Files.ReadWrite.All Schedule.Read.All "
    "Sites.ReadWrite.All Mail.Read Mail.ReadWrite Mail.Send "
    "Chat.ReadWrite ChannelMessage.Read.All ChannelMessage.Send "
    "Channel.ReadBasic.All Team.ReadBasic.All offline_access"
)


def _load_graph_config() -> tuple[str, str, str]:
    """Load MS Graph config from user-config.json. Returns (tenant_id, client_id, email)."""
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return (
            config.get("ms_graph_tenant_id", ""),
            config.get("ms_graph_client_id", ""),
            config.get("calendar_email", ""),
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return "", "", ""


def main():
    tenant_id, client_id, calendar_email = _load_graph_config()
    if not tenant_id or not client_id:
        print("Error: ms_graph_tenant_id and ms_graph_client_id must be set in user-config.json")
        return

    if TOKEN_FILE.exists():
        print(f"Token file already exists at {TOKEN_FILE}")
        resp = input("Overwrite? (y/N): ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return

    # Request device code
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": SCOPES,
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode",
        data=data,
        method="POST",
    )
    resp = urllib.request.urlopen(req, context=SSL_CTX)
    dc = json.loads(resp.read())

    print(f"\n  Go to: https://microsoft.com/devicelogin")
    print(f"  Enter code: {dc['user_code']}")
    if calendar_email:
        print(f"  Sign in as: {calendar_email}\n")
    else:
        print(f"  Sign in with your corporate account\n")
    print("Polling for completion (3 min max)...")

    # Poll for token
    token_data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": dc["device_code"],
    }).encode()

    for i in range(36):
        time.sleep(5)
        token_req = urllib.request.Request(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data=token_data,
            method="POST",
        )
        try:
            token_resp = urllib.request.urlopen(token_req, context=SSL_CTX)
            result = json.loads(token_resp.read())
        except urllib.error.HTTPError as e:
            result = json.loads(e.read())

        if "access_token" in result:
            TOKEN_FILE.write_text(json.dumps({
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", ""),
                "expires_in": result.get("expires_in", 3600),
                "scope": result.get("scope", ""),
            }, indent=2))
            print(f"\n✅ Token saved to {TOKEN_FILE} (after {(i + 1) * 5}s)")
            print("   Calendar is now enabled for the weekly-recap agent.")
            return
        elif result.get("error") != "authorization_pending":
            print(f"\n❌ Error: {result.get('error_description', result)}")
            return

    print("\n❌ Timeout — no response within 3 minutes. Try again.")


if __name__ == "__main__":
    main()
