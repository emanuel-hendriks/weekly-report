#!/usr/bin/env python3
"""Full report generation pipeline.

Orchestrates the complete flow:
1. Load cached Jira issues
2. Load cached commits
3. Process tickets (tenant, environment, due date extraction)
4. Match commits to tickets
5. Generate Markdown report
6. Write to reports/weekly-recap-{start_date}.md
"""

import json
import os
import re
import sys
from datetime import date

from weekly_recap.processing.due_date_formatter import DueDateFormatter
from weekly_recap.processing.environment_extractor import EnvironmentExtractor
from weekly_recap.processing.models import (
    FormattedDueDate,
    JiraTicket,
    ProcessedTicket,
    STATUS_GROUPS,
    STATUS_LABELS_IT,
    STATUS_ORDER,
    STATUS_TO_GROUP,
)
from weekly_recap.processing.report_generator import ReportGenerator, ReportConfig
from weekly_recap.processing.summary_calculator import SummaryCalculator
from weekly_recap.processing.tenant_extractor import TenantExtractor


def load_json_file(filepath: str) -> list[dict] | None:
    """Load and parse a JSON file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {filepath}: {e}", file=sys.stderr)
        return None


def load_user_config() -> dict | None:
    """Load user configuration."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user-config.json")
    return load_json_file(config_path)


def match_commits_to_tickets(tickets: list[dict], commits: list[dict]) -> dict[str, list[str]]:
    """Match commits to tickets by looking for ticket keys in commit messages.
    
    Uses a single compiled regex with alternation (KEY1|KEY2|...) to find all
    matching ticket keys in one pass per commit message — O(c) instead of O(c×t).
    
    Returns a dict mapping ticket key to list of commit markdown links.
    """
    # Collect all valid ticket keys (uppercase)
    ticket_keys = [t.get("key", "").upper() for t in tickets]
    ticket_keys = [k for k in ticket_keys if k]
    
    if not ticket_keys or not commits:
        return {}
    
    # Compile a single regex: \b(AWS-18634|CPS-1205|...)\b
    # Sort by length descending to avoid partial matches (e.g., CPS-12 matching before CPS-1205)
    sorted_keys = sorted(ticket_keys, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted_keys) + r")\b", re.IGNORECASE)
    
    ticket_commits: dict[str, list[str]] = {}
    
    for commit in commits:
        message = commit.get("message", "")
        short_sha = commit.get("short_sha", "")
        html_url = commit.get("html_url", "")
        
        # Build markdown link for commit
        if html_url:
            commit_link = f"[`{short_sha}`]({html_url})"
        else:
            commit_link = f"`{short_sha}`"
        
        # Single pass: find all ticket keys mentioned in this commit message
        matches = pattern.findall(message)
        for key in set(matches):  # deduplicate matches within same message
            key_upper = key.upper()
            if key_upper not in ticket_commits:
                ticket_commits[key_upper] = []
            if commit_link not in ticket_commits[key_upper]:
                ticket_commits[key_upper].append(commit_link)
    
    return ticket_commits


def _customer_label_to_tenant(customer_label: str, service_label: str | None = None) -> str:
    """Derive a short tenant name from the customer_label and service_label returned by the API.
    
    Logic:
    - If the customer is internal ("your-company"), the tenant is the product/service
      extracted from service_label (format: "Customer | Product").
    - If the customer is external, derive a short name from the customer label itself.
    
    The function does NOT use a hardcoded map — it works generically with any customer name.
    
    Derivation rules for external customers:
    1. Remove common suffixes: "SPA", "S.P.A.", "S.R.L.", "S.A."
    2. Take the most distinctive word(s) as the short name
    3. Uppercase the result
    
    Examples (from API, not hardcoded):
        "Banca Mediolanum SPA", service=None → "BANCA MEDIOLANUM"
        "Poste Italiane SPA", service="Poste Italiane | Retail" → "POSTE ITALIANE"
        "your-company (Interno)", service="your-company | CAE" → "CAE"
        "your-company (Interno)", service="your-company | Development DWM" → "DWM"
        "Cassa Di Risparmio Di Bolzano SPA", service=None → "CASSA DI RISPARMIO DI BOLZANO"
    """
    if not customer_label:
        return "\u2014"
    
    normalized = customer_label.lower().strip()
    
    # Internal (your-company) → extract product from service label
    if "your-company" in normalized:
        if service_label and "|" in service_label:
            # "your-company | CAE" → "CAE"
            # "your-company | Development DWM" → "DWM"
            product_part = service_label.split("|", 1)[1].strip()
            # Remove "Development " prefix if present
            if product_part.lower().startswith("development "):
                product_part = product_part[len("development "):]
            return product_part.upper() if product_part else "\u2014"
        return "\u2014"  # Internal with no service info
    
    # External customer → derive short name from the label
    name = customer_label.strip()
    # Remove common legal suffixes
    for suffix in (" SPA", " S.P.A.", " S.R.L.", " S.A.", " S.P.A", " SRL", " SA"):
        if name.upper().endswith(suffix):
            name = name[:len(name) - len(suffix)].strip()
            break
    
    return name.upper() if name else "\u2014"


