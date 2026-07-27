#!/usr/bin/env bash
# Pre-commit hook — validates staged files before allowing a commit.
# Install: cp scripts/pre-commit-check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# Exit 0 = all checks pass, Exit 1 = at least one blocking check failed.

set -euo pipefail

# --- Colors for output ---
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# --- State ---
FAILED=0

# --- Get staged files ---
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)

if [ -z "$STAGED_FILES" ]; then
  echo -e "${GREEN}✅ No staged files — nothing to check.${NC}"
  exit 0
fi

# =============================================================================
# CHECK 1: Secrets Detection (ALWAYS BLOCKING — never skippable)
# =============================================================================
check_secrets() {
  local secret_patterns=(".env" ".env.local" "*.token" "*tokens.json" ".ms-graph-tokens.json")
  local found_secrets=()

  for file in $STAGED_FILES; do
    local basename
    basename=$(basename "$file")
    for pattern in "${secret_patterns[@]}"; do
      case "$basename" in
        $pattern)
          found_secrets+=("$file")
          ;;
      esac
    done
    # Also check full path for .env at root
    if [ "$file" = ".env" ] || [ "$file" = ".env.local" ]; then
      # Avoid duplicates
      local already=0
      for f in "${found_secrets[@]+"${found_secrets[@]}"}"; do
        if [ "$f" = "$file" ]; then
          already=1
          break
        fi
      done
      if [ "$already" -eq 0 ]; then
        found_secrets+=("$file")
      fi
    fi
  done

  if [ ${#found_secrets[@]} -gt 0 ]; then
    echo -e "${RED}❌ SECRETS DETECTED in staging area:${NC}" >&2
    for f in "${found_secrets[@]}"; do
      echo -e "   ${RED}• $f${NC}" >&2
    done
    echo -e "${RED}   Remove these files from staging: git reset HEAD <file>${NC}" >&2
    FAILED=1
  else
    echo -e "${GREEN}✅ No secrets detected in staging.${NC}"
  fi
}

# =============================================================================
# CHECK 2: Python Syntax Check (skippable if python3 not available)
# =============================================================================
check_python_syntax() {
  local py_files=()
  for file in $STAGED_FILES; do
    if [[ "$file" == *.py ]]; then
      py_files+=("$file")
    fi
  done

  if [ ${#py_files[@]} -eq 0 ]; then
    return 0
  fi

  if ! command -v python3 &>/dev/null; then
    echo -e "${YELLOW}⚠️  python3 not found — skipping syntax check.${NC}"
    return 0
  fi

  local syntax_errors=0
  for file in "${py_files[@]}"; do
    if [ -f "$file" ]; then
      if ! python3 -m py_compile "$file" 2>/dev/null; then
        echo -e "${RED}❌ Syntax error in: $file${NC}" >&2
        syntax_errors=1
      fi
    fi
  done

  if [ "$syntax_errors" -eq 1 ]; then
    FAILED=1
  else
    echo -e "${GREEN}✅ Python syntax OK (${#py_files[@]} files checked).${NC}"
  fi
}

# =============================================================================
# CHECK 3: Unit Tests (skippable if pytest not available)
# =============================================================================
check_unit_tests() {
  local run_tests=0
  for file in $STAGED_FILES; do
    if [[ "$file" == scripts/* ]] || [[ "$file" == tests/* ]]; then
      run_tests=1
      break
    fi
  done

  if [ "$run_tests" -eq 0 ]; then
    return 0
  fi

  if ! command -v python3 &>/dev/null; then
    echo -e "${YELLOW}⚠️  python3 not found — skipping unit tests.${NC}"
    return 0
  fi

  if ! python3 -m pytest --version &>/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  pytest not available — skipping unit tests.${NC}"
    return 0
  fi

  echo "Running unit tests..."
  if ! python3 -m pytest tests/ --tb=short -q 2>&1; then
    echo -e "${RED}❌ Unit tests failed.${NC}" >&2
    FAILED=1
  else
    echo -e "${GREEN}✅ Unit tests passed.${NC}"
  fi
}

# =============================================================================
# CHECK 4: Docker Build (skippable if docker not available)
# =============================================================================
check_docker_build() {
  local run_docker=0
  for file in $STAGED_FILES; do
    case "$file" in
      Dockerfile|setup.sh|preflight.sh)
        run_docker=1
        break
        ;;
    esac
  done

  if [ "$run_docker" -eq 0 ]; then
    return 0
  fi

  if ! command -v docker &>/dev/null; then
    echo -e "${YELLOW}⚠️  docker not found — skipping Docker build check.${NC}"
    return 0
  fi

  if ! docker info &>/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Docker daemon not running — skipping Docker build check.${NC}"
    return 0
  fi

  echo "Verifying Docker build..."
  if ! docker build -t weekly-recap-mcp:latest . --quiet 2>&1; then
    echo -e "${RED}❌ Docker build failed.${NC}" >&2
    FAILED=1
  else
    echo -e "${GREEN}✅ Docker build succeeded.${NC}"
  fi
}

# =============================================================================
# CHECK 5: Preflight Executable (blocking when preflight.sh is staged)
# =============================================================================
check_preflight_executable() {
  local preflight_staged=0
  for file in $STAGED_FILES; do
    if [ "$file" = "preflight.sh" ]; then
      preflight_staged=1
      break
    fi
  done

  if [ "$preflight_staged" -eq 0 ]; then
    return 0
  fi

  if [ ! -x "preflight.sh" ]; then
    echo -e "${RED}❌ preflight.sh is not executable. Run: chmod +x preflight.sh${NC}" >&2
    FAILED=1
  else
    echo -e "${GREEN}✅ preflight.sh is executable.${NC}"
  fi
}

# =============================================================================
# RUN ALL CHECKS
# =============================================================================
echo "🔍 Running pre-commit checks..."
echo ""

check_secrets
check_python_syntax
check_unit_tests
check_docker_build
check_preflight_executable

echo ""
if [ "$FAILED" -eq 1 ]; then
  echo -e "${RED}❌ Pre-commit checks FAILED. Commit aborted.${NC}" >&2
  exit 1
else
  echo -e "${GREEN}✅ All pre-commit checks passed.${NC}"
  exit 0
fi
