"""Environment extraction from Jira ticket titles.

Extracts the deployment environment from a ticket title using
two pattern-matching strategies:
1. -env- pattern (environment surrounded by hyphens)
2. Word boundary match for environment names
Multiple environments are returned as a comma-separated string.
Fallback: "—"
"""

from __future__ import annotations

import re

# Recognized environments
ENVIRONMENTS: list[str] = ["DEV", "STAG", "PREPROD", "DEMO", "PROD", "MT"]

# Pattern 1: -env- pattern (environment surrounded by hyphens)
# e.g. "bmedpft-dev-lambda" → DEV
_PATTERN_HYPHEN = re.compile(
    r"-(?:dev|stag|preprod|demo|prod|mt)-", re.IGNORECASE
)

# Pattern 2: Word boundary match for environment names
# e.g. "Aggiornamento in ambiente STAG" → STAG
_PATTERN_WORD_BOUNDARY = re.compile(
    r"\b(?:dev|stag|preprod|demo|prod|mt)\b", re.IGNORECASE
)

# Default fallback value
_FALLBACK = "\u2014"  # em-dash "—"


class EnvironmentExtractor:
    """Extracts deployment environment from a Jira ticket title."""

    def extract(self, title: str) -> str:
        """Extract environment(s) from the given ticket title.

        Applies patterns in order, collecting all unique environments found:
        1. -env- hyphen-surrounded pattern
        2. Word boundary pattern

        Multiple environments are returned as a comma-separated string
        in the order they appear in the title. Duplicates are removed.

        Args:
            title: The Jira ticket summary/title string.

        Returns:
            Comma-separated uppercase environment names (e.g. "DEV, STAG"),
            or "—" if no environment is identified.
        """
        if not title:
            return _FALLBACK

        found: list[str] = []
        seen: set[str] = set()

        # Pattern 1: -env- pattern
        for match in _PATTERN_HYPHEN.finditer(title):
            env = match.group(0).strip("-").upper()
            if env not in seen:
                found.append(env)
                seen.add(env)

        # Pattern 2: Word boundary pattern
        for match in _PATTERN_WORD_BOUNDARY.finditer(title):
            env = match.group(0).upper()
            if env not in seen:
                found.append(env)
                seen.add(env)

        if not found:
            return _FALLBACK

        return ", ".join(found)