def process_tickets(
    raw_tickets: list[dict],
    ticket_commits: dict[str, list[str]],
    generation_date: date,
) -> list[ProcessedTicket]:
    """Process raw Jira tickets into ProcessedTicket objects.
    
    Tickets tagged with _stale=True by the fetcher are assigned a synthetic
    status "__stale__" so the report generator places them in the
    "Attività Precedenti" section instead of their actual Jira status group.
    """
    tenant_extractor = TenantExtractor()
    environment_extractor = EnvironmentExtractor()
    due_date_formatter = DueDateFormatter()
    
    processed = []
    
    for raw in raw_tickets:
        key = raw.get("key", "")
        summary = raw.get("summary", "")
        status = raw.get("status", "")
        is_stale = raw.get("_stale", False)
        
        # Extract tenant: priority 1 = structured field, priority 2 = regex from title
        customer_label = raw.get("customer_label")
        service_label = raw.get("service_label")
        if customer_label:
            tenant = _customer_label_to_tenant(customer_label, service_label)
        else:
            tenant = tenant_extractor.extract(summary)
        
        # Extract environment: priority 1 = structured field, priority 2 = regex from title
        environment_resolved = raw.get("environment_resolved")
        if environment_resolved:
            environment = environment_resolved
        else:
            environment = environment_extractor.extract(summary)
        
        # Format due date using the formatter
        jira_ticket = JiraTicket(
            key=key,
            summary=summary,
            status=status,
            updated=raw.get("updated", ""),
            created=raw.get("created", ""),
            duedate=raw.get("duedate"),
            customfield_11674=raw.get("customfield_11674"),
            reporter=raw.get("reporter", ""),
            description=raw.get("description", ""),
        )
        formatted_due_date = due_date_formatter.format(jira_ticket, generation_date)
        
        # Build ticket link
        ticket_link = f"[{key}](https://your-company.atlassian.net/browse/{key})"
        
        # Get commits for this ticket
        commits = ticket_commits.get(key, [])
        
        # Use synthetic status for stale tickets so they land in their own section
        effective_status = "__stale__" if is_stale else status
        
        processed_ticket = ProcessedTicket(
            key=key,
            summary=summary,
            status=effective_status,
            updated=raw.get("updated", ""),
            created=raw.get("created", ""),
            reporter=raw.get("reporter", ""),
            description=raw.get("description", ""),
            tenant=tenant,
            environment=environment,
            formatted_due_date=formatted_due_date,
            ticket_link=ticket_link,
            commits=commits,
        )
        processed.append(processed_ticket)
    
    return processed


