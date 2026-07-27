"""Due date formatting for Jira tickets.

Formats the due date of a ticket with fallback logic and imminent
deadline highlighting:
1. Use `duedate` if present
2. Fallback to `customfield_11674` (Desired Closure Date)
3. Bold formatting (**YYYY-MM-DD**) when within 30 days of generation date
4. Return "—" when no date available
"""

from __future__ import annotations

from datetime import date

from weekly_recap.processing.models import FormattedDueDate, JiraTicket

# Default fallback value
_FALLBACK = "\u2014"  # em-dash "—"

# Threshold for imminent deadline highlighting (days)
_IMMINENT_THRESHOLD_DAYS = 30


class DueDateFormatter:
    """Formats due dates with fallback chain and imminent highlighting."""

    def format(self, ticket: JiraTicket, generation_date: date) -> FormattedDueDate:
        """Format the due date for a ticket.

        Applies the fallback chain:
        1. Use `duedate` if present and valid
        2. Use `customfield_11674` if present and valid
        3. Return "—" if no date available

        When a date is within 30 days of the generation date, it is
        wrapped in bold markers (**YYYY-MM-DD**).

        Args:
            ticket: The Jira ticket containing date fields.
            generation_date: The report generation date for imminent calculation.

        Returns:
            A FormattedDueDate with display string, imminent flag, and raw date.
        """
        # Resolve the effective date using fallback chain
        raw_date_str = self._resolve_date(ticket)

        if raw_date_str is None:
            return FormattedDueDate(
                display=_FALLBACK,
                is_imminent=False,
                raw_date=None,
            )

        # Parse the date string
        parsed_date = self._parse_date(raw_date_str)
        if parsed_date is None:
            return FormattedDueDate(
                display=_FALLBACK,
                is_imminent=False,
                raw_date=None,
            )

        # Determine if the date is imminent (within 30 days of generation date)
        is_imminent = self._is_imminent(parsed_date, generation_date)

        # Format the display string
        date_str = parsed_date.isoformat()
        display = f"**{date_str}**" if is_imminent else date_str

        return FormattedDueDate(
            display=display,
            is_imminent=is_imminent,
            raw_date=date_str,
        )

    def _resolve_date(self, ticket: JiraTicket) -> str | None:
        """Resolve the effective due date using the fallback chain.

        Priority:
        1. duedate (primary)
        2. customfield_11674 (Desired Closure Date)

        Args:
            ticket: The Jira ticket.

        Returns:
            The date string to use, or None if no date is available.
        """
        if ticket.duedate:
            return ticket.duedate
        if ticket.customfield_11674:
            return ticket.customfield_11674
        return None

    def _parse_date(self, date_str: str) -> date | None:
        """Parse an ISO 8601 date string (YYYY-MM-DD).

        Args:
            date_str: The date string to parse.

        Returns:
            A date object, or None if parsing fails.
        """
        try:
            return date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None

    def _is_imminent(self, due_date: date, generation_date: date) -> bool:
        """Determine if a due date is within 30 days of the generation date.

        A date is considered imminent if:
            generation_date <= due_date <= generation_date + 30 days

        Past dates (before generation_date) are also considered imminent
        since they are overdue.

        Args:
            due_date: The resolved due date.
            generation_date: The report generation date.

        Returns:
            True if the due date is within 30 days (or overdue).
        """
        delta = (due_date - generation_date).days
        return delta <= _IMMINENT_THRESHOLD_DAYS
