#!/usr/bin/env python3
"""
Fetch GitHub commit activity using httpx (async HTTP).

Strategy (hybrid, 2 phases):
  Phase 1: GitHub Search API for default-branch commits + repo discovery
  Phase 2: GraphQL API for non-default branch commits (1 query per repo)

All HTTP calls are async via httpx — no subprocess overhead.

Usage:
    python3 -m weekly_recap.fetchers.fetch_github_commits [--full] <github_handle> <orgs_json> <start_date> <end_date>

Parameters:
    github_handle: GitHub username (e.g., "your-github-username")
    orgs_json: JSON array of org names (e.g., '["your-org-1", "your-company-wam"]')
    start_date: ISO 8601 date (YYYY-MM-DD)
    end_date: ISO 8601 date (YYYY-MM-DD)

Output:
    Writes commit data to reports/.cache/git-commits.json

Exit codes:
    0 — success (including zero results)
    1 — CLI tool missing, auth failed, or invalid arguments
    2 — API error after successful auth (partial results written)
"""

import asyncio
import json
import pathlib
import sys
from datetime import datetime

import httpx

from weekly_recap.auth import get_github_token, get_github_token_for_org

OUTPUT_FILE = pathlib.Path("reports/.cache/git-commits.json")
GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"
MAX_SEARCH_RESULTS = 100  # GitHub Search API max per page
SEARCH_PAGES = 10  # Max pages to fetch (100 * 10 = 1000 results)
REQUEST_TIMEOUT = 30.0


