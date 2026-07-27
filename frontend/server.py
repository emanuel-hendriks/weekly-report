"""Weekly Recap Dashboard — FastAPI + HTMX + TailwindCSS.

Launch:
    uvicorn frontend.server:app --reload --port 8501
"""

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "reports" / ".cache"
FRONTEND_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Weekly Recap Viewer")

# Mount static files
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))


def load_user_config() -> dict:
    """Load user-config.json from project root."""
    config_path = PROJECT_ROOT / "user-config.json"
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_json_cache(filename: str) -> list[dict]:
    """Load a JSON cache file, returning empty list on failure."""
    filepath = CACHE_DIR / filename
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_all_data() -> dict[str, Any]:
    """Load all cached data sources."""
    tickets = load_json_cache("processed-tickets.json")
    commits = load_json_cache("git-commits.json")
    prs = load_json_cache("github-prs.json")
    events = load_json_cache("calendar.json")
    return {"tickets": tickets, "commits": commits, "prs": prs, "events": events}


def calculate_meeting_hours(events: list[dict]) -> str:
    """Calculate total meeting hours from events."""
    total = 0.0
    for event in events:
        start_str = event.get("start")
        end_str = event.get("end")
        if start_str and end_str:
            try:
                start_dt = datetime.fromisoformat(start_str)
                end_dt = datetime.fromisoformat(end_str)
                duration = (end_dt - start_dt).total_seconds() / 3600.0
                if duration > 0:
                    total += duration
            except (ValueError, TypeError):
                continue
    return f"{total:.1f}"


def extract_filter_options(data: dict) -> dict:
    """Extract all available filter options from data."""
    tickets = data["tickets"]
    commits = data["commits"]

    # Status groups
    statuses: set[str] = set()
    projects: set[str] = set()
    for ticket in tickets:
        if sg := ticket.get("status_group"):
            statuses.add(sg)
        if proj := ticket.get("project"):
            projects.add(proj)
        else:
            for key_entry in ticket.get("keys", []):
                key = key_entry.get("key", "")
                if "-" in key:
                    projects.add(key.split("-")[0])

    # GitHub
    orgs: set[str] = set()
    repos: set[str] = set()
    for commit in commits:
        if org := commit.get("org"):
            orgs.add(org)
        if repo := commit.get("repo"):
            repos.add(repo)

    status_order = ["Completati", "In Test / In Attesa", "In Corso", "Da Fare", "Annullati"]
    sorted_statuses = [s for s in status_order if s in statuses]

    return {
        "all_statuses": sorted_statuses,
        "all_projects": sorted(projects),
        "all_orgs": sorted(orgs),
        "all_repos": sorted(repos),
    }


def filter_tickets(
    tickets: list[dict],
    statuses: list[str] | None = None,
    projects: list[str] | None = None,
) -> list[dict]:
    """Filter tickets by status and project."""
    result = tickets
    if statuses:
        result = [t for t in result if t.get("status_group") in statuses]
    if projects:
        result = [
            t for t in result
            if t.get("project") in projects
            or any(
                k.get("key", "").startswith(p + "-")
                for k in t.get("keys", [])
                for p in projects
            )
        ]
    # Add due_soon flag
    today = date.today()
    for t in result:
        due = t.get("due_date")
        if due:
            try:
                due_dt = date.fromisoformat(due[:10])
                t["due_soon"] = 0 <= (due_dt - today).days <= 30
            except (ValueError, IndexError):
                t["due_soon"] = False
        else:
            t["due_soon"] = False
    return result