def deduplicate_tickets(tickets: list[ProcessedTicket]) -> list[ProcessedTicket]:
    """Deduplicate tickets with the same description (case-insensitive, trimmed).
    
    When multiple tickets have the same summary:
    - Merge ticket links: [AWS-18848](...), [CPS-1531](...)
    - Merge commits from all tickets
    - Use the most advanced status (Done > In Progress > To Do)
    - Count as 1 activity
    
    Args:
        tickets: List of processed tickets.
    
    Returns:
        Deduplicated list of tickets.
    """
    # Build status → priority mapping from STATUS_GROUPS and STATUS_ORDER
    # Lower index = more advanced (done=0, inTest=1, inProgress=2, todo=3, cancelled=4)
    status_priority: dict[str, int] = {}
    for priority, group_key in enumerate(STATUS_ORDER):
        for status_name in STATUS_GROUPS.get(group_key, []):
            status_priority[status_name] = priority
    
    # Group tickets by normalized summary (case-insensitive, trimmed)
    groups: dict[str, list[ProcessedTicket]] = {}
    for ticket in tickets:
        normalized_summary = ticket.summary.lower().strip()
        if normalized_summary not in groups:
            groups[normalized_summary] = []
        groups[normalized_summary].append(ticket)
    
    deduplicated = []
    
    for normalized_summary, group in groups.items():
        if len(group) == 1:
            # No duplicates, keep as is
            deduplicated.append(group[0])
        else:
            # Multiple tickets with same summary: merge them
            # Select the ticket with the most advanced status
            primary = min(group, key=lambda t: status_priority.get(t.status, 999))
            
            # Merge ticket links: [AWS-18848](...), [CPS-1531](...)
            merged_links = ", ".join([t.ticket_link for t in group])
            
            # Merge commits from all tickets (deduplicate)
            all_commits = []
            for t in group:
                all_commits.extend(t.commits)
            merged_commits = list(dict.fromkeys(all_commits))  # Deduplicate while preserving order
            
            # Create merged ticket using primary as base
            merged_ticket = ProcessedTicket(
                key=primary.key,  # Keep primary key for reference
                summary=primary.summary,
                status=primary.status,
                updated=primary.updated,
                created=primary.created,
                reporter=primary.reporter,
                description=primary.description,
                tenant=primary.tenant,
                environment=primary.environment,
                formatted_due_date=primary.formatted_due_date,
                ticket_link=merged_links,  # Merged links
                commits=merged_commits,  # Merged commits
            )
            deduplicated.append(merged_ticket)
    
    return deduplicated


def _parse_ticket_links_from_markdown(ticket_link: str) -> list[dict[str, str]]:
    """Parse merged ticket_link field into a list of {key, url} dicts.

    Handles single links like "[AWS-18848](url)" and merged links like
    "[AWS-18848](url), [CPS-1531](url)".
    """
    matches = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", ticket_link)
    return [{"key": key, "url": url} for key, url in matches]


def write_processed_cache(
    tickets: list[ProcessedTicket],
    raw_issues: list[dict],
    cache_dir: str,
) -> None:
    """Serialize processed tickets to reports/.cache/processed-tickets.json.

    Each ticket dict includes: key, keys, summary, status, status_group, tenant,
    environment, priority, issuetype, commits, due_date, ticket_link, description, project.

    Args:
        tickets: Deduplicated list of ProcessedTicket objects.
        raw_issues: Original raw Jira issue dicts (for priority/issuetype lookup).
        cache_dir: Path to reports/.cache/ directory.
    """
    # Build lookup from raw issues for priority and issuetype
    raw_lookup: dict[str, dict] = {}
    for issue in raw_issues:
        key = issue.get("key", "")
        if key:
            raw_lookup[key] = issue

    serialized: list[dict] = []
    for ticket in tickets:
        # Map status → status_group using STATUS_TO_GROUP and STATUS_LABELS_IT
        group_key = STATUS_TO_GROUP.get(ticket.status, "")
        status_group = STATUS_LABELS_IT.get(group_key, ticket.status)

        # Derive project from ticket key (e.g., "AWS-18848" → "AWS")
        project = ticket.key.split("-")[0] if "-" in ticket.key else ticket.key

        # Pull priority and issuetype from raw Jira issue data
        raw_issue = raw_lookup.get(ticket.key, {})
        priority = raw_issue.get("priority")
        issuetype = raw_issue.get("issuetype")

        # Parse ticket_link field to build keys list
        keys = _parse_ticket_links_from_markdown(ticket.ticket_link)

        # Extract due_date from formatted_due_date.raw_date
        due_date = ticket.formatted_due_date.raw_date

        serialized.append({
            "key": ticket.key,
            "keys": keys,
            "summary": ticket.summary,
            "status": ticket.status,
            "status_group": status_group,
            "tenant": ticket.tenant if ticket.tenant != "\u2014" else None,
            "environment": ticket.environment if ticket.environment != "\u2014" else None,
            "priority": priority,
            "issuetype": issuetype,
            "commits": ticket.commits,
            "due_date": due_date,
            "ticket_link": ticket.ticket_link,
            "description": ticket.description,
            "project": project,
        })

    # Write to processed-tickets.json
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, "processed-tickets.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, ensure_ascii=False, indent=2)

    print(f"Processed tickets cache written: {output_path}")


