#!/bin/bash
# Setup script for weekly-recap agent (CLI-native mode).
#
# Validates that gh CLI is installed and authenticated, checks user-config.json
# for non-placeholder values, installs Python dependencies, and writes the
# .setup-complete sentinel on success.
#
# Prerequisites:
#   1. Install GitHub CLI: https://cli.github.com/
#   2. Authenticate: gh auth login
#   3. Copy user-config.json.template to user-config.json and fill in your values
#   4. Run: ./setup.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$ROOT/user-config.json"

# --- Check gh installed ---
check_gh_installed() {
  if ! command -v gh &>/dev/null; then
    echo "❌ ERROR: GitHub CLI (gh) is not installed."
    echo "   Install it from: https://cli.github.com/"
    exit 1
  fi
  echo "  ✅ gh CLI found"
}

# --- Check gh authenticated ---
check_gh_auth() {
  if ! gh auth status &>/dev/null; then
    echo "❌ ERROR: GitHub CLI is not authenticated."
    echo "   Run: gh auth login"
    exit 1
  fi
  echo "  ✅ gh authenticated"
}

# --- Validate user-config.json ---
validate_config() {
  if [ ! -f "$CONFIG" ]; then
    echo "❌ ERROR: $CONFIG not found."
    echo "   Copy user-config.json.template to user-config.json and fill in your values."
    exit 1
  fi

  # Check for placeholder values in required fields
  local validation_result
  validation_result=$(python3 -c "
import json, sys

config = json.load(open('$CONFIG'))

placeholders = [
    'Your Name', 'your-github-handle', 'your.email@company.com',
    'your-org-1', 'your-org-2', 'Colleague Name', 'colleague@company.com'
]

errors = []

# Check required fields exist and are non-empty
required = {'name': str, 'jira_username': str, 'github_handle': str, 'github_orgs': list}
for field, expected_type in required.items():
    val = config.get(field)
    if val is None:
        errors.append(f'Missing required field: {field}')
    elif not isinstance(val, expected_type):
        errors.append(f'Field {field} must be a {expected_type.__name__}')
    elif isinstance(val, str) and (not val.strip() or val.strip() in placeholders):
        errors.append(f'Field {field} contains a placeholder value: \"{val}\"')
    elif isinstance(val, list) and len(val) == 0:
        errors.append(f'Field {field} must have at least one entry')

# Check github_orgs entries are not placeholders
orgs = config.get('github_orgs', [])
if isinstance(orgs, list):
    for org in orgs:
        if isinstance(org, str) and org in placeholders:
            errors.append(f'github_orgs contains placeholder value: \"{org}\"')

if errors:
    for e in errors:
        print(e)
    sys.exit(1)
else:
    sys.exit(0)
" 2>&1)

  if [ $? -ne 0 ]; then
    echo "❌ ERROR: user-config.json validation failed:"
    echo "$validation_result" | while IFS= read -r line; do
      echo "   $line"
    done
    exit 1
  fi

  echo "  ✅ user-config.json validated"
}

# --- Install Python package (editable mode) ---
install_package() {
  echo "Installing weekly-recap package..."
  if ! pip install -e "$ROOT" --quiet; then
    echo "❌ ERROR: Failed to install package."
    exit 1
  fi
  echo "  ✅ Package installed (weekly-recap CLI available)"
}

# --- Main ---
main() {
  echo "=== Weekly Recap Agent — Setup (CLI-native) ==="
  echo ""

  echo "Checking CLI tools..."
  check_gh_installed
  check_gh_auth
  echo ""

  echo "Validating configuration..."
  validate_config
  echo ""

  install_package
  echo ""

  # Write sentinel file to mark setup as completed
  date -u "+%Y-%m-%dT%H:%M:%SZ" > "$ROOT/.setup-complete"

  echo "✅ Setup complete."
}

main "$@"
