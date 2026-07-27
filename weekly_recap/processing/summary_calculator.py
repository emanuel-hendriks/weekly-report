"""Summary calculator for the Weekly Report V2 pipeline.

Calculates aggregated statistics from processed tickets:
- Ticket counts grouped by status
- Imminent deadlines (within 30 days of generation date)
- Total ticket count

Validates: Requirements 2.1, 11.2, 11.3
"""

from __future__ import annotations

from weekly_recap.processing.models import (
    ImminentDeadline,
    ProcessedTicket,
    ReportSummary,
    STATUS_ORDER,
    STATUS_TO_GROUP,
)


class SummaryCalculator:
    """Calculates report summary statistics from processed tickets."""

    def calculate(self, tickets: list[ProcessedTicket]) -> ReportSummary:
        """Calculate summary statistics for the given tickets.

        Counts tickets by status group and collects imminent deadlines.

        Args:
            tickets: List of processed tickets to summarize.

        Returns:
            A ReportSummary with counts per status group, imminent
            deadlines, and total ticket count.
        """
        by_status: dict[str, int] = {}
        imminent_deadlines: list[ImminentDeadline] = []

        # Initialize counts for all status groups
        for group_key in STATUS_ORDER:
            by_status[group_key] = 0

        # Count tickets per status group and collect imminent deadlines
        for ticket in tickets:
            group = self._get_status_group(ticket.status)
            by_status[group] = by_status.get(group, 0) + 1

            # Check for imminent deadline (exclude done/cancelled tickets)
            if ticket.formatted_due_date.is_imminent and group not in ("done", "cancelled"):
                imminent_deadlines.append(
                    ImminentDeadline(
                        ticket_key=ticket.key,
                        due_date=ticket.formatted_due_date.raw_date or "",
                        summary=ticket.summary,
                    )
                )

        return ReportSummary(
            by_status=by_status,
            imminent_deadlines=imminent_deadlines,
            total_tickets=len(tickets),
        )

    def _get_status_group(self, status: str) -> str:
        """Map a Jira status string to its status group key.

        Uses the pre-built STATUS_TO_GROUP reverse lookup for O(1) access.
        Falls back to "todo" if no match is found.

        Args:
            status: The raw Jira status string (e.g., "Done", "In Progress").

        Returns:
            The status group key (e.g., "done", "inProgress", "todo").
        """
        return STATUS_TO_GROUP.get(status, "todo")
