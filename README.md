# Weekly Recap Agent

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL2-lightgrey)

A [Kiro](https://kiro.dev) agent that generates your personal weekly recap by querying **Jira** (REST API), **GitHub** (Search API + GraphQL via httpx), and **Outlook calendar** (MS Graph) in parallel. Produces a structured Markdown report.

> This is an individual tool — it generates a recap for a single person based on their credentials and configuration.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Setup (First Time)](#setup-first-time)
3. [Usage](#usage)
4. [Architecture](#architecture)
5. [Project Structure](#project-structure)
6. [License](#license)

---

## Prerequisites

| Software | Purpose |
|----------|---------|
| Python 3.11+ | Package and scripts |
| GitHub CLI (`gh`) | OAuth token for GitHub APIs |
| Jira API Token | Fetch tickets via REST API |
| git | Version control |

---

## Setup (First Time)

```
 1. Install prerequisites
 2. Authenticate with GitHub
 3. Configure Jira token
 4. Authenticate MS Graph (calendar)
 5. Configure user-config.json
 6. Run setup.sh (install + validate + sentinel)
```

> If you request a recap without completing setup, the `weekly-recap preflight` command detects what's missing. The agent, via steering ([`.kiro/steering/AGENT.md`](.kiro/steering/AGENT.md)), auto-fixes what it can (config, setup.sh) and tells you the manual steps (auth, tokens).

### 1. Install Prerequisites

- **Python 3.11+**: [python.org/downloads](https://python.org/downloads/)
- **GitHub CLI**: [cli.github.com](https://cli.github.com/)
- **git**: [git-scm.com](https://git-scm.com)

### 2. Authenticate with GitHub

```bash
gh auth login
```

GitHub fetchers use `httpx` to call the APIs directly. `gh` only serves as a keychain: at startup, the fetcher runs `gh auth token` to read the OAuth token, then makes all HTTP requests via httpx. The token is saved in `~/.config/gh/hosts.yml`.

### 3. Configure Jira Token

The Jira fetcher (`weekly_recap/fetchers/fetch_jira.py`) calls the Jira Cloud REST API via HTTP. A personal API token is required for authentication.

Generate a token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) and save it:

```bash
mkdir -p ~/.config/.jira
echo 'export JIRA_API_TOKEN=<YOUR_TOKEN_HERE>' > ~/.config/.jira/.token
```

The file must contain a single line:

```
export JIRA_API_TOKEN=<YOUR_TOKEN_HERE>
```

Then add to your `~/.bashrc` or `~/.zshrc`:

```bash
source ~/.config/.jira/.token
```

`fetch_jira.py` builds the `Authorization: Basic` header with `base64(email:token)` (see `_prepare_auth()`).

### 4. Authenticate MS Graph (Calendar)

```bash
python3 -m weekly_recap.auth.setup_graph_token
```

Follow the instructions: open [microsoft.com/devicelogin](https://microsoft.com/devicelogin), enter the displayed code, sign in with your work account.

The token is saved in `~/.ms-graph-tokens.json` and auto-refreshes on each run. If it expires (~90 days without use), repeat this step.

### 5. Configure user-config.json

```bash
cp user-config.json.template user-config.json
```

The template has shared team values (tenant_id, client_id, workspace_id, orgs, projects). You only need to change personal fields:

```json
{
  "name": "Your Name",
  "jira_username": "your.name@company.com",
  "github_handle": "YourGitHubUsername",
  "calendar_email": "your.name@company.com"
}
```

| Field | Description |
|-------|-------------|
| `name` | Your name (appears in the report) |
| `jira_url` | Jira instance URL |
| `jira_username` | Your Jira email (also used for REST API auth) |
| `github_handle` | Your GitHub username |
| `github_orgs` | GitHub organizations to query |
| `jira_projects` | Jira projects to query |
| `jira_assets_workspace_id` | Jira Assets workspace ID (pre-filled) |
| `calendar_email` | Email for MS Graph calendar |
| `ms_graph_tenant_id` | Azure AD tenant ID (pre-filled) |
| `ms_graph_client_id` | Azure AD app client ID (pre-filled) |
| `team_members` | (optional) Colleagues to group calendar events |
| `language` | Report language: `"it"` or `"en"` |

### 6. Run Setup

```bash
./setup.sh
```

The script:
- Verifies `gh` is installed and authenticated
- Validates `user-config.json` (no placeholders)
- Installs the package in editable mode (`pip install -e .`)
- Writes `.setup-complete` (sentinel for preflight)

If `weekly-recap` is not found after setup:

```bash
# ~/.zshrc or ~/.bashrc
export PATH="$HOME/.local/bin:$PATH"
source ~/.zshrc
```

Or use a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
./setup.sh
```

---

## Usage

### Kiro Configuration (`.kiro/`)

The `.kiro/` folder configures the AI agent's behavior in the Kiro IDE: steering files (always-on rules), hooks (automations), skills, and a custom agent with restricted permissions.

> 📖 Full documentation: [wiki — Kiro Configuration](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Kiro-Configuration)

### One-Click (Kiro Hook) — Fastest Way

**"Generate Weekly Recap"** button in the *Agent Hooks* section of the Kiro explorer. One click: preflight + generation. No commands to type.

### Kiro Chat

From the Kiro IDE chat, with the `weekly-report-agent` workspace open:

```
generate weekly recap
weekly recap from 2026-05-05 to 2026-05-11
```

### Custom Agent

The project includes a dedicated **custom agent** in `.kiro/agents/weekly-report.json`. It's a restricted-permissions agent designed for daily use, activatable from the Kiro CLI or Kiro IDE chat when the `weekly-report-agent` workspace is open:

- **Read-only** on source code — can read but not modify `weekly_recap/`, `tests/`, `.kiro/`
- **Write** only on `user-config.json` and `reports/`
- **Shell** limited to allowlisted commands: `weekly-recap preflight`, `weekly-recap generate`, `setup.sh`
- **No access** to git push, rm -rf, or destructive commands

**Activation:**

```bash
# At session start
kiro-cli --agent weekly-report

# Or during an active session
kiro /agent swap
# → select "weekly-report" from the list
```

Once active, the agent responds to recap generation prompts while respecting scoped permissions.

### CLI

From any terminal (integrated IDE, iTerm, Terminal.app), positioned in the project root (`weekly-report-agent/`):

```bash
weekly-recap preflight                    # Verify prerequisites
weekly-recap generate                     # Recap last 7 days
weekly-recap generate 2026-05-05 2026-05-11  # Specific period
weekly-recap --help
```

### Credential Rotation

From a terminal positioned in the project root (for MS Graph) or from any directory (for `gh` and Jira):

| Credential | Command | When |
|------------|---------|------|
| GitHub | `gh auth refresh` | If revoked |
| Jira | Regenerate token at [Atlassian](https://id.atlassian.com/manage-profile/security/api-tokens), update `~/.config/.jira/.token` | If revoked |
| MS Graph | `python3 -m weekly_recap.auth.setup_graph_token` | After ~90 days of inactivity |

---

## Architecture

> For the complete diagram and architectural decisions, see the [wiki — Architecture](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Architecture).

```
┌─────────────────────────────────────────────────────────────┐
│  User → "weekly recap" / click hook / CLI                   │
└──────────┬──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│  weekly-recap CLI (installable Python package)               │
│  1. preflight (validation)                                   │
│  2. generate (parallel orchestrator)                         │
└──────────┬───────────────────────────────────────────────────┘
           │ subprocess.Popen (4 parallel processes)
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Parallel Fetchers                                           │
│  • fetch_jira.py       → Jira REST API (6 parallel queries)  │
│  • fetch_github_prs.py → httpx async (6 parallel queries)    │
│  • fetch_github_commits.py → httpx (Search API + GraphQL)    │
│  • fetch_calendar.py   → MS Graph API                        │
└──────────┬───────────────────────────────────────────────────┘
           │ reports/.cache/*.json
           ▼
┌──────────────────────────────────────────────────────────────┐
│  generate_full_report.py (in-process)                        │
│  → reports/weekly-recap-{date}.md                            │
└──────────────────────────────────────────────────────────────┘
```

---

## Project Structure

> For details on each module (role, input/output, dependencies), see the [wiki — Modules](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Modules).

```
.
├── .kiro
│   ├── agents
│   │   ├── weekly-report-prompt.md
│   │   └── weekly-report.json
│   ├── hooks
│   │   └── generate-weekly-recap.kiro.hook
│   ├── skills
│   │   └── weekly-recap
│   │       └── SKILL.md
│   └── steering
│       ├── AGENT.md
│       ├── calendar-source.md
│       ├── data-sources.md
│       ├── jira-api-reference.md
│       └── report-format.md
├── graphs
│   ├── architecturev2.drawio
│   ├── architecturev2.drawio.svg
│   ├── dependency-graph.json
│   ├── dependency-graph.png
│   └── dependency-graph.svg
├── reports
│   └── .cache
│       └── .gitkeep
├── tests
│   ├── __init__.py
│   ├── test_bug_condition_dual_source.py
│   ├── test_cli.py
│   ├── test_fetch_github_commits.py
│   ├── test_fetch_github_prs.py
│   ├── test_fetch_jira.py
│   ├── test_load_json_cache.py
│   ├── test_preflight.py
│   ├── test_preservation_filters.py
│   ├── test_resolve_assets.py
│   └── test_setup.py
├── weekly_recap
│   ├── auth
│   │   ├── __init__.py
│   │   ├── ensure_graph_token.py
│   │   └── setup_graph_token.py
│   ├── fetchers
│   │   ├── __init__.py
│   │   ├── fetch_calendar.py
│   │   ├── fetch_github_commits.py
│   │   ├── fetch_github_prs.py
│   │   └── fetch_jira.py
│   ├── infra
│   │   ├── apply-branch-protection.sh
│   │   └── pre-commit-check.sh
│   ├── processing
│   │   ├── __init__.py
│   │   ├── due_date_formatter.py
│   │   ├── environment_extractor.py
│   │   ├── models.py
│   │   ├── report_generator.py
│   │   ├── summary_calculator.py
│   │   └── tenant_extractor.py
│   ├── __init__.py
│   ├── cli.py
│   ├── generate_full_report.py
│   ├── preflight.py
│   ├── README.md
│   └── run_recap.py
├── .gitignore
├── app.py
├── CONTRIBUTING.md
├── LICENSE
├── pyproject.toml
├── README.md
├── requirements.txt
├── setup.sh
└── user-config.json.template
```

---

## License

[MIT](LICENSE) © 2026 your-org-1
