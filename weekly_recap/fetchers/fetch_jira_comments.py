#!/usr/bin/env python3
"""
Fetch comments for Jira issues from the weekly recap cache.

Reads issue keys from the processed tickets cache (reports/.cache/processed-tickets.json)
or from the raw Jira issues cache (reports/.cache/jira-issues.json), fetches comments
for each ticket via the Jira REST API, and writes the results to
reports/.cache/jira-comments.json.

Usage:
    python3 -m weekly_recap.fetchers.fetch_jira_comments

Output:
    Writes comments to reports/.cache/jira-comments.json

Exit codes:
    0 — success (including zero comments)
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
OUTPUT_FILE = pathlib.Path("reports/.cache/jira-comments.json")

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
    """Extract ticket keys from the cached data.

    Tries processed-tickets.json first, falls back to jira-issues.json.
    """
    if PROCESSED_TICKETS_FILE.exists():
        try:
            data = json.loads(PROCESSED_TICKETS_FILE.read_text())
            keys = set()
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        # processed-tickets has "tickets" list with key objects
                        for ticket in item.get("tickets", []):
                            if isinstance(ticket, dict) and ticket.get("key"):
                                keys.add(ticket["key"])
                        # Or it might be a flat list of issues
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
                elif inline_type == "emoji":
                    parts.append(inline.get("attrs", {}).get("shortName", ""))
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

        elif block_type == "heading":
            for inline in block.get("content", []):
                if inline.get("type") == "text":
                    parts.append(inline.get("text", ""))
            parts.append("\n")

        elif block_type == "blockquote":
            if block.get("content"):
                quoted = _extract_text_from_adf(block["content"]).strip()
                parts.append(f"> {quoted}\n")

        elif block_type == "table":
            # Simplified table extraction
            for row in block.get("content", []):
                if row.get("type") == "tableRow":
                    cells = []
                    for cell in row.get("content", []):
                        if cell.get("content"):
                            cells.append(_extract_text_from_adf(cell["content"]).strip())
                    parts.append(" | ".join(cells) + "\n")

        elif block.get("content"):
            # Generic fallback for nested content
            parts.append(_extract_text_from_adf(block["content"]))

    return "".join(parts)


def fetch_comments_for_ticket(
    ticket_key: str,
    auth_header: str,
    jira_base_url: str,
) -> tuple[str, list[dict], str | None]:
    """Fetch comments for a single ticket.

    Returns (ticket_key, comments_list, error_or_none).
    """
    url = f"{jira_base_url}/rest/api/3/issue/{ticket_key}/comment"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
    })

    try:
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return ticket_key, [], f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return ticket_key, [], f"Network error: {e.reason}"
    except Exception as e:
        return ticket_key, [], f"Error: {e}"

    comments = []
    for c in data.get("comments", []):
        body_text = ""
        if c.get("body") and c["body"].get("content"):
            body_text = _extract_text_from_adf(c["body"]["content"]).strip()

        if not body_text:
            continue

        author = c.get("author", {}).get("displayName", "Unknown")
        created = c.get("created", "")[:10]

        comments.append({
            "author": author,
            "date": created,
            "body": body_text,
        })

    return ticket_key, comments, None


def main():
    """Main entry point."""
    # Load config
    try:
        config = _load_config()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Cannot load user-config.json: {e}", file=sys.stderr)
        sys.exit(1)

    jira_base_url = config.get("jira_url", "").rstrip("/")
    if not jira_base_url:
        print("Error: jira_url not set in user-config.json", file=sys.stderr)
        sys.exit(1)

    # Prepare auth
    auth = prepare_jira_auth(config)
    if auth is None:
        print("Error: Jira authentication is unavailable.", file=sys.stderr)
        sys.exit(1)

    auth_header, email = auth

    # Get ticket keys from cache
    ticket_keys = _get_ticket_keys()
    if not ticket_keys:
        print("No ticket keys found in cache. Run 'weekly-recap generate' first.")
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text("{}")
        sys.exit(0)

    print(f"Fetching comments for {len(ticket_keys)} tickets...")

    # Fetch comments in parallel
    results: dict[str, list[dict]] = {}
    api_errors = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(
                fetch_comments_for_ticket, key, auth_header, jira_base_url
            ): key
            for key in ticket_keys
        }
        for future in as_completed(futures):
            ticket_key, comments, error = future.result()
            if error:
                api_errors.append(f"{ticket_key}: {error}")
                results[ticket_key] = []
            else:
                results[ticket_key] = comments

    # Write output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Summary
    total_comments = sum(len(v) for v in results.values())
    tickets_with_comments = sum(1 for v in results.values() if v)
    print(f"Done: {total_comments} comments across {tickets_with_comments}/{len(ticket_keys)} tickets")
    print(f"Output: {OUTPUT_FILE}")

    if api_errors:
        print(f"\nWarnings ({len(api_errors)} errors):", file=sys.stderr)
        for err in api_errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
