#!/usr/bin/env python3
"""
Fetch Jira issue activity using the Jira Cloud REST API directly.

Uses POST /rest/api/3/search/jql (enhanced search) to fetch issues with all
custom fields in a single call per query — no enrichment step needed.

Executes three JQL queries per project (assigned, WAS DURING, reporter),
deduplicates by issue key, and writes results to the cache directory.

Usage:
    python3 -m weekly_recap.fetchers.fetch_jira <jira_username> <projects_json> <start_date> <end_date>

Parameters:
    jira_username: Jira username or email (e.g., "user@company.com")
    projects_json: JSON array of project keys (e.g., '["AWS", "CPS"]')
    start_date: ISO 8601 date (YYYY-MM-DD)
    end_date: ISO 8601 date (YYYY-MM-DD)

Output:
    Writes deduplicated issue data to reports/.cache/jira-issues.json

Exit codes:
    0 — success (including zero results)
    1 — authentication failed or token missing
    2 — API error (partial results written)
"""

import json
import pathlib
import sys
import ssl
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from weekly_recap.auth import prepare_jira_auth

OUTPUT_FILE = pathlib.Path("reports/.cache/jira-issues.json")
ASSETS_CACHE_FILE = pathlib.Path("reports/.cache/assets-cache.json")

# Jira Cloud REST API base URL and Assets workspace ID — loaded from user-config.json
JIRA_BASE_URL = ""  # Set in main() from config
ASSETS_WORKSPACE_ID = ""  # Set in main() from config
SEARCH_ENDPOINT = ""  # Set in main() from config

# Fields to request from the REST API search (all fields in one call)
SEARCH_FIELDS = [
    "key", "summary", "status", "priority", "issuetype", "duedate", "assignee", "reporter",
    "customfield_11674",   # Desired Closure Date
    # CPS tenant/environment fields (Assets objects)
    "customfield_11530",   # Customers (cmdb-object)
    "customfield_11562",   # Services (cmdb-object)
    "customfield_11693",   # Environment Cloud (option/select)
    # AWS tenant/environment fields
    "customfield_10346",   # Assets (cmdb-object)
    "customfield_10272",   # Cloud environments (multiselect)
    "customfield_10269",   # Tenant (text field)
]

# Environment Cloud value mapping (API value → report abbreviation)
ENVIRONMENT_MAPPING = {
    "dev": "DEV",
    "development": "DEV",
    "staging": "STAG",
    "stag": "STAG",
    "pre-prod": "PREPROD",
    "pre-production": "PREPROD",
    "preprod": "PREPROD",
    "produzione": "PROD",
    "production": "PROD",
    "prod": "PROD",
    "demo": "DEMO",
    "mt": "MT",
    "other": "",
}

# SSL context for HTTPS calls
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()


