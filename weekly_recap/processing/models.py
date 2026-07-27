"""Data models for the Weekly Report V2 pipeline.

Defines dataclasses for ticket processing, formatting, and report generation,
plus constants for status grouping and Italian labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --- Status Constants ---

STATUS_GROUPS: dict[str, list[str]] = {
    "done": ["Done", "Resolved", "Closed"],
    "inTest": ["In Test", "Waiting for Customer", "Waiting for customer", "Waiting for Info",
               "Additional Information Required", "Feedback"],
    "inProgress": ["In Progress", "Take in charge", "Implementation In Progress",
                   "Work in progress", "In Analysis", "waiting for development"],
    "todo": ["To Do", "Backlog", "Open", "Reopened", "Suspended"],
    "cancelled": ["Cancelled", "Declined", "Rejected"],
}

STATUS_ORDER: list[str] = ["done", "inTest", "inProgress", "todo", "cancelled", "stale"]

# Reverse lookup: status string → group key (O(1) instead of iterating STATUS_GROUPS)
STATUS_TO_GROUP: dict[str, str] = {
    status: group_key
    for group_key, statuses in STATUS_GROUPS.items()
    for status in statuses
}

# Synthetic status used for stale tickets (assigned but not updated during report period)
STATUS_TO_GROUP["__stale__"] = "stale"

STATUS_LABELS_IT: dict[str, str] = {
    "done": "Completati",
    "inTest": "In Test / In Attesa",
    "inProgress": "In Corso",
    "todo": "Da Fare",
    "cancelled": "Annullati",
    "stale": "Attività Precedenti",
}


# --- Data Models ---


@dataclass
class JiraTicket:
    """Raw Jira ticket data as retrieved from the Jira API."""

    key: str
    summary: str
    status: str
    updated: str
    created: str
    duedate: Optional[str]
    customfield_11674: Optional[str]
    reporter: str
    description: str


@dataclass
class FormattedDueDate:
    """Result of due date formatting with imminent flag."""

    display: str  # "YYYY-MM-DD", "**YYYY-MM-DD**", or "—"
    is_imminent: bool  # True if within 30 days of generation date
    raw_date: Optional[str]  # Original date string for sorting, or None


@dataclass
class ProcessedTicket:
    """A Jira ticket after processing through all extractors."""

    # Original fields
    key: str
    summary: str
    status: str
    updated: str
    created: str
    reporter: str
    description: str

    # Extracted fields
    tenant: str
    environment: str

    # Formatted fields
    formatted_due_date: FormattedDueDate
    ticket_link: str  # Markdown link: [KEY](url)
    commits: list[str] = field(default_factory=list)  # List of commit markdown links


@dataclass
class ImminentDeadline:
    """A ticket with an imminent deadline (within 30 days)."""

    ticket_key: str
    due_date: str
    summary: str


@dataclass
class ReportSummary:
    """Aggregated statistics for the report summary section."""

    by_status: dict[str, int] = field(default_factory=dict)
    imminent_deadlines: list[ImminentDeadline] = field(default_factory=list)
    total_tickets: int = 0
