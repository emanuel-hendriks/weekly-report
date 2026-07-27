#!/usr/bin/env python3
"""
Fetch subtasks for all Jira issues in the weekly recap cache.

Reads issue keys from the cache, fetches subtask info (key, summary, status)
and their comments for each parent ticket, and writes results to
reports/.cache/jira-subtasks.json.

Usage:
    python3 -m weekly_recap.fetchers.fetch_jira_subtasks

Output:
    Writes subtask data to reports/.cache/jira-subtasks.json

    Format:
    {
      "AWS-18933": {
        "subtasks": [
          {
            "key": "AWS-18934",
            "summary": "[DEV] PCA - ...",
            "status": "Done",
            "comments": [...]
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
OUTPUT_FILE = pathlib.Path("reports/.cache/jira-subtasks.json")

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


def _extract_text_from_adf(content: list) -> str:
    """Recursively extract plain text from Atlassian Document Format content."""
    parts = []
    for block in content:
        block_type = block.get("type", "")
        if block_type == "paragraph":
            for inline in block.get("content", []):
                inline_type = inline.get("type", "")
                if inline_type == "text":
                    parts.append(inline.get("text", ""))
                elif inline_type == "mention":
                    parts.append("@" + inline.get("attrs", {}).get("text", ""))
                elif inline_type == "hardBreak":
                    parts.append("\n")
                elif inline_type == "inlineCard":
                    parts.append(inline.get("attrs", {}).get("url", ""))
            parts.append("\n")
        elif block_type == "codeBlock":
            for inline in block.get("content", []):
                if inline.get("type") == "text":
                    parts.append("[code] " + inline.get("text", ""))
            parts.append("\n")
        elif block_type in ("bulletList", "orderedList"):
            for item in block.get("content", []):
                if item.get("type") == "listItem" and item.get("content"):
                    item_text = _extract_text_from_adf(item["content"]).strip()
                    parts.append(f"- {item_text}\n")
        elif block.get("content"):
            parts.append(_extract_text_from_adf(block["content"]))
    return "".join(parts)


def _fetch_subtask_comments(
    subtask_key: str,
    auth_header: str,
    jira_base_url: str,
) -> list[dict]:
    """Fetch comments for a single subtask. Returns list of comment dicts."""
    url = f"{jira_base_url}/rest/api/3/issue/{subtask_key}/comment"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
    })

    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=20)
        data = json.loads(resp.read().decode())
    except Exception:
        return []

    comments = []
    for c in data.get("comments", []):
        body_text = ""
        if c.get("body") and c["body"].get("content"):
            body_text = _extract_text_from_adf(c["body"]["content"]).strip()
        if not body_text:
            continue
        comments.append({
            "author": c.get("author", {}).get("displayName", "Unknown"),
            "date": c.get("created", "")[:10],
            "body": body_text,
        })
    return comments


def fetch_subtasks_for_ticket(
    ticket_key: str,
    auth_header: str,
    jira_base_url: str,
) -> tuple[str, dict, str | None]:
    """Fetch subtasks for a single parent ticket.

    Returns (ticket_key, result_dict, error_or_none).
    """
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_key}?fields=subtasks"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
    })

    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=20)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return ticket_key, {"subtasks": []}, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return ticket_key, {"subtasks": []}, f"Network error: {e.reason}"
    except Exception as e:
        return ticket_key, {"subtasks": []}, f"Error: {e}"

    raw_subtasks = data.get("fields", {}).get("subtasks", [])
    if not raw_subtasks:
        return ticket_key, {"subtasks": []}, None

    subtasks = []
    for st in raw_subtasks:
        key = st.get("key", "")
        summary = st.get("fields", {}).get("summary", "")
        status = st.get("fields", {}).get("status", {}).get("name", "")

        # Fetch comments for this subtask
        comments = _fetch_subtask_comments(key, auth_header, jira_base_url)

        subtasks.append({
            "key": key,
            "summary": summary,
            "status": status,
            "comments": comments,
        })

    return ticket_key, {"subtasks": subtasks}, None


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

    print(f"Fetching subtasks for {len(ticket_keys)} tickets...")

    results: dict[str, dict] = {}
    api_errors = []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(
                fetch_subtasks_for_ticket, key, auth_header, jira_base_url
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
    total_subtasks = sum(len(v.get("subtasks", [])) for v in results.values())
    tickets_with_subtasks = sum(1 for v in results.values() if v.get("subtasks"))
    print(f"Done: {total_subtasks} subtasks across {tickets_with_subtasks}/{len(ticket_keys)} tickets")
    print(f"Output: {OUTPUT_FILE}")

    if api_errors:
        print(f"\nWarnings ({len(api_errors)} errors):", file=sys.stderr)
        for err in api_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
