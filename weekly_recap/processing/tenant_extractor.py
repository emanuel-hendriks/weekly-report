"""Tenant extraction from Jira ticket titles.

Fallback extractor used ONLY when the Jira Assets API does not provide
a structured customer_label for the ticket. The primary source of tenant
data is always the Assets API (see jira-api-reference.md).

Applies two regex patterns in priority order:
1. [TENANT] prefix pattern — e.g. "[BMEDPFT] Richiesta..."
2. tenant-env- prefix pattern — e.g. "bmedpft-dev-lambda timeout"
3. Fallback: "—"
"""

from __future__ import annotations

import re

# Pattern 1: [TENANT] prefix — e.g. "[BMEDPFT] Richiesta..."
_PATTERN_BRACKET = re.compile(r"^\[([A-Za-z0-9_-]+)\]")

# Pattern 2: tenant-env- prefix — e.g. "bmedpft-dev-lambda"
_PATTERN_TENANT_ENV = re.compile(
    r"^([a-z0-9]+)-(?:dev|stag|preprod|demo|prod|mt)-", re.IGNORECASE
)

# Default fallback value
_FALLBACK = "\u2014"  # em-dash "—"


class TenantExtractor:
    """Extracts tenant name from a Jira ticket title (fallback only).

    This is used ONLY when the Assets API does not provide a customer_label.
    The primary tenant source is the structured Jira field resolved via API.
    """

    def extract(self, title: str) -> str:
        """Extract tenant from the given ticket title.

        Applies patterns in priority order:
        1. [TENANT] bracket prefix
        2. tenant-env- prefix (lowercase tenant followed by environment)
        3. Fallback: "—"

        Args:
            title: The Jira ticket summary/title string.

        Returns:
            The extracted tenant name (uppercased), or "—" if
            no pattern matches.
        """
        if not title:
            return _FALLBACK

        # Pattern 1: [TENANT] prefix
        match = _PATTERN_BRACKET.search(title)
        if match:
            return match.group(1).upper()

        # Pattern 2: tenant-env- prefix
        match = _PATTERN_TENANT_ENV.search(title)
        if match:
            return match.group(1).upper()

        return _FALLBACK