def validate_date(date_str: str) -> bool:
    """Validate that a string is a valid ISO 8601 date (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_inputs(jira_username: str, projects: list, start_date: str, end_date: str) -> str | None:
    """Validate all inputs. Returns error message or None if valid."""
    if not jira_username or not jira_username.strip():
        return "jira_username is required and cannot be empty"

    if not isinstance(projects, list):
        return "projects_json must be a JSON array"

    if len(projects) == 0:
        return "at least one project key is required"

    if len(projects) > 10:
        return "maximum 10 project keys allowed"

    for i, proj in enumerate(projects):
        if not isinstance(proj, str) or not proj.strip():
            return f"projects[{i}] must be a non-empty string"

    if not validate_date(start_date):
        return f"start_date is not a valid ISO 8601 date (YYYY-MM-DD): {start_date}"

    if not validate_date(end_date):
        return f"end_date is not a valid ISO 8601 date (YYYY-MM-DD): {end_date}"

    return None


def build_jql_queries(
    jira_username: str,
    project_key: str,
    start_date: str,
    end_date: str,
    end_date_plus_1: str,
) -> list[str]:
    """Build the 4 JQL queries for a given project.

    Returns a list of 4 JQL query strings.
    Query 4 captures assigned tickets in active statuses that had no activity
    during the period (stale-but-active backlog).
    """
    subtask_clause = ""
    if project_key.upper() == "AWS":
        subtask_clause = " AND issuetype not in subTaskIssueTypes()"

    # Query 1: Assigned tickets updated in period
    q1 = (
        f'assignee = "{jira_username}" AND project = "{project_key}" '
        f'AND updated >= "{start_date}" AND updated < "{end_date_plus_1}"'
        f'{subtask_clause}'
    )

    # Query 2: Previously-assigned tickets (WAS DURING)
    q2 = (
        f'assignee WAS "{jira_username}" DURING ("{start_date}", "{end_date}") '
        f'AND assignee != "{jira_username}" AND project = "{project_key}"'
        f'{subtask_clause}'
    )

    # Query 3: Reporter tickets updated in period
    q3 = (
        f'reporter = "{jira_username}" AND project = "{project_key}" '
        f'AND updated >= "{start_date}" AND updated < "{end_date_plus_1}"'
        f'{subtask_clause}'
    )

    # Query 4: Assigned tickets in active statuses NOT updated in period
    # These are stale-but-active tickets (assigned to me, open, no Jira activity this week)
    q4 = (
        f'assignee = "{jira_username}" AND project = "{project_key}" '
        f'AND status NOT IN (Done, Closed, Resolved, Cancelled, Rejected, Declined) '
        f'AND updated < "{start_date}"'
        f'{subtask_clause}'
    )

    return [q1, q2, q3, q4]


def execute_jql_query(jql: str, auth_header: str) -> tuple[list[dict], str | None]:
    """Execute a JQL query via the Jira REST API (POST /rest/api/3/search/jql).

    Returns all issues with full custom fields in a single call.
    Handles pagination via nextPageToken.

    Returns (issues_list, error_message_or_None).
    """
    all_issues: list[dict] = []
    next_page_token: str | None = None
    max_pages = 10  # Safety limit

    for _ in range(max_pages):
        payload: dict = {
            "jql": jql,
            "fields": SEARCH_FIELDS,
            "maxResults": 100,
        }
        if next_page_token:
            payload["nextPageToken"] = next_page_token

        data_bytes = json.dumps(payload).encode()
        req = urllib.request.Request(SEARCH_ENDPOINT, data=data_bytes, headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        try:
            resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
            data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                error_body = json.loads(e.read())
                error_msg = error_body.get("errorMessages", [str(e)])
            except Exception:
                error_msg = [str(e)]
            return all_issues, f"HTTP {e.code}: {'; '.join(str(m) for m in error_msg)}"
        except urllib.error.URLError as e:
            return all_issues, f"Network error: {e.reason}"
        except Exception as e:
            return all_issues, f"Unexpected error: {e}"

        # Parse issues from response
        raw_issues = data.get("issues", [])
        for raw in raw_issues:
            normalized = normalize_issue(raw)
            if normalized:
                all_issues.append(normalized)

        # Check pagination
        if data.get("isLast", True):
            break
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return all_issues, None


def normalize_issue(raw: dict) -> dict:
    """Normalize a single issue dict from the REST API to the output schema."""
    fields = raw.get("fields", {})
    key = raw.get("key", "")

    # Support both nested (REST API) and flat (legacy acli) structures
    summary = fields.get("summary") or raw.get("summary", "")
    duedate = fields.get("duedate") or raw.get("duedate")
    customfield_11674 = fields.get("customfield_11674") or raw.get("customfield_11674")

    # Status is an object with "name" (REST API) or a plain string (legacy)
    status_raw = fields.get("status") or raw.get("status")
    if isinstance(status_raw, dict):
        status = status_raw.get("name", "")
    else:
        status = str(status_raw) if status_raw else ""

    # Priority is an object with "name" (REST API) or a plain string (legacy)
    priority_raw = fields.get("priority") or raw.get("priority")
    if isinstance(priority_raw, dict):
        priority = priority_raw.get("name", "")
    elif isinstance(priority_raw, str):
        priority = priority_raw
    else:
        priority = None

    # Issue type is an object with "name"
    issuetype_raw = fields.get("issuetype") or raw.get("issuetype")
    if isinstance(issuetype_raw, dict):
        issuetype = issuetype_raw.get("name", "")
    elif isinstance(issuetype_raw, str):
        issuetype = issuetype_raw
    else:
        issuetype = None

    # Assignee is an object with "displayName" (REST API) or a plain string (legacy)
    assignee_raw = fields.get("assignee") or raw.get("assignee")
    if isinstance(assignee_raw, dict):
        assignee = assignee_raw.get("displayName") or assignee_raw.get("name")
    elif isinstance(assignee_raw, str):
        assignee = assignee_raw
    else:
        assignee = None

    # Reporter is an object with "displayName" (REST API) or a plain string (legacy)
    reporter_raw = fields.get("reporter") or raw.get("reporter")
    if isinstance(reporter_raw, dict):
        reporter = reporter_raw.get("displayName") or reporter_raw.get("name")
    elif isinstance(reporter_raw, str):
        reporter = reporter_raw
    else:
        reporter = None

    return {
        "key": key,
        "summary": summary,
        "status": status,
        "priority": priority,
        "issuetype": issuetype,
        "duedate": duedate,
        "customfield_11674": customfield_11674,
        "assignee": assignee,
        "reporter": reporter,
        # CPS: Customers (tenant) — list of objectIds from Assets
        "customer_object_ids": _extract_asset_object_ids(
            fields.get("customfield_11530") or raw.get("customfield_11530")
        ),
        # CPS: Services — list of objectIds from Assets
        "service_object_ids": _extract_asset_object_ids(
            fields.get("customfield_11562") or raw.get("customfield_11562")
        ),
        # CPS: Environment Cloud — direct option value
        "environment_cloud": _extract_option_value(
            fields.get("customfield_11693") or raw.get("customfield_11693")
        ),
        # AWS: Assets — list of objectIds from Assets
        "assets_object_ids": _extract_asset_object_ids(
            fields.get("customfield_10346") or raw.get("customfield_10346")
        ),
        # AWS: Cloud environments — list of option values
        "cloud_environments": _extract_multiselect_values(
            fields.get("customfield_10272") or raw.get("customfield_10272")
        ),
        # AWS: Tenant (text field)
        "tenant_text": fields.get("customfield_10269") or raw.get("customfield_10269"),
    }


def _extract_asset_object_ids(field_value) -> list[str]:
    """Extract objectId values from a cmdb-object-cftype field.

    Field format: [{"objectId": "131", "workspaceId": "...", "id": "..."}]
    Returns list of objectId strings.
    """
    if not field_value or not isinstance(field_value, list):
        return []
    return [
        item.get("objectId", "")
        for item in field_value
        if isinstance(item, dict) and item.get("objectId")
    ]


def _extract_option_value(field_value) -> str | None:
    """Extract the value from an option/select field.

    Field format: {"id": "12640", "value": "Staging"}
    Returns the value string or None.
    """
    if not field_value or not isinstance(field_value, dict):
        return None
    return field_value.get("value")


def _extract_multiselect_values(field_value) -> list[str]:
    """Extract values from a multiselect field.

    Field format: [{"id": "10614", "value": "Development"}]
    Returns list of value strings.
    """
    if not field_value or not isinstance(field_value, list):
        return []
    return [
        item.get("value", "")
        for item in field_value
        if isinstance(item, dict) and item.get("value")
    ]


def deduplicate_issues(issues: list[dict]) -> list[dict]:
    """Deduplicate issues by key, keeping the first occurrence."""
    seen_keys = set()
    unique = []
    for issue in issues:
        key = issue.get("key", "")
        if key and key not in seen_keys:
            seen_keys.add(key)
            unique.append(issue)
    return unique


def normalize_acli_output(data) -> list[dict]:
    """Normalize acli-style JSON output to a list of issue dicts.

    Kept for backward compatibility with tests. The primary path now uses
    the REST API directly, but this handles legacy acli output formats:
    - A list of issue objects directly
    - A dict with an "issues" key containing the list
    - A dict with a single issue (has "key" field)
    """
    if isinstance(data, list):
        return [normalize_issue(item) for item in data if isinstance(item, dict)]

    if isinstance(data, dict):
        if "issues" in data:
            issues = data["issues"]
            if isinstance(issues, list):
                return [normalize_issue(item) for item in issues if isinstance(item, dict)]
        if "key" in data:
            return [normalize_issue(data)]

    return []


def write_output(issues: list[dict]) -> None:
    """Write issues to the output JSON file, creating directory if needed."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(issues, indent=2))


