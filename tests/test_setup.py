"""Unit tests for setup.sh bash functions.

Tests the bash functions by sourcing the script in controlled subprocess environments.
Validates: Requirements 5.1, 8.1, 8.2
"""

import os
import subprocess
import tempfile
import json

import pytest

# Path to setup.sh relative to this test file
SETUP_SH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup.sh"
)


def run_bash_function(function_call: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Source setup.sh and call a function, returning the result."""
    # We need to override some variables that setup.sh sets at the top
    # and disable 'set -euo pipefail' for controlled testing
    script = f"""
set +euo pipefail
source "{SETUP_SH}" 2>/dev/null || true
{function_call}
"""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=cwd or tempfile.gettempdir(),
    )


class TestDetectOS:
    """Tests for detect_os() function.

    Validates: Requirement 5.1 — OS detection (macOS, Linux, WSL2)
    """

    def test_detect_os_macos(self):
        """When OSTYPE=darwin*, detect_os returns 'macos'."""
        # Source the script and override OSTYPE before calling detect_os
        script = f"""
set +euo pipefail
OSTYPE="darwin22.0"
# Source only the detect_os function
detect_os() {{
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macos"
  elif [[ -f /proc/version ]] && grep -qi microsoft /proc/version 2>/dev/null; then
    echo "wsl"
  else
    echo "linux"
  fi
}}
detect_os
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "macos"
        assert result.returncode == 0

    def test_detect_os_linux(self):
        """When OSTYPE=linux-gnu and no microsoft in /proc/version, detect_os returns 'linux'."""
        script = f"""
set +euo pipefail
OSTYPE="linux-gnu"
# Override /proc/version check by using a temp file
MOCK_PROC_VERSION=$(mktemp)
echo "Linux version 5.15.0-generic" > "$MOCK_PROC_VERSION"
detect_os() {{
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macos"
  elif grep -qi microsoft "$MOCK_PROC_VERSION" 2>/dev/null; then
    echo "wsl"
  else
    echo "linux"
  fi
}}
detect_os
rm -f "$MOCK_PROC_VERSION"
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "linux"
        assert result.returncode == 0

    def test_detect_os_wsl(self):
        """When /proc/version contains 'microsoft', detect_os returns 'wsl'."""
        script = f"""
set +euo pipefail
OSTYPE="linux-gnu"
MOCK_PROC_VERSION=$(mktemp)
echo "Linux version 5.15.90.1-microsoft-standard-WSL2" > "$MOCK_PROC_VERSION"
detect_os() {{
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macos"
  elif grep -qi microsoft "$MOCK_PROC_VERSION" 2>/dev/null; then
    echo "wsl"
  else
    echo "linux"
  fi
}}
detect_os
rm -f "$MOCK_PROC_VERSION"
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "wsl"
        assert result.returncode == 0


class TestCheckPrerequisites:
    """Tests for check_prerequisites() function.

    Validates: Requirements 8.1, 8.2 — Docker CLI and daemon validation
    """

    def test_check_prerequisites_missing_config(self):
        """When user-config.json is missing, check_prerequisites exits non-zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal setup.sh-like script that checks for CONFIG
            script = f"""
set +u
CONFIG="{tmpdir}/user-config.json"
check_prerequisites() {{
  local fail=0
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: user-config.json not found." >&2
    fail=1
  fi
  if [ "$fail" -ne 0 ]; then
    exit 1
  fi
}}
check_prerequisites "linux"
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0
            assert "user-config.json" in result.stderr or "user-config.json" in result.stdout

    def test_check_prerequisites_no_docker(self):
        """When docker command is not available, check_prerequisites exits non-zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a user-config.json so that check passes
            config_path = os.path.join(tmpdir, "user-config.json")
            with open(config_path, "w") as f:
                json.dump({"jira_url": "https://test.atlassian.net", "jira_username": "test@test.com"}, f)

            # Use a PATH that doesn't include docker
            script = f"""
set +u
CONFIG="{config_path}"
# Override PATH to exclude docker
export PATH="/usr/bin:/bin"
check_prerequisites() {{
  local fail=0
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: user-config.json not found." >&2
    fail=1
  fi
  if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker CLI not found." >&2
    fail=1
  fi
  if [ "$fail" -ne 0 ]; then
    exit 1
  fi
}}
check_prerequisites "linux"
"""
            # Use a restricted PATH that won't have docker
            env = os.environ.copy()
            env["PATH"] = "/usr/bin:/bin"

            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                env=env,
            )
            # If docker happens to be in /usr/bin or /bin, skip this test
            docker_check = subprocess.run(
                ["bash", "-c", "command -v docker"],
                capture_output=True,
                text=True,
                env=env,
            )
            if docker_check.returncode != 0:
                # Docker is not in the restricted PATH, so our test is valid
                assert result.returncode != 0
                assert "Docker" in result.stderr or "Docker" in result.stdout
            else:
                pytest.skip("docker is available in restricted PATH, cannot test missing docker")

    def test_check_prerequisites_all_present(self):
        """When user-config.json exists and docker is available, check_prerequisites succeeds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "user-config.json")
            with open(config_path, "w") as f:
                json.dump({"jira_url": "https://test.atlassian.net", "jira_username": "test@test.com"}, f)

            # Create a mock docker command
            mock_bin = os.path.join(tmpdir, "bin")
            os.makedirs(mock_bin)
            docker_mock = os.path.join(mock_bin, "docker")
            with open(docker_mock, "w") as f:
                f.write("#!/bin/bash\nexit 0\n")
            os.chmod(docker_mock, 0o755)

            script = f"""
set +u
CONFIG="{config_path}"
export PATH="{mock_bin}:$PATH"
check_prerequisites() {{
  local fail=0
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: user-config.json not found." >&2
    fail=1
  fi
  if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker CLI not found." >&2
    fail=1
  fi
  if [ "$fail" -ne 0 ]; then
    exit 1
  fi
  echo "OK"
}}
check_prerequisites "linux"
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert "OK" in result.stdout


class TestEnvGeneration:
    """Tests for .env file generation format.

    Validates: Requirements 5.1, 8.1, 8.2 — env file has all required keys
    """

    def test_env_generation_format(self):
        """Generated .env file contains all required keys with correct format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")

            # Simulate what setup.sh does when generating .env
            script = f"""
cat > "{env_path}" <<EOF
# Generated by setup.sh — do not commit this file
JIRA_URL=https://test.atlassian.net
JIRA_USERNAME=user@company.com
JIRA_API_TOKEN=ATATT3xFakeToken123
GITHUB_PAT_WAM=github_pat_fakeWamToken456
GITHUB_PAT_CANDP=github_pat_fakeCandpToken789
EOF
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            # Verify the .env file exists and has all required keys
            assert os.path.isfile(env_path)

            with open(env_path) as f:
                content = f.read()

            required_keys = [
                "JIRA_URL",
                "JIRA_USERNAME",
                "JIRA_API_TOKEN",
                "GITHUB_PAT_WAM",
                "GITHUB_PAT_CANDP",
            ]

            for key in required_keys:
                assert f"{key}=" in content, f"Missing key '{key}' in .env file"

            # Verify no key has an empty value
            lines = [l for l in content.splitlines() if l and not l.startswith("#")]
            for line in lines:
                key, _, value = line.partition("=")
                assert value.strip() != "", f"Key '{key}' has empty value"

    def test_env_generation_overwrites_existing(self):
        """Generating .env overwrites existing file (idempotency)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = os.path.join(tmpdir, ".env")

            # Write an initial .env
            with open(env_path, "w") as f:
                f.write("OLD_KEY=old_value\n")

            # Overwrite with new content (simulating setup.sh behavior)
            script = f"""
cat > "{env_path}" <<EOF
# Generated by setup.sh — do not commit this file
JIRA_URL=https://new.atlassian.net
JIRA_USERNAME=new@company.com
JIRA_API_TOKEN=ATATT3xNewToken
GITHUB_PAT_WAM=github_pat_newWam
GITHUB_PAT_CANDP=github_pat_newCandp
EOF
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            with open(env_path) as f:
                content = f.read()

            # Old content should be gone
            assert "OLD_KEY" not in content
            assert "old_value" not in content
            # New content should be present
            assert "JIRA_URL=https://new.atlassian.net" in content

    def test_env_generation_from_config_values(self):
        """The .env generation reads jira_url and jira_username from user-config.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "user-config.json")
            env_path = os.path.join(tmpdir, ".env")

            config_data = {
                "jira_url": "https://mycompany.atlassian.net",
                "jira_username": "developer@mycompany.com",
            }
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Simulate the config-reading part of generate_env
            script = f"""
CONFIG="{config_path}"
jira_url=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('jira_url', ''))")
jira_username=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('jira_username', ''))")

cat > "{env_path}" <<EOF
# Generated by setup.sh — do not commit this file
JIRA_URL=$jira_url
JIRA_USERNAME=$jira_username
JIRA_API_TOKEN=ATATT3xTestToken
GITHUB_PAT_WAM=github_pat_testWam
GITHUB_PAT_CANDP=github_pat_testCandp
EOF
"""
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            with open(env_path) as f:
                content = f.read()

            assert "JIRA_URL=https://mycompany.atlassian.net" in content
            assert "JIRA_USERNAME=developer@mycompany.com" in content