def filter_commits(
    commits: list[dict],
    orgs: list[str] | None = None,
    repos: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Filter commits by org, repo, and date range."""
    result = commits
    if orgs:
        result = [c for c in result if c.get("org") in orgs]
    if repos:
        result = [c for c in result if c.get("repo") in repos]
    if start_date and end_date:
        result = [
            c for c in result
            if c.get("date") and start_date <= c["date"][:10] <= end_date
        ]
    return result


def filter_events(
    events: list[dict],
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Filter calendar events by date range."""
    if not start_date or not end_date:
        return events
    return [
        e for e in events
        if e.get("start") and start_date <= e["start"][:10] <= end_date
    ]


def group_tickets_by_status(tickets: list[dict]) -> dict[str, list[dict]]:
    """Group tickets by status_group, preserving display order."""
    status_order = ["Completati", "In Test / In Attesa", "In Corso", "Da Fare", "Annullati"]
    groups: dict[str, list[dict]] = {}
    for ticket in tickets:
        group = ticket.get("status_group", "Unknown")
        groups.setdefault(group, []).append(ticket)
    # Return ordered dict
    ordered: dict[str, list[dict]] = {}
    for status in status_order:
        if status in groups:
            ordered[status] = groups[status]
    # Add any remaining groups not in the order
    for key, val in groups.items():
        if key not in ordered:
            ordered[key] = val
    return ordered


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard page."""
    config = load_user_config()
    data = load_all_data()
    options = extract_filter_options(data)

    today = date.today()
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()

    # Apply default date filter to commits/events
    filtered_commits = filter_commits(data["commits"], start_date=start, end_date=end)
    filtered_events = filter_events(data["events"], start_date=start, end_date=end)
    tickets = filter_tickets(data["tickets"])

    return templates.TemplateResponse(request, "index.html", {
        "user_name": config.get("name", ""),
        "lang": config.get("language", "en"),
        "start_date": start,
        "end_date": end,
        "tickets": tickets,
        "ticket_groups": group_tickets_by_status(tickets),
        "commits": filtered_commits,
        "prs": data["prs"],
        "events": filtered_events,
        "meeting_hours": calculate_meeting_hours(filtered_events),
        **options,
    })


@app.get("/api/filter", response_class=HTMLResponse)
async def api_filter(
    request: Request,
    start_date: str = Query(""),
    end_date: str = Query(""),
    status: list[str] = Query(default=[]),
    project: list[str] = Query(default=[]),
    org: list[str] = Query(default=[]),
    repo: list[str] = Query(default=[]),
) -> HTMLResponse:
    """HTMX endpoint: return filtered content as HTML partial."""
    data = load_all_data()

    tickets = filter_tickets(data["tickets"], statuses=status or None, projects=project or None)
    commits = filter_commits(
        data["commits"],
        orgs=org or None,
        repos=repo or None,
        start_date=start_date or None,
        end_date=end_date or None,
    )
    prs = data["prs"]
    events = filter_events(data["events"], start_date=start_date or None, end_date=end_date or None)

    # Re-render just the main content area
    return templates.TemplateResponse(request, "partials/main_content.html", {
        "tickets": tickets,
        "ticket_groups": group_tickets_by_status(tickets),
        "commits": commits,
        "prs": prs,
        "events": events,
        "meeting_hours": calculate_meeting_hours(events),
    })


@app.post("/api/generate", response_class=HTMLResponse)
async def api_generate(request: Request) -> HTMLResponse:
    """Trigger recap generation and return updated content."""
    result = subprocess.run(
        [sys.executable, "-m", "weekly_recap.run_recap"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        return HTMLResponse(
            f'<div class="text-red-400 p-4 bg-navy-800 rounded-lg border border-red-800">'
            f'<p class="font-semibold">Generation failed (exit {result.returncode})</p>'
            f'<pre class="text-xs mt-2 text-text-muted">{result.stderr[:500]}</pre>'
            f'</div>'
        )

    # Reload and return fresh content
    data = load_all_data()
    today = date.today()
    start = (today - timedelta(days=6)).isoformat()
    end = today.isoformat()

    tickets = filter_tickets(data["tickets"])
    commits = filter_commits(data["commits"], start_date=start, end_date=end)
    events = filter_events(data["events"], start_date=start, end_date=end)

    return templates.TemplateResponse(request, "partials/main_content.html", {
        "tickets": tickets,
        "ticket_groups": group_tickets_by_status(tickets),
        "commits": commits,
        "prs": data["prs"],
        "events": events,
        "meeting_hours": calculate_meeting_hours(events),
    })