def _load_assets_cache() -> dict[str, str]:
    """Load the local Assets object ID → label cache."""
    if ASSETS_CACHE_FILE.exists():
        try:
            return json.loads(ASSETS_CACHE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_assets_cache(cache: dict[str, str]) -> None:
    """Save the Assets cache to disk."""
    ASSETS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASSETS_CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _ensure_config_loaded():
    """Lazy-load JIRA_BASE_URL and ASSETS_WORKSPACE_ID from user-config.json if not set."""
    global JIRA_BASE_URL, ASSETS_WORKSPACE_ID, SEARCH_ENDPOINT
    if JIRA_BASE_URL and ASSETS_WORKSPACE_ID:
        return
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        JIRA_BASE_URL = config.get("jira_url", "").rstrip("/")
        ASSETS_WORKSPACE_ID = config.get("jira_assets_workspace_id", "")
        SEARCH_ENDPOINT = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def _fetch_asset_label(
    object_id: str,
    auth_header: str,
    ssl_ctx: ssl.SSLContext,
    cache: dict[str, str],
) -> str | None:
    """Fetch a single asset label from the Jira Assets API."""
    global JIRA_BASE_URL, ASSETS_WORKSPACE_ID
    if not JIRA_BASE_URL or not ASSETS_WORKSPACE_ID:
        _ensure_config_loaded()

    url = (
        f"{JIRA_BASE_URL}/gateway/api/jsm/assets/"
        f"workspace/{ASSETS_WORKSPACE_ID}/v1/object/{object_id}"
    )
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
    })

    try:
        resp = urllib.request.urlopen(req, context=ssl_ctx, timeout=10)
        data = json.loads(resp.read())
        label = data.get("label", "")
        if label:
            cache[object_id] = label
            return label
    except (urllib.error.HTTPError, urllib.error.URLError, Exception):
        pass

    return None


