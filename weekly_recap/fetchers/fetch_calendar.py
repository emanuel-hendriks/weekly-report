#!/usr/bin/env python3
"""
Fetch calendar events from MS Graph and write processed results to a temp file.

Usage:
    python3 -m weekly_recap.fetchers.fetch_calendar START_DATE END_DATE
    python3 -m weekly_recap.fetchers.fetch_calendar 2026-04-10 2026-04-16

Output:
    Writes processed events to /tmp/weekly-recap-calendar.json
    Prints only a summary line to stdout (e.g., "4 events")
    Tokens and raw API responses never appear in stdout/stderr.

Exit codes:
    0 — success (events written, or zero events)
    1 — token refresh failed, device code flow required
    2 — token file missing
    3 — API error
"""

import json, pathlib, ssl, sys, urllib.error, urllib.parse, urllib.request

# SSL context — macOS Python often lacks system certs
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

TOKEN_FILE = pathlib.Path.home() / ".ms-graph-tokens.json"
SCOPES = "User.Read Calendars.ReadWrite Schedule.Read.All offline_access"
OUTPUT_FILE = pathlib.Path("reports/.cache/calendar.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_graph_config() -> tuple[str, str]:
    """Load MS Graph tenant_id and client_id from user-config.json."""
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("ms_graph_tenant_id", ""), config.get("ms_graph_client_id", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return "", ""


def load_tokens():
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, KeyError):
        return None


def refresh_token(tokens):
    """Refresh the access token silently. Returns new access_token or None."""
    rt = tokens.get("refresh_token")
    if not rt:
        return None

    tenant_id, client_id = _load_graph_config()
    if not tenant_id or not client_id:
        return None

    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "scope": SCOPES,
    }).encode()

    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data=data, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
        result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            result = json.loads(e.read())
        except Exception:
            return None
    except Exception:
        return None

    if "access_token" in result:
        new_tokens = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token", rt),
            "expires_in": result.get("expires_in", 3600),
            "scope": result.get("scope", ""),
        }
        TOKEN_FILE.write_text(json.dumps(new_tokens, indent=2))
        return result["access_token"]
    return None


def fetch_events(access_token, start_date, end_date):
    """Fetch all calendar events for the period. Returns list of events or raises."""
    url = (
        f"https://graph.microsoft.com/v1.0/me/calendarView"
        f"?startDateTime={start_date}T00:00:00"
        f"&endDateTime={end_date}T23:59:59"
        f"&$top=50"
        f"&$orderby=start/dateTime"
        f"&$select=subject,start,end,attendees,isAllDay,isCancelled,organizer,bodyPreview"
    )

    MAX_PAGES = 20  # Safety limit: 20 pages × 50 events = 1000 events max
    all_events = []
    page_count = 0
    while url and page_count < MAX_PAGES:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {access_token}",
            "Prefer": 'outlook.timezone="Europe/Rome"',
        })
        resp = urllib.request.urlopen(req, timeout=15, context=SSL_CTX)
        data = json.loads(resp.read())
        all_events.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        page_count += 1

    return all_events


def process_events(raw_events):
    """Filter cancelled events and extract only the fields we need."""
    processed = []
    for e in raw_events:
        if e.get("isCancelled", False):
            continue
        processed.append({
            "subject": e.get("subject", ""),
            "start": e["start"]["dateTime"][:16],
            "end": e["end"]["dateTime"][:16],
            "isAllDay": e.get("isAllDay", False),
            "bodyPreview": e.get("bodyPreview", ""),
            "attendee_emails": [
                a["emailAddress"]["address"]
                for a in e.get("attendees", [])
            ],
        })
    return processed


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 -m weekly_recap.fetchers.fetch_calendar START_DATE END_DATE", file=sys.stderr)
        sys.exit(1)

    start_date, end_date = sys.argv[1], sys.argv[2]

    # Load token
    tokens = load_tokens()
    if tokens is None:
        print("TOKEN_MISSING")
        sys.exit(2)

    access_token = tokens.get("access_token", "")

    # Try fetching events
    try:
        raw_events = fetch_events(access_token, start_date, end_date)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Token expired — try refresh
            new_token = refresh_token(tokens)
            if new_token is None:
                print("REFRESH_FAILED")
                sys.exit(1)
            try:
                raw_events = fetch_events(new_token, start_date, end_date)
            except Exception:
                print("API_ERROR_AFTER_REFRESH")
                sys.exit(3)
        else:
            print(f"API_ERROR_{e.code}")
            sys.exit(3)
    except Exception:
        # Try refresh as fallback (might be SSL or network issue with stale token)
        new_token = refresh_token(tokens)
        if new_token:
            try:
                raw_events = fetch_events(new_token, start_date, end_date)
            except Exception:
                print("API_ERROR")
                sys.exit(3)
        else:
            print("NETWORK_ERROR")
            sys.exit(3)

    # Process and write
    processed = process_events(raw_events)
    OUTPUT_FILE.write_text(json.dumps(processed, indent=2))
    print(f"{len(processed)} events")


if __name__ == "__main__":
    main()
