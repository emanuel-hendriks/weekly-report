#!/usr/bin/env python3
"""
Fetch changelog/history for all Jira issues in the weekly recap cache.

Reads issue keys from the cache, fetches the changelog (assignee and status
transitions) for each ticket, and writes results to
reports/.cache/jira-history.json.

Usage:
    python3 -m weekly_recap.fetchers.fetch_jira_history

Output:
    Writes history data to reports/.cache/jira-history.json

    Format:
    {
      "AWS-18933": {
        "created": "2026-05-20",
        "transitions": [
          {
            "date": "2026-05-22T10:15",
            "author": "John Doe",
            "field": "status",
            "from": "Open",
            "to": "In Progress"
          },
          {
            "date": "2026-05-22T10:15",
            "author": "Jane Smith",
            "field": "assignee",
            "from": "Unassigned",
            "to": "John Doe"
          }
        ]
      }
    }

Exit codes:
    0 — success
    1 — authentication failed or token missing
    2 — API error (partial results written)
"""

import json
import pathlib
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from weekly_recap.auth import prepare_jira_auth

# File paths
PROCESSED_TICKETS_FILE = pathlib.Path("reports/.cache/processed-tickets.json")
JIRA_ISSUES_FILE = pathlib.Path("reports/.cache/jira-issues.json")
OUTPUT_FILE = pathlib.Path("reports/.cache/jira-history.json")

# Fields we care about in the changelog
TRACKED_FIELDS = {"status", "assignee"}

# SSL context
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()


def _load_config() -> dict:
    """Load user-config.json from project root."""
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_ticket_keys() -> list[str]:
    """Extract ticket keys from the cached data."""
    if PROCESSED_TICKETS_FILE.exists():
        try:
            data = json.loads(PROCESSED_TICKETS_FILE.read_text())
            keys = set()
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for ticket in item.get("tickets", []):
                            if isinstance(ticket, dict) and ticket.get("key"):
                                keys.add(ticket["key"])
                        if item.get("key"):
                            keys.add(item["key"])
            if keys:
                return sorted(keys)
        except (json.JSONDecodeError, IOError):
            pass

    if JIRA_ISSUES_FILE.exists():
        try:
            data = json.loads(JIRA_ISSUES_FILE.read_text())
            if isinstance(data, list):
                return sorted(
                    item["key"] for item in data
                    if isinstance(item, dict) and item.get("key")
                )
        except (json.JSONDecodeError, IOError):
            pass

    return []


def fetch_history_for_ticket(
    ticket_key: str,
    auth_header: str,
    jira_base_url: str,
) -> tuple[str, dict, str | None]:
    """Fetch changelog for a single ticket.

    Returns (ticket_key, result_dict, error_or_none).
    """
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_key}?expand=changelog&fields=created"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
    })

    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return ticket_key, {"created": None, "transitions": []}, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return ticket_key, {"created": None, "transitions": []}, f"Network error: {e.reason}"
    except Exception as e:
        return ticket_key, {"created": None, "transitions": []}, f"Error: {e}"

    # Extract creation date
    created = (data.get("fields", {}).get("created") or "")[:10]

    # Extract changelog transitions
    transitions = []
    histories = data.get("changelog", {}).get("histories", [])

    for entry in histories:
        entry_date = entry.get("created", "")[:16]  # YYYY-MM-DDTHH:MM
        author = entry.get("author", {}).get("displayName", "Unknown")

        for item in entry.get("items", []):
            field = item.get("field", "")
            if field.lower() in TRACKED_FIELDS:
                transitions.append({
                    "date": entry_date,
                    "author": author,
                    "field": field.lower(),
                    "from": item.get("fromString", "") or "",
                    "to": item.get("toString", "") or "",
                })

    return ticket_key, {"created": created, "transitions": transitions}, None


def main():
    """Main entry point."""
    try:
        config = _load_config()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Cannot load user-config.json: {e}", file=sys.stderr)
        sys.exit(1)

    jira_base_url = config.get("jira_url", "").rstrip("/")
    if not jira_base_url:
        print("Error: jira_url not set in user-config.json", file=sys.stderr)
        sys.exit(1)

    auth = prepare_jira_auth(config)
    if auth is None:
        print("Error: Jira authentication is unavailable.", file=sys.stderr)
        sys.exit(1)

    auth_header, email = auth

    ticket_keys = _get_ticket_keys()
    if not ticket_keys:
        print("No ticket keys found in cache. Run 'weekly-recap generate' first.")
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text("{}")
        sys.exit(0)

    print(f"Fetching history for {len(ticket_keys)} tickets...")

    results: dict[str, dict] = {}
    api_errors = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                fetch_history_for_ticket, key, auth_header, jira_base_url
            ): key
            for key in ticket_keys
        }
        for future in as_completed(futures):
            ticket_key, data, error = future.result()
            if error:
                api_errors.append(f"{ticket_key}: {error}")
            results[ticket_key] = data

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Summary
    total_transitions = sum(len(v.get("transitions", [])) for v in results.values())
    print(f"Done: {total_transitions} transitions across {len(ticket_keys)} tickets")
    print(f"Output: {OUTPUT_FILE}")

    if api_errors:
        print(f"\nWarnings ({len(api_errors)} errors):", file=sys.stderr)
        for err in api_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