def filter_accepted_cps_feature_requests(issues: list[dict]) -> list[dict]:
    """Remove CPS Feature Request tickets that have a corresponding AWS ticket.

    When the Jira workflow accepts a CPS Feature Request, it generates an AWS-*
    ticket with a similar summary. In the report we only want the AWS ticket
    (the actionable work item), not the original CPS request.

    A CPS Feature Request is considered "accepted" when an AWS ticket exists
    with >50% word overlap in the summary.

    Args:
        issues: Raw Jira issue dicts from jira-issues.json.

    Returns:
        Filtered list with accepted CPS Feature Requests removed.
    """
    # Separate CPS Feature Requests from all other tickets
    cps_feature_requests = [
        i for i in issues
        if i.get("key", "").startswith("CPS")
        and i.get("issuetype") == "Feature Request"
    ]
    aws_tickets = [i for i in issues if i.get("key", "").startswith("AWS")]

    if not cps_feature_requests or not aws_tickets:
        return issues

    # Build word sets for AWS ticket summaries
    aws_word_sets = [
        (a["key"], set(a.get("summary", "").lower().split()))
        for a in aws_tickets
    ]

    # Find CPS Feature Requests that have a matching AWS ticket
    keys_to_exclude: set[str] = set()
    for cps in cps_feature_requests:
        cps_words = set(cps.get("summary", "").lower().split())
        if not cps_words:
            continue
        for _aws_key, aws_words in aws_word_sets:
            if not aws_words:
                continue
            overlap = len(cps_words & aws_words) / max(len(cps_words), len(aws_words))
            if overlap > 0.5:
                keys_to_exclude.add(cps["key"])
                break

    if keys_to_exclude:
        filtered = [i for i in issues if i.get("key") not in keys_to_exclude]
        excluded_str = ", ".join(sorted(keys_to_exclude))
        print(f"  Filtered {len(keys_to_exclude)} accepted CPS Feature Request(s): {excluded_str}")
        return filtered

    return issues


def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print(
            "Usage: python3 scripts/generate_full_report.py <start_date> <end_date>",
            file=sys.stderr,
        )
        print("  Example: python3 scripts/generate_full_report.py 2026-05-09 2026-05-15", file=sys.stderr)
        sys.exit(1)
    
    start_date_str = sys.argv[1]
    end_date_str = sys.argv[2]
    
    # Load user config
    config = load_user_config()
    if not config:
        print("Error: user-config.json not found or invalid", file=sys.stderr)
        sys.exit(1)
    
    user_name = config.get("name", "Unknown")
    
    # Load cached data
    project_root = os.path.dirname(os.path.dirname(__file__))
    cache_dir = os.path.join(project_root, "reports", ".cache")
    
    jira_issues = load_json_file(os.path.join(cache_dir, "jira-issues.json")) or []
    commits = load_json_file(os.path.join(cache_dir, "git-commits.json")) or []
    prs = load_json_file(os.path.join(cache_dir, "github-prs.json")) or []
    calendar_events = load_json_file(os.path.join(cache_dir, "calendar.json")) or []
    
    if not jira_issues:
        print("Warning: No Jira issues found in cache", file=sys.stderr)
    
    # Filter out CPS Feature Requests that have a corresponding AWS ticket
    jira_issues = filter_accepted_cps_feature_requests(jira_issues)
    
    # Get generation date (today)
    generation_date = date.today()
    
    # Match commits to tickets
    ticket_commits = match_commits_to_tickets(jira_issues, commits)
    
    # Process tickets
    processed_tickets = process_tickets(jira_issues, ticket_commits, generation_date)
    
    # Deduplicate tickets with same description
    processed_tickets = deduplicate_tickets(processed_tickets)
    
    # Write processed tickets cache (single source of truth for app.py)
    write_processed_cache(processed_tickets, jira_issues, cache_dir)
    
    # Calculate summary
    summary_calculator = SummaryCalculator()
    summary = summary_calculator.calculate(processed_tickets)
    
    # Generate report
    report_config = ReportConfig(
        user_name=user_name,
        start_date=start_date_str,
        end_date=end_date_str,
        generation_date=generation_date.isoformat(),
    )
    
    report_generator = ReportGenerator()
    report_content = report_generator.generate(
        processed_tickets, summary, report_config,
        commits=commits, prs=prs, calendar_events=calendar_events,
    )
    
    # Write report to file
    report_filename = f"weekly-recap-{start_date_str}.md"
    report_path = os.path.join(project_root, "reports", report_filename)
    
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    print(f"Report generated: {report_path}")


if __name__ == "__main__":
    main()