def _resolve_asset_object(object_id: str, cache: dict[str, str]) -> str | None:
    """Resolve a single Assets object ID to its label via the Jira Assets API.

    Convenience wrapper that checks cache first, then prepares auth and fetches.
    Returns the label string or None on failure.
    """
    if object_id in cache:
        return cache[object_id]

    _ensure_config_loaded()
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    auth = prepare_jira_auth(config)
    if auth is None:
        return None

    return _fetch_asset_label(object_id, auth[0], SSL_CTX, cache)


def resolve_assets_labels(issues: list[dict]) -> list[dict]:
    """Resolve all Assets object IDs in issues to human-readable labels.

    Adds resolved fields to each issue:
    - customer_label: resolved from customer_object_ids (CPS) or service from assets_object_ids (AWS)
    - service_label: resolved from service_object_ids (CPS) or assets_object_ids (AWS)
    - environment_resolved: from environment_cloud (CPS) or cloud_environments (AWS)
    """
    # Collect all unique object IDs that need resolution
    all_object_ids: set[str] = set()
    for issue in issues:
        all_object_ids.update(issue.get("customer_object_ids", []))
        all_object_ids.update(issue.get("service_object_ids", []))
        all_object_ids.update(issue.get("assets_object_ids", []))

    if not all_object_ids:
        # No Assets fields to resolve — just map environment
        for issue in issues:
            issue["customer_label"] = issue.get("tenant_text")
            issue["service_label"] = None
            issue["environment_resolved"] = _map_environment(
                issue.get("environment_cloud"),
                issue.get("cloud_environments", []),
            )
        return issues

    # Load cache and resolve missing IDs
    cache = _load_assets_cache()
    resolved_count = 0

    # Prepare auth once for all API calls
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = None

    auth = prepare_jira_auth(config) if config else None
    if auth is None:
        print("Warning: Cannot load Jira API token for Assets resolution", file=sys.stderr)
    else:
        auth_header, _email = auth
        ids_to_resolve = [oid for oid in all_object_ids if oid not in cache]

        if ids_to_resolve:
            MAX_WORKERS = 10

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_id = {
                    executor.submit(_fetch_asset_label, oid, auth_header, SSL_CTX, cache): oid
                    for oid in ids_to_resolve
                }
                for future in as_completed(future_to_id):
                    try:
                        label = future.result()
                        if label:
                            resolved_count += 1
                    except Exception:
                        pass

    if resolved_count > 0:
        _save_assets_cache(cache)
        print(f"Resolved {resolved_count} new Assets objects (cache: {len(cache)} total)", file=sys.stderr)

    # Apply resolved labels to issues
    for issue in issues:
        customer_ids = issue.get("customer_object_ids", [])
        if customer_ids:
            labels = [cache.get(oid, "") for oid in customer_ids if cache.get(oid)]
            issue["customer_label"] = labels[0] if labels else None
        else:
            issue["customer_label"] = issue.get("tenant_text")

        service_ids = issue.get("service_object_ids", []) or issue.get("assets_object_ids", [])
        if service_ids:
            labels = [cache.get(oid, "") for oid in service_ids if cache.get(oid)]
            issue["service_label"] = labels[0] if labels else None
        else:
            issue["service_label"] = None

        if not issue["customer_label"] and issue["service_label"] and "|" in issue["service_label"]:
            issue["customer_label"] = issue["service_label"].split("|")[0].strip()

        issue["environment_resolved"] = _map_environment(
            issue.get("environment_cloud"),
            issue.get("cloud_environments", []),
        )

    return issues


