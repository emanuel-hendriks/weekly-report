#!/usr/bin/env python3
"""Unified weekly recap generation pipeline.

Orchestrates the complete flow in a single invocation:
1. Fetch Jira issues
2. Fetch GitHub PRs
3. Fetch GitHub commits (search-only fast mode)
4. Fetch calendar events
5. Generate full report with all data

Optimizations:
- All fetchers run as parallel subprocesses
- Commits fetcher uses search-only mode (--fast) to skip branch enumeration
- Report generation runs in-process (no subprocess overhead)

Preflight validation is handled by the agent BEFORE calling this script.

Usage:
    python3 scripts/run_recap.py [start_date] [end_date]

Examples:
    python3 scripts/run_recap.py                    # Last 7 days
    python3 scripts/run_recap.py 2026-05-09 2026-05-15
"""

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

# Project root: from weekly_recap/run_recap.py → up two levels to project root
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


def load_user_config() -> dict | None:
    """Load user configuration."""
    config_path = os.path.join(PROJECT_ROOT, "user-config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main():
    """Main entry point."""
    # Parse arguments — extract flags first
    include_stale = "--include-stale" in sys.argv
    positional_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if len(positional_args) == 0:
        # Default: last 7 days
        end_date = date.today()
        start_date = end_date - timedelta(days=6)
    elif len(positional_args) == 2:
        start_date_str = positional_args[0]
        end_date_str = positional_args[1]
        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        except ValueError:
            print(f"Error: Invalid date format. Use YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        print(
            "Usage: weekly-recap generate [start_date] [end_date] [--include-stale]",
            file=sys.stderr,
        )
        print("  Example: python3 scripts/run_recap.py 2026-05-09 2026-05-15", file=sys.stderr)
        sys.exit(1)

    start_date_str = start_date.isoformat()
    end_date_str = end_date.isoformat()

    # Preflight check (integrated — fast mode skips slow auth checks)
    from weekly_recap.preflight import run_preflight
    preflight_result = run_preflight(fast=True)
    if not preflight_result.ready:
        print("❌ NOT_READY\n")
        for e in preflight_result.errors:
            print(f"❌ {e}")
        print("\nRun 'weekly-recap preflight' for full diagnostics.")
        sys.exit(1)

    print(f"\n📋 Weekly Recap Generator")
    print(f"   Period: {start_date_str} to {end_date_str}\n")

    # Load config
    config = load_user_config()
    if not config:
        print("\n❌ user-config.json not found or invalid", file=sys.stderr)
        sys.exit(1)

    jira_username = config.get("jira_username")
    jira_projects = config.get("jira_projects", [])
    github_handle = config.get("github_handle")
    github_orgs = config.get("github_orgs", [])

    if not all([jira_username, jira_projects, github_handle, github_orgs]):
        print("\n❌ user-config.json is missing required fields", file=sys.stderr)
        sys.exit(1)

    # Fetch all data sources in parallel as subprocesses
    projects_json = json.dumps(jira_projects)
    # Normalize github_orgs: support both plain strings and {"org": "...", "server": "..."} objects
    org_names = [
        entry["org"] if isinstance(entry, dict) else entry
        for entry in github_orgs
    ]
    orgs_json = json.dumps(org_names)

    fetchers = [
        {
            "cmd": [
                sys.executable, "-m", "weekly_recap.fetchers.fetch_jira",
                jira_username, projects_json, start_date_str, end_date_str,
            ] + (["--include-stale"] if include_stale else []),
            "description": "Fetching Jira issues",
        },
        {
            "cmd": [
                sys.executable, "-m", "weekly_recap.fetchers.fetch_github_prs",
                github_handle, orgs_json, start_date_str, end_date_str,
            ],
            "description": "Fetching GitHub PRs",
        },
        {
            "cmd": [
                sys.executable, "-m", "weekly_recap.fetchers.fetch_github_commits",
                github_handle, orgs_json, start_date_str, end_date_str,
            ],
            "description": "Fetching GitHub commits",
        },
        {
            "cmd": [
                sys.executable, "-m", "weekly_recap.fetchers.fetch_calendar",
                start_date_str, end_date_str,
            ],
            "description": "Fetching calendar events",
        },
    ]

    # Launch all fetchers in parallel
    print("▶ Fetching all data sources in parallel...")
    processes = []
    for fetcher in fetchers:
        try:
            proc = subprocess.Popen(
                fetcher["cmd"],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append((proc, fetcher))
        except Exception as e:
            print(f"  ✗ Failed to start: {fetcher['description']} — {e}")
            processes.append((None, fetcher))

    # Wait for all fetchers to complete (timeout: 5 minutes)
    for proc, fetcher in processes:
        if proc is None:
            print(f"  ✗ {fetcher['description']}: not started")
            continue
        try:
            proc.wait(timeout=300)
            if proc.returncode == 0:
                print(f"  ✓ {fetcher['description']}")
            elif proc.returncode == 2:
                # API error but partial results written — acceptable
                print(f"  ✓ {fetcher['description']} (partial)")
            else:
                print(f"  ✗ {fetcher['description']} (exit code {proc.returncode})")
                print(f"    ⚠️  Continuing with other sources...")
        except subprocess.TimeoutExpired:
            proc.kill()
            print(f"  ✗ {fetcher['description']}: timeout after 300s")
            print(f"    ⚠️  Continuing with other sources...")

    # Generate full report in-process (no subprocess overhead)
    print("▶ Generating report...", flush=True)
    old_argv = sys.argv
    try:
        sys.argv = ["generate_full_report", start_date_str, end_date_str]
        from weekly_recap.generate_full_report import main as generate_main
        generate_main()
        print("  ✓ Done")
    except SystemExit as e:
        if e.code != 0:
            print("\n❌ Report generation failed", file=sys.stderr)
            sys.exit(1)
        print("  ✓ Done")
    except Exception as e:
        print(f"\n❌ Report generation failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        sys.argv = old_argv

    print(f"\n✅ Report generated successfully!")
    print(f"   📄 reports/weekly-recap-{start_date_str}.md")

    # Launch dashboard (non-blocking, runs in background)
    _pidfile = os.path.join(PROJECT_ROOT, ".dashboard.pid")
    try:
        # Kill previous instance by PID file
        if os.path.exists(_pidfile):
            try:
                with open(_pidfile, "r") as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 15)  # SIGTERM
            except (ProcessLookupError, PermissionError, ValueError):
                pass

        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "frontend.server:app",
             "--host", "127.0.0.1", "--port", "8501"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(_pidfile, "w") as f:
            f.write(str(proc.pid))
        print(f"\n🚀 Dashboard running at http://localhost:8501")
        print(f"   (Press Ctrl+C to stop the server)\n")
    except Exception as e:
        print(f"⚠️  Could not launch dashboard: {e}")


if __name__ == "__main__":
    main()