def _get_author_email() -> str:
    """Get the author email from user-config.json for GraphQL filtering."""
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config.get("jira_username", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_inputs(github_handle: str, orgs: list, start_date: str, end_date: str) -> str | None:
    if not github_handle or not github_handle.strip():
        return "github_handle is required and cannot be empty"
    if not orgs or not isinstance(orgs, list) or len(orgs) == 0:
        return "orgs list is required and must contain at least one org"
    for i, org in enumerate(orgs):
        if not isinstance(org, str) or not org.strip():
            return f"orgs[{i}] must be a non-empty string"
    if not start_date:
        return "start_date is required"
    if not end_date:
        return "end_date is required"
    if not validate_date(start_date):
        return f"start_date '{start_date}' is not a valid ISO 8601 date (YYYY-MM-DD)"
    if not validate_date(end_date):
        return f"end_date '{end_date}' is not a valid ISO 8601 date (YYYY-MM-DD)"
    return None


# ---------------------------------------------------------------------------
# Phase 1: Search API (async)
# ---------------------------------------------------------------------------

async def search_commits_for_org(
    client: httpx.AsyncClient,
    github_handle: str,
    org: str,
    start_date: str,
    end_date: str,
) -> tuple[list[dict], set[str], str | None]:
    """Search commits via GitHub Search API. Returns (commits, repo_names, error)."""
    query = f"author:{github_handle} author-date:{start_date}..{end_date} org:{org}"
    all_commits: list[dict] = []
    repos_found: set[str] = set()

    for page in range(1, SEARCH_PAGES + 1):
        try:
            resp = await client.get(
                f"{GITHUB_API}/search/commits",
                params={"q": query, "per_page": MAX_SEARCH_RESULTS, "page": page},
                headers={"Accept": "application/vnd.github.cloak-preview+json"},
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException:
            return all_commits, repos_found, f"Search timed out for org '{org}'"
        except httpx.HTTPError as e:
            return all_commits, repos_found, f"Search failed for org '{org}': {e}"

        if resp.status_code != 200:
            error_msg = resp.json().get("message", resp.text[:200]) if resp.text else str(resp.status_code)
            return all_commits, repos_found, f"Search API {resp.status_code} for org '{org}': {error_msg}"

        data = resp.json()
        items = data.get("items", [])

        for item in items:
            sha = item.get("sha", "")
            if not sha or len(sha) < 7:
                continue

            commit_data = item.get("commit", {})
            repo_data = item.get("repository", {})

            message = commit_data.get("message", "")
            if "\n" in message:
                message = message.split("\n")[0]

            author_data = commit_data.get("author", {})
            date_raw = author_data.get("date", "")
            date_str = date_raw[:10] if len(date_raw) >= 10 else date_raw

            repo_name = repo_data.get("name", "")
            org_name = repo_data.get("owner", {}).get("login", org)
            html_url = item.get("html_url", f"https://github.com/{org_name}/{repo_name}/commit/{sha}")

            if repo_name:
                repos_found.add(repo_name)

            all_commits.append({
                "sha": sha,
                "short_sha": sha[:7],
                "message": message,
                "date": date_str,
                "author": author_data.get("name", ""),
                "repo": repo_name,
                "org": org_name,
                "branches": ["main"],
                "html_url": html_url,
            })

        # Stop if we got fewer results than requested (last page)
        if len(items) < MAX_SEARCH_RESULTS:
            break

    return all_commits, repos_found, None


# ---------------------------------------------------------------------------
# Phase 2: GraphQL for non-default branches (async)
# ---------------------------------------------------------------------------

async def fetch_non_default_graphql(
    client: httpx.AsyncClient,
    org: str,
    repo: str,
    start_date: str,
    end_date: str,
    author_email: str,
    search_shas: set[str],
) -> tuple[list[dict], str | None]:
    """Fetch commits from non-default branches via a single GraphQL query."""
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"

    query = (
        '{ repository(owner: "%s", name: "%s") { '
        'refs(refPrefix: "refs/heads/", first: 100) { nodes { name '
        'target { ... on Commit { history(first: 50, since: "%s", until: "%s") { '
        'nodes { oid message committedDate author { name email } } } } } } } } }'
        % (org, repo, start_iso, end_iso)
    )

    try:
        resp = await client.post(
            GITHUB_GRAPHQL,
            json={"query": query},
            timeout=REQUEST_TIMEOUT,
        )
    except httpx.TimeoutException:
        return [], f"GraphQL timed out for {org}/{repo}"
    except httpx.HTTPError as e:
        return [], f"GraphQL failed for {org}/{repo}: {e}"

    if resp.status_code != 200:
        return [], f"GraphQL {resp.status_code} for {org}/{repo}"

    data = resp.json()

    # Check for GraphQL errors
    if "errors" in data:
        error_msg = data["errors"][0].get("message", "unknown error")
        return [], f"GraphQL error for {org}/{repo}: {error_msg}"

    refs = data.get("data", {}).get("repository", {}).get("refs", {}).get("nodes", [])

    commits = []
    for ref in refs:
        branch = ref.get("name", "")
        if branch in ("main", "master"):
            continue

        target = ref.get("target")
        if not target:
            continue

        nodes = target.get("history", {}).get("nodes", [])
        for node in nodes:
            email = node.get("author", {}).get("email", "")
            if author_email and author_email.lower() not in email.lower():
                continue
            sha = node.get("oid", "")
            if sha and sha not in search_shas:
                message = node.get("message", "")
                if "\n" in message:
                    message = message.split("\n")[0]
                commits.append({
                    "sha": sha,
                    "short_sha": sha[:7],
                    "message": message,
                    "date": node.get("committedDate", "")[:10],
                    "author": node.get("author", {}).get("name", ""),
                    "repo": repo,
                    "org": org,
                    "branches": [branch],
                    "html_url": f"https://github.com/{org}/{repo}/commit/{sha}",
                })

    return commits, None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def write_output(commits: list[dict]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(commits, indent=2))


async def run_fast(
    github_handle: str, orgs: list[str], start_date: str, end_date: str, token: str
) -> int:
    """Fast mode: Search API + GraphQL. Returns exit code."""
    api_error = False
    all_commits: list[dict] = []
    all_repos: dict[str, set[str]] = {}

    # Resolve per-org tokens (fall back to default token)
    org_tokens: dict[str, str] = {}
    for org in orgs:
        org_name = org.strip()
        org_token = get_github_token_for_org(org_name)
        org_tokens[org_name] = org_token if org_token else token

    # Phase 1: Search API (sequential per org due to different tokens)
    for org in orgs:
        org_name = org.strip()
        headers = {
            "Authorization": f"Bearer {org_tokens[org_name]}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(headers=headers) as client:
            commits, repos, err = await search_commits_for_org(
                client, github_handle, org_name, start_date, end_date
            )
            if err:
                print(f"Warning: {err}", file=sys.stderr)
                api_error = True
            all_commits.extend(commits)
            all_repos[org_name] = repos

    search_shas = {c["sha"] for c in all_commits}

    # Phase 2: GraphQL for non-default branches (per org token)
    author_email = _get_author_email()
    repo_tasks_by_org: dict[str, list[str]] = {}
    for org_name, repos in all_repos.items():
        if repos:
            repo_tasks_by_org[org_name] = list(repos)

    if repo_tasks_by_org and author_email:
        for org_name, repo_list in repo_tasks_by_org.items():
            headers = {
                "Authorization": f"Bearer {org_tokens[org_name]}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            async with httpx.AsyncClient(headers=headers) as client:
                graphql_tasks = [
                    fetch_non_default_graphql(
                        client, org_name, repo, start_date, end_date, author_email, search_shas
                    )
                    for repo in repo_list
                ]
                graphql_results = await asyncio.gather(*graphql_tasks)

                for commits, err in graphql_results:
                    if err:
                        print(f"Warning: {err}", file=sys.stderr)
                        api_error = True
                    all_commits.extend(commits)

    # Deduplicate by SHA
    seen: dict[str, dict] = {}
    for commit in all_commits:
        sha = commit.get("sha", "")
        if sha and sha not in seen:
            seen[sha] = commit
    all_commits = list(seen.values())

    write_output(all_commits)
    print(f"Total: {len(all_commits)} commits")
    return 2 if api_error else 0


def main():
    # Parse flags
    args = sys.argv[1:]
    full_mode = False
    if "--full" in args:
        full_mode = True
        args.remove("--full")
    if "--fast" in args:
        args.remove("--fast")  # backward compat, fast is default

    if len(args) != 4:
        print(
            "Usage: python3 -m weekly_recap.fetchers.fetch_github_commits "
            "[--full] <github_handle> <orgs_json> <start_date> <end_date>",
            file=sys.stderr,
        )
        sys.exit(1)

    github_handle = args[0]
    orgs_json = args[1]
    start_date = args[2]
    end_date = args[3]

    try:
        orgs = json.loads(orgs_json)
    except json.JSONDecodeError as e:
        print(f"Error: invalid orgs_json: {e}", file=sys.stderr)
        sys.exit(1)

    error = validate_inputs(github_handle, orgs, start_date, end_date)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    # Get token from shared auth module
    token = get_github_token()
    if not token:
        print("Error: GitHub authentication is unavailable.", file=sys.stderr)
        sys.exit(1)

    if full_mode:
        # Legacy mode: import and run the old branch-scan approach
        # (kept for backward compat, not rewritten with httpx)
        print("Full mode not available in httpx version. Use default (fast) mode.", file=sys.stderr)
        sys.exit(1)

    # Run async fast mode
    exit_code = asyncio.run(run_fast(github_handle, orgs, start_date, end_date, token))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