def _map_environment(env_cloud: str | None, cloud_envs: list[str]) -> str | None:
    """Map environment field values to report abbreviations."""
    if env_cloud:
        return ENVIRONMENT_MAPPING.get(env_cloud.lower(), env_cloud)

    if cloud_envs:
        mapped = [ENVIRONMENT_MAPPING.get(e.lower(), e) for e in cloud_envs]
        mapped = [m for m in mapped if m]
        return ", ".join(mapped) if mapped else None

    return None


def main():
    # Check for --include-stale flag (opt-in for stale/backlog tickets)
    include_stale = "--include-stale" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--include-stale"]

    if len(args) != 4:
        print(
            "Usage: python3 -m weekly_recap.fetchers.fetch_jira <jira_username> <projects_json> <start_date> <end_date> [--include-stale]",
            file=sys.stderr,
        )
        sys.exit(1)

    jira_username = args[0]
    projects_json = args[1]
    start_date = args[2]
    end_date = args[3]

    # Parse projects JSON
    try:
        projects = json.loads(projects_json)
    except json.JSONDecodeError as e:
        print(f"Error: invalid projects JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate inputs
    error = validate_inputs(jira_username, projects, start_date, end_date)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    # Load config first (needed for auth)
    global JIRA_BASE_URL, ASSETS_WORKSPACE_ID, SEARCH_ENDPOINT
    config_path = pathlib.Path(__file__).resolve().parent.parent.parent / "user-config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("Error: user-config.json not found or invalid", file=sys.stderr)
        sys.exit(1)

    # Prepare authentication
    auth = prepare_jira_auth(config)
    if auth is None:
        print("Error: Jira authentication is unavailable.", file=sys.stderr)
        sys.exit(1)

    auth_header, email = auth

    # Set Jira URL and Assets workspace ID from config
    JIRA_BASE_URL = config.get("jira_url", "").rstrip("/")
    ASSETS_WORKSPACE_ID = config.get("jira_assets_workspace_id", "")
    SEARCH_ENDPOINT = f"{JIRA_BASE_URL}/rest/api/3/search/jql"

    if not JIRA_BASE_URL:
        print("Error: jira_url not set in user-config.json", file=sys.stderr)
        sys.exit(1)

    # Verify token works with a lightweight call
    try:
        test_req = urllib.request.Request(
            f"{JIRA_BASE_URL}/rest/api/3/myself",
            headers={"Authorization": f"Basic {auth_header}", "Accept": "application/json"},
        )
        urllib.request.urlopen(test_req, context=SSL_CTX, timeout=10)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(
                "Error: Jira authentication failed (401). Token may be expired. "
                "Run 'acli jira auth login' to re-authenticate.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Other HTTP errors are not auth failures — continue
    except Exception as e:
        print(f"Warning: Could not verify auth: {e}", file=sys.stderr)

    # Compute end_date_plus_1 for JQL updated < clause
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    end_date_plus_1 = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    # Build all JQL queries across all projects
    all_queries: list[tuple[str, str, bool]] = []  # (jql, project_key, is_stale)
    for project_key in projects:
        project_key = project_key.strip()
        queries = build_jql_queries(jira_username, project_key, start_date, end_date, end_date_plus_1)
        # First 3 queries are active, query 4 is stale
        for i, jql in enumerate(queries[:3]):
            all_queries.append((jql, project_key, False))
        if include_stale and len(queries) > 3:
            all_queries.append((queries[3], project_key, True))

    # Execute all JQL queries in parallel via REST API
    active_issues: list[dict] = []
    stale_issues: list[dict] = []
    api_error_occurred = False

    # Build lookup: jql → is_stale (from the tuple)
    stale_query_set: set[str] = {jql for jql, _, is_stale in all_queries if is_stale}

    MAX_SEARCH_WORKERS = 8

    with ThreadPoolExecutor(max_workers=MAX_SEARCH_WORKERS) as executor:
        future_to_query = {
            executor.submit(execute_jql_query, jql, auth_header): (jql, project_key)
            for jql, project_key, _ in all_queries
        }
        for future in as_completed(future_to_query):
            jql, project_key = future_to_query[future]
            is_stale_query = jql in stale_query_set
            try:
                issues, error = future.result()
                if error:
                    print(f"Error: API error for project {project_key}: {error}", file=sys.stderr)
                    api_error_occurred = True
                else:
                    if is_stale_query:
                        stale_issues.extend(issues)
                    else:
                        active_issues.extend(issues)
            except Exception as e:
                print(f"Error: unexpected error for project {project_key}: {e}", file=sys.stderr)
                api_error_occurred = True

    # Deduplicate active issues by key
    unique_active = deduplicate_issues(active_issues)
    active_keys = {issue.get("key", "") for issue in unique_active}

    # Stale issues: only those NOT already captured by active queries
    unique_stale = deduplicate_issues(stale_issues)
    unique_stale = [issue for issue in unique_stale if issue.get("key", "") not in active_keys]

    # Tag stale issues so downstream processing can distinguish them
    for issue in unique_stale:
        issue["_stale"] = True

    # Combine: active first, then stale
    unique_issues = unique_active + unique_stale

    # Resolve Assets object IDs to human-readable labels
    if unique_issues:
        unique_issues = resolve_assets_labels(unique_issues)

    # Write output
    write_output(unique_issues)

    print(f"Total: {len(unique_issues)} issues")

    if api_error_occurred:
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
