"""Report generator for the Weekly Report V2 pipeline.

Assembles the final Markdown report from processed tickets and summary data.
Produces sections in Italian with status-based grouping (H2), flat tables,
and a final summary with imminent deadlines.

Validates: Requirements 1.1, 1.2, 1.3, 2.1, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4,
           11.1, 11.2, 11.3, 13.1, 13.2, 13.3
"""

from __future__ import annotations

from dataclasses import dataclass

from weekly_recap.processing.models import (
    ProcessedTicket,
    ReportSummary,
    STATUS_LABELS_IT,
    STATUS_ORDER,
    STATUS_TO_GROUP,
)


@dataclass
class ReportConfig:
    """Configuration for report generation."""

    user_name: str
    start_date: str  # ISO 8601 (YYYY-MM-DD)
    end_date: str  # ISO 8601 (YYYY-MM-DD)
    generation_date: str  # ISO 8601 (YYYY-MM-DD)


class ReportGenerator:
    """Generates the V2 weekly report in Markdown format."""

    def generate(
        self,
        tickets: list[ProcessedTicket],
        summary: ReportSummary,
        config: ReportConfig,
        commits: list[dict] | None = None,
        prs: list[dict] | None = None,
        calendar_events: list[dict] | None = None,
    ) -> str:
        """Generate the complete Markdown report.

        Args:
            tickets: List of processed tickets to include in the report.
            summary: Aggregated summary statistics.
            config: Report configuration (user name, dates).
            commits: List of commit dicts from git-commits.json cache.
            prs: List of PR dicts from github-prs.json cache.
            calendar_events: List of calendar event dicts from calendar-events.json cache.

        Returns:
            The complete Markdown report as a string.
        """
        sections: list[str] = []

        # Header
        sections.append(self._generate_header(config))

        # Personal Summary
        sections.append(self._generate_personal_summary(summary, commits, prs, calendar_events))

        # Jira status sections
        status_sections = self._generate_status_sections(tickets)
        if status_sections:
            sections.append(status_sections)

        # GitHub section
        sections.append(self._generate_github_section(commits or [], prs or []))

        # Calendar section
        sections.append(self._generate_calendar_section(calendar_events or []))

        # Riepilogo finale
        sections.append(self._generate_riepilogo(summary))

        return "\n\n---\n\n".join(sections) + "\n"

    def _generate_header(self, config: ReportConfig) -> str:
        """Generate the report header with title, period, and generation date.

        Uses en-dash (–) between period dates per requirement 1.2.

        Args:
            config: Report configuration.

        Returns:
            Header section as Markdown string.
        """
        lines = [
            f"# Weekly Recap \u2014 {config.user_name}",
            f"Period: {config.start_date} \u2013 {config.end_date}",
            f"Generated: {config.generation_date}",
        ]
        return "\n".join(lines)

    def _generate_personal_summary(
        self,
        summary: ReportSummary,
        commits: list[dict] | None = None,
        prs: list[dict] | None = None,
        calendar_events: list[dict] | None = None,
    ) -> str:
        """Generate the Personal Summary section with ticket counts per status.

        Args:
            summary: Report summary with status counts.
            commits: List of commit dicts.
            prs: List of PR dicts.
            calendar_events: List of calendar event dicts.

        Returns:
            Personal Summary section as Markdown string.
        """
        done_count = summary.by_status.get("done", 0)
        in_progress_count = summary.by_status.get("inProgress", 0)
        todo_count = summary.by_status.get("todo", 0)

        commit_count = len(commits) if commits else 0
        pr_opened = sum(1 for pr in (prs or []) if pr.get("state") == "open" or pr.get("category") == "created")
        pr_merged = sum(1 for pr in (prs or []) if pr.get("category") == "merged" or pr.get("state") == "merged")

        # Calculate meeting count and hours
        meeting_count = len(calendar_events) if calendar_events else 0
        total_hours = 0.0
        if calendar_events:
            from datetime import datetime
            for event in calendar_events:
                start_str = event.get("start")
                end_str = event.get("end")
                if start_str and end_str:
                    try:
                        start_dt = datetime.fromisoformat(start_str)
                        end_dt = datetime.fromisoformat(end_str)
                        duration = (end_dt - start_dt).total_seconds() / 3600.0
                        if duration > 0:
                            total_hours += duration
                    except (ValueError, TypeError):
                        continue

        lines = [
            "## Riepilogo Personale",
            f"- Ticket Jira: Done ({done_count}), In Progress ({in_progress_count}), To Do ({todo_count})",
            f"- Commits: {commit_count}",
            f"- PRs aperte: {pr_opened}",
            f"- PRs merged: {pr_merged}",
            f"- Meeting: {meeting_count} ({total_hours:.0f}h totali)",
        ]
        return "\n".join(lines)

    def _generate_status_sections(self, tickets: list[ProcessedTicket]) -> str:
        """Generate H2 sections for each status group with tickets.

        Sections are ordered per STATUS_ORDER. Empty sections are omitted.
        Each section contains a flat table with the standard columns.

        Args:
            tickets: All processed tickets.

        Returns:
            All status sections joined by section separators, or empty string
            if no tickets exist.
        """
        # Group tickets by status group
        grouped: dict[str, list[ProcessedTicket]] = {key: [] for key in STATUS_ORDER}
        for ticket in tickets:
            group = self._get_status_group(ticket.status)
            grouped[group].append(ticket)

        sections: list[str] = []
        for group_key in STATUS_ORDER:
            group_tickets = grouped[group_key]
            if not group_tickets:
                continue  # Omit empty status sections (Req 3.3)

            label = STATUS_LABELS_IT[group_key]
            section = self._generate_table_section(label, group_tickets)
            sections.append(section)

        return "\n\n---\n\n".join(sections)

    def _generate_table_section(
        self, heading: str, tickets: list[ProcessedTicket]
    ) -> str:
        """Generate a single status section with H2 heading and table.

        Table columns: Ticket, Tenant, Ambiente, Descrizione, Commits, Scadenza

        Args:
            heading: The Italian label for the H2 heading.
            tickets: Tickets belonging to this status group.

        Returns:
            Section with heading and Markdown table.
        """
        lines = [
            f"## {heading}",
            "| Ticket | Tenant | Ambiente | Descrizione | Commits | Scadenza |",
            "|--------|--------|----------|-------------|---------|----------|",
        ]

        for ticket in tickets:
            # Format commits: join with comma if multiple, or "—" if none
            commits_display = ", ".join(ticket.commits) if ticket.commits else "—"
            
            row = (
                f"| {ticket.ticket_link} "
                f"| {ticket.tenant} "
                f"| {ticket.environment} "
                f"| {ticket.summary} "
                f"| {commits_display} "
                f"| {ticket.formatted_due_date.display} |"
            )
            lines.append(row)

        return "\n".join(lines)

    def _generate_github_section(self, commits: list[dict], prs: list[dict]) -> str:
        """Generate the GitHub section with commits grouped by repo → branch.

        Args:
            commits: List of commit dicts with branches field.
            prs: List of PR dicts.

        Returns:
            GitHub section as Markdown string.
        """
        if not commits and not prs:
            return "## GitHub\n\n_No GitHub activity found for this period._"

        lines = ["## GitHub"]

        # Group commits by repo → branch
        if commits:
            repos: dict[str, dict[str, list[dict]]] = {}
            for commit in commits:
                repo = commit.get("repo", "Unknown")
                branches = commit.get("branches", [])
                if not branches:
                    branches = ["(unknown)"]
                for branch in branches:
                    repos.setdefault(repo, {}).setdefault(branch, []).append(commit)

            for repo_name in sorted(repos.keys()):
                repo_branches = repos[repo_name]
                total = sum(len(cs) for cs in repo_branches.values())
                lines.append("")
                lines.append(f"### {repo_name}")
                lines.append(f"**Commits:** {total}")

                # Sort branches: "main" first, then alphabetically
                sorted_branches = sorted(
                    repo_branches.keys(),
                    key=lambda b: (0 if b == "main" else 1, b),
                )

                for branch in sorted_branches:
                    branch_commits = repo_branches[branch]
                    # Sort by date descending
                    branch_commits.sort(key=lambda c: c.get("date", ""), reverse=True)

                    lines.append("")
                    lines.append(f"**`{branch}`** ({len(branch_commits)})")
                    lines.append("| SHA | Message | Date |")
                    lines.append("|-----|---------|------|")

                    for commit in branch_commits:
                        sha = commit.get("short_sha") or commit.get("sha", "")[:7]
                        html_url = commit.get("html_url", "")
                        message = commit.get("message", "").replace("|", "\\|")
                        commit_date = commit.get("date", "")

                        if html_url:
                            sha_display = f"[`{sha}`]({html_url})"
                        else:
                            sha_display = f"`{sha}`"

                        lines.append(f"| {sha_display} | {message} | {commit_date} |")

        # PRs section
        if prs:
            lines.append("")
            lines.append("**Pull Requests:**")
            lines.append("| # | Title | Status | URL |")
            lines.append("|---|-------|--------|-----|")

            for pr in prs:
                number = pr.get("number", "")
                title = pr.get("title", "").replace("|", "\\|")
                state = pr.get("category") or pr.get("state", "")
                html_url = pr.get("html_url", "")
                lines.append(f"| {number} | {title} | {state} | {html_url} |")

        return "\n".join(lines)

    def _generate_calendar_section(self, events: list[dict]) -> str:
        """Generate the Calendar section.

        Args:
            events: List of calendar event dicts.

        Returns:
            Calendar section as Markdown string.
        """
        if not events:
            return "## Calendar\n\n_No calendar events found for this period._"

        lines = ["## Calendar", ""]

        # Sort by start time
        sorted_events = sorted(events, key=lambda e: e.get("start", ""))

        for event in sorted_events:
            subject = event.get("subject", "Untitled")
            start_str = event.get("start", "")
            end_str = event.get("end", "")

            # Format time display
            time_display = ""
            if start_str and end_str:
                try:
                    from datetime import datetime
                    start_dt = datetime.fromisoformat(start_str)
                    end_dt = datetime.fromisoformat(end_str)
                    time_display = f"{start_dt.strftime('%Y-%m-%d %H:%M')} – {end_dt.strftime('%H:%M')}"
                except (ValueError, TypeError):
                    time_display = start_str[:16] if start_str else ""

            lines.append(f"- {time_display} — {subject}")

        return "\n".join(lines)

    def _generate_riepilogo(self, summary: ReportSummary) -> str:
        """Generate the final Riepilogo section with per-status table and deadlines.

        Args:
            summary: Report summary with counts and imminent deadlines.

        Returns:
            Riepilogo section as Markdown string.
        """
        lines = [
            "## Riepilogo",
            "",
            "### Per Stato",
            "| Stato | Conteggio |",
            "|-------|-----------|",
        ]

        # Add rows for each status group that has tickets
        for group_key in STATUS_ORDER:
            count = summary.by_status.get(group_key, 0)
            if count > 0:
                label = STATUS_LABELS_IT[group_key]
                lines.append(f"| {label} | {count} |")

        # Scadenze Imminenti section
        lines.append("")
        lines.append("### Scadenze Imminenti (\u226430 giorni)")
        lines.append("| Ticket | Scadenza | Descrizione |")
        lines.append("|--------|----------|-------------|")

        if summary.imminent_deadlines:
            for deadline in summary.imminent_deadlines:
                ticket_link = f"[{deadline.ticket_key}](https://your-company.atlassian.net/browse/{deadline.ticket_key})"
                due_display = f"**{deadline.due_date}**"
                lines.append(
                    f"| {ticket_link} | {due_display} | {deadline.summary} |"
                )

        return "\n".join(lines)

    def _get_status_group(self, status: str) -> str:
        """Map a Jira status string to its status group key.

        Uses the pre-built STATUS_TO_GROUP reverse lookup for O(1) access.

        Args:
            status: The raw Jira status string.

        Returns:
            The status group key. Defaults to "todo" for unknown statuses.
        """
        return STATUS_TO_GROUP.get(status, "todo")
