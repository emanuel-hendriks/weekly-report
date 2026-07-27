#!/usr/bin/env python3
"""Fetch GitHub PR activity using httpx (async HTTP).

Replaces subprocess calls to `gh search prs` with direct GitHub Search API calls.

CLI invocation:
    python3 -m weekly_recap.fetchers.fetch_github_prs <github_handle> <orgs_json> <start_date> <end_date>

Parameters:
    github_handle: GitHub username (e.g., "your-github-username")
    orgs_json: JSON array of org names (e.g., '["your-org-1", "your-company-wam"]')
    start_date: ISO 8601 date (YYYY-MM-DD)
    end_date: ISO 8601 date (YYYY-MM-DD)

Output: reports/.cache/github-prs.json
Exit codes: 0 (success), 1 (CLI/auth error), 2 (API error with partial results)
"""

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

import httpx

from weekly_recap.auth import get_github_token, get_github_token_for_org

GITHUB_API = "https://api.github.com"
MAX_PER_PAGE = 100
REQUEST_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Auth & validation
# ---------------------------------------------------------------------------

def validate_iso_date(date_str: str) -> bool:
    try:
        date.fromisoformat(date_str)
        return True
    except (ValueError, TypeError):
        return False


def validate_inputs(
    github_handle: str, orgs: list[str], start_date: str, end_date: str
) -> str | None:
    if not github_handle or not github_handle.strip():
        return "Error: github_handle must be non-empty."
    if not orgs:
        return "Error: at least one org is required."
    if not validate_iso_date(start_date):
        return f"Error: start_date '{start_date}' is not a valid ISO 8601 date."
    if not validate_iso_date(end_date):
        return f"Error: end_date '{end_date}' is not a valid ISO 8601 date."
    return None


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------

async def search_prs(
    client: httpx.AsyncClient,
    query: str,
) -> tuple[list[dict], str | None]:
    """Execute a GitHub Search API query for PRs. Returns (items, error)."""
    all_items: list[dict] = []

    for page in range(1, 4):  # Max 3 pages (300 PRs per query should be enough)
        try:
            resp = await client.get(
                f"{GITHUB_API}/search/issues",
                params={"q": query, "per_page": MAX_PER_PAGE, "page": page},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException:
            return all_items, "Search timed out"
        except httpx.HTTPError as e:
            return all_items, f"Search failed: {e}"

        if resp.status_code != 200:
            error_msg = resp.json().get("message", "") if resp.text else str(resp.status_code)
            return all_items, f"Search API {resp.status_code}: {error_msg}"

        data = resp.json()
        items = data.get("items", [])
        all_items.extend(items)

        if len(items) < MAX_PER_PAGE:
            break

    return all_items, None


def build_queries(handle: str, org: str, start: str, end: str) -> list[tuple[str, str]]:
    """Build 3 search queries for PRs. Returns list of (query_string, category)."""
    date_range = f"{start}..{end}"
    return [
        (f"type:pr author:{handle} org:{org} created:{date_range}", "created"),
        (f"type:pr author:{handle} org:{org} merged:{date_range}", "merged"),
        (f"type:pr author:{handle} org:{org} closed:{date_range} -is:merged", "closed"),
    ]


def normalize_pr(raw: dict, org: str, category: str) -> dict:
    """Normalize a raw search result to the output schema."""
    # Extract repo name from repository_url
    repo_url = raw.get("repository_url", "")
    repo_name = repo_url.split("/")[-1] if repo_url else ""

    # Dates
    created_at = (raw.get("created_at") or "")[:10]
    closed_at = (raw.get("closed_at") or "")[:10] or None

    # State and category
    if category == "merged":
        state = "closed"
        pr_category = "merged"
        merged_at = closed_at
    elif category == "closed":
        state = "closed"
        pr_category = "closed"
        merged_at = None
    else:
        raw_state = raw.get("state", "").lower()
        if raw_state == "closed":
            state = "closed"
            pr_category = "closed"
        else:
            state = "open"
            pr_category = "open"
        merged_at = None

    return {
        "number": raw.get("number", 0),
        "title": raw.get("title", ""),
        "state": state,
        "category": pr_category,
        "repo": repo_name,
        "org": org,
        "html_url": raw.get("html_url", ""),
        "created_at": created_at,
        "merged_at": merged_at,
    }


def deduplicate_prs(prs: list[dict]) -> list[dict]:
    """Deduplicate PRs by html_url, preferring merged > closed > open."""
    PRIORITY = {"merged": 3, "closed": 2, "open": 1}
    seen: dict[str, dict] = {}
    for pr in prs:
        url = pr.get("html_url", "")
        if not url:
            continue
        if url not in seen:
            seen[url] = pr
        else:
            if PRIORITY.get(pr.get("category", ""), 0) > PRIORITY.get(seen[url].get("category", ""), 0):
                seen[url] = pr
    return list(seen.values())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def fetch_all_prs(
    github_handle: str, orgs: list[str], start_date: str, end_date: str, token: str
) -> int:
    """Fetch all PRs. Returns exit code."""
    api_error = False
    all_prs: list[dict] = []

    # Resolve per-org tokens (fall back to default token)
    org_tokens: dict[str, str] = {}
    for org in orgs:
        org_name = org.strip()
        org_token = get_github_token_for_org(org_name)
        org_tokens[org_name] = org_token if org_token else token

    # Execute queries per org (each may have a different token)
    for org in orgs:
        org_name = org.strip()
        headers = {
            "Authorization": f"Bearer {org_tokens[org_name]}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(headers=headers) as client:
            tasks = []
            task_meta: list[tuple[str, str]] = []
            for query_str, category in build_queries(github_handle, org_name, start_date, end_date):
                tasks.append(search_prs(client, query_str))
                task_meta.append((org_name, category))

            results = await asyncio.gather(*tasks)

            for i, (items, err) in enumerate(results):
                org_r, category = task_meta[i]
                if err:
                    print(f"Warning: {err} (org={org_r}, category={category})", file=sys.stderr)
                    api_error = True
                for raw in items:
                    all_prs.append(normalize_pr(raw, org_r, category))

    # Deduplicate
    deduplicated = deduplicate_prs(all_prs)

    # Write output
    output_path = Path("reports/.cache/github-prs.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(deduplicated, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Total: {len(deduplicated)} PRs")
    return 2 if api_error else 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) != 5:
        print(
            "Usage: python3 -m weekly_recap.fetchers.fetch_github_prs "
            "<github_handle> <orgs_json> <start_date> <end_date>",
            file=sys.stderr,
        )
        return 1

    github_handle = sys.argv[1]
    orgs_json = sys.argv[2]
    start_date = sys.argv[3]
    end_date = sys.argv[4]

    try:
        orgs = json.loads(orgs_json)
        if not isinstance(orgs, list):
            print("Error: orgs_json must be a JSON array.", file=sys.stderr)
            return 1
    except json.JSONDecodeError:
        print(f"Error: orgs_json is not valid JSON: {orgs_json}", file=sys.stderr)
        return 1

    error = validate_inputs(github_handle, orgs, start_date, end_date)
    if error:
        print(error, file=sys.stderr)
        return 1

    token = get_github_token()
    if token is None:
        print("Error: GitHub authentication is unavailable.", file=sys.stderr)
        return 1

    exit_code = asyncio.run(fetch_all_prs(github_handle, orgs, start_date, end_date, token))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
