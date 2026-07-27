#!/bin/bash
# =============================================================================
# apply-branch-protection.sh
# =============================================================================
# Applies GitHub branch protection rules to the `main` branch of the
# your-org-1/kiro-personal-hendrikse repository.
#
# Prerequisites:
#   - GitHub CLI (`gh`) installed and authenticated
#   - Admin access to the repository
#
# Usage:
#   ./scripts/apply-branch-protection.sh
#
# Requirements satisfied:
#   - Req 1.1: main receives code exclusively via approved PRs
#   - Req 1.4: Branch protection rule prevents direct pushes to main
#   - Req 1.5: PRs to main require at least 1 approval
# =============================================================================

set -euo pipefail

OWNER="your-org-1"
REPO="kiro-personal-hendrikse"
BRANCH="main"

echo "🔒 Applying branch protection rules to ${OWNER}/${REPO}:${BRANCH}..."
echo ""

# Apply branch protection rules via GitHub REST API
# Reference: https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection
gh api \
  --method PUT \
  "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  --input - <<'EOF'
{
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "required_status_checks": null,
  "enforce_admins": true,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF

echo ""
echo "✅ Branch protection rules applied successfully!"
echo ""
echo "Summary of rules applied:"
echo "  • Require pull request before merging: YES"
echo "  • Required approving reviews: 1"
echo "  • Dismiss stale reviews on new pushes: YES"
echo "  • Enforce for administrators: YES (no direct pushes, even for admins)"
echo "  • Allow force pushes: NO"
echo "  • Allow branch deletion: NO"
echo ""
echo "Verify with:"
echo "  gh api repos/${OWNER}/${REPO}/branches/${BRANCH}/protection | jq ."
