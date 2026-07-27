---
inclusion: auto
description: Direct REST API patterns for Jira, GitHub PRs, GitHub commits, and Calendar data fetching
---

# Data Sources — Direct REST API Patterns

All date parameters use ISO 8601 format: `YYYY-MM-DD`.

**Authentication:** GitHub uses `gh auth token` to extract OAuth token for direct API calls. Jira uses local API token file at `~/.config/.jira/.token` for Basic auth. No CLI subprocess calls for data fetching.

---

## Jira (Direct REST API)

Tool: Direct Jira Cloud REST API via `weekly_recap/fetchers/fetch_jira.py`

### Authentication

Uses Jira API token stored at `~/.config/.jira/.token` with Basic authentication:
- Token file format: `JIRA_API_TOKEN=your_token_here` or just the token directly
- Basic auth header: `base64(email:token)`
- Email from `jira_username` field in `user-config.json`

### API Endpoint

**POST** `/rest/api/3/search/jql` (enhanced search with all custom fields in single call)

Request payload:
```json
{
  "jql": "assignee = \"user@company.com\" AND project = \"AWS\" AND updated >= \"2026-05-01\" AND updated < \"2026-05-08\"",
  "fields": ["key", "summary", "status", "priority", "issuetype", "duedate", "assignee", "reporter", "customfield_11674", "customfield_11530", "customfield_11562", "customfield_11693", "customfield_10346", "customfield_10272", "customfield_10269"],
  "maxResults": 100
}
```

Handles pagination via `nextPageToken` (up to 10 pages per query).

### Invocation

```bash
weekly-recap generate <start_date> <end_date>
```

The Jira fetcher is invoked internally by the `weekly-recap generate` command. Direct invocation:
```bash
python3 -m weekly_recap.fetchers.fetch_jira <jira_username> <projects_json> <start_date> <end_date>
```

Example:
```bash
python3 -m weekly_recap.fetchers.fetch_jira "user@company.com" '["AWS", "CPS"]' 2026-05-01 2026-05-07
```

**ALWAYS use `weekly-recap generate`** — never run raw REST API calls in chat.

### Three queries per project, merged and deduplicated by key

The script runs queries separately for each project in `jira_projects`. Results are grouped by project key in the report.

**Query 1** — Tickets assigned to me, updated in the period:
```
assignee = "{jira_username}" AND project = "{project_key}" AND updated >= "{start_date}" AND updated < "{end_date_plus_1}"
```

**Query 2** — Tickets I worked on but reassigned (passed to test/feedback):
```
assignee WAS "{jira_username}" DURING ("{start_date}", "{end_date}") AND assignee != "{jira_username}" AND project = "{project_key}"
```

**Query 3** — Tickets I opened (reporter), updated in the period:
```
reporter = "{jira_username}" AND project = "{project_key}" AND updated >= "{start_date}" AND updated < "{end_date_plus_1}"
```

**For AWS project only**, add `AND issuetype not in subTaskIssueTypes()` to all three queries to exclude subtasks and report only task-level issues.

Merge results from all three queries per project, deduplicate by key.

### Fields requested

`key`, `summary`, `status`, `duedate`, `customfield_11674`, `assignee`, `reporter`

- `duedate` — scadenza primaria del ticket
- `customfield_11674` — Desired Closure Date (fallback per la scadenza)

### Output file

`reports/.cache/jira-issues.json` — JSON array of issue objects:

```json
[
  {
    "key": "AWS-18634",
    "summary": "[BMEDPFT] Richiesta aggiornamento lambda",
    "status": "In Progress",
    "duedate": "2026-05-15",
    "customfield_11674": null,
    "assignee": "Emanuel Hendriks",
    "reporter": "Someone Else"
  }
]
```

After the script completes, read the file with `readFile`.

### Exit codes

| Code | Meaning | Agent behavior |
|------|---------|----------------|
| 0 | Success (including zero results) | Read output file, proceed |
| 1 | Authentication failed or token missing | Report error, stop for Jira source |
| 2 | API error (partial results written) | Include warning, continue with other sources |

### Deduplicazione Ticket con Stessa Descrizione

Dopo il merge, identificare ticket con lo stesso `summary` (case-insensitive, trim spazi). Tipicamente un ticket AWS-* e un CPS-* per la stessa attività. Unirli in una singola entry:
- Mantenere entrambe le key (es. `["AWS-18634", "CPS-1205"]`)
- Usare lo stato più "avanzato" (Done > Resolved > In Test > In Progress > To Do)
- Unire i commit di entrambi i ticket
- Conta come 1 attività nel conteggio totale

### Commit Cross-Reference

Per ogni ticket, cercare commit il cui messaggio inizia con la key del ticket (es. `AWS-18634: fix lambda`). Mostrare gli SHA corti come link nella colonna Commits della tabella Jira.

### Ticket URL format

`https://your-company.atlassian.net/browse/{key}`

### Error handling

- Token file missing: `⚠️ Jira data unavailable: API token not found at ~/.config/.jira/.token. Create token at https://id.atlassian.com/manage-profile/security/api-tokens`
- Auth failed: `⚠️ Jira data unavailable: authentication failed (401). Token may be expired.`
- API error: `⚠️ Jira data unavailable: {error}`
- Zero results: `_Nessuna attività Jira trovata per questo periodo._`

---

## Jira — Estrazione Tenant dal Titolo

L'estrazione del tenant segue una catena di priorità:

1. **Campo strutturato** (Assets API) — `customer_label` risolto dal campo `customfield_11530` o `customfield_10346` via Jira Assets REST API. Questa è la fonte primaria e autorevole.
2. **Fallback regex dal titolo** — usato SOLO quando il campo strutturato è assente (comune nei ticket AWS con ~30% copertura). Due pattern applicati in ordine:

**Pattern 1 — Prefisso [TENANT]**: `^\[([A-Za-z0-9_-]+)\]`
- `[BMEDPFT] Richiesta aggiornamento lambda` → `BMEDPFT`
- `[PCA-CORE] Deploy batch` → `PCA-CORE`

**Pattern 2 — Prefisso tenant-env-**: `^([a-z0-9]+)-(?:dev|stag|preprod|demo|prod|mt)-`
- `bmedpft-dev-lambda timeout fix` → `BMEDPFT`
- `bper-prod-migrazione security group` → `BPER`

**Fallback**: "—"

Non esiste una lista hardcoded di tenant nel codice. I nomi vengono sempre dall'API o dai pattern regex generici.

---

## Jira — Estrazione Ambiente dal Titolo

Ambienti riconosciuti: `DEV`, `STAG`, `PREPROD`, `DEMO`, `PROD`, `MT`

**Pattern 1**: `-(?:dev|stag|preprod|demo|prod|mt)-` (case-insensitive, separato da trattini)

**Pattern 2**: `\b(?:dev|stag|preprod|demo|prod|mt)\b` (case-insensitive, word boundary)

- Entrambi i pattern vengono applicati, risultati uniti e deduplicati
- Output sempre in UPPERCASE, più ambienti separati da `, `
- Fallback: "—"

---

## Jira — Formattazione Scadenza (Due Date)

Catena di fallback:
1. Campo `duedate` (primario)
2. Campo `customfield_11674` — Desired Closure Date (secondario)
3. Nessuna data → "—"

Formattazione:
- Data entro 30 giorni dalla generazione → `**YYYY-MM-DD**` (grassetto)
- Data oltre 30 giorni → `YYYY-MM-DD` (normale)
- Nessuna data → `—`

Calcolo imminenza: `0 <= (due_date - generation_date).days <= 30`

---

## GitHub PRs — via httpx (async HTTP)

Tool: Direct GitHub Search API via `weekly_recap/fetchers/fetch_github_prs.py`

### Authentication

Uses `gh auth token` to extract OAuth token, then makes direct API calls:
```python
token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
headers = {"Authorization": f"Bearer {token.stdout.strip()}"}
```

### API Endpoint

**GET** `https://api.github.com/search/issues` with query parameters:
- `q`: GitHub search query (e.g., `author:your-github-username org:your-org-1 created:2026-05-01..2026-05-07`)
- `per_page`: 100 (maximum)
- `page`: for pagination

Uses async httpx for concurrent requests across multiple orgs.

### Invocation

```bash
python3 -m weekly_recap.fetchers.fetch_github_prs <github_handle> <orgs_json> <start_date> <end_date>
```

Example:
```bash
python3 -m weekly_recap.fetchers.fetch_github_prs "your-github-username" '["your-org-1", "your-company-wam"]' 2026-05-01 2026-05-07
```

**ALWAYS use `weekly-recap generate`** — never run raw GitHub API calls in chat.

The `orgs_json` parameter is a JSON array of org name strings from `github_orgs` in `user-config.json`.

### Three search queries per org

For each org in `github_orgs`:

**PRs created:**
```
q=author:{github_handle} org:{org} created:{start_date}..{end_date} type:pr
```

**PRs merged:**
```
q=author:{github_handle} org:{org} merged:{start_date}..{end_date} type:pr
```

**PRs closed (not merged):**
```
q=author:{github_handle} org:{org} closed:{start_date}..{end_date} type:pr -is:merged
```

### Merge and group

Merge results from all orgs. Deduplicate by `html_url`. Group PRs by repository name.

### Output cache file

`reports/.cache/github-prs.json` — consumed by the report generator.

Each PR object in the JSON array:
```json
{
  "number": 7,
  "title": "PR title",
  "state": "open|closed",
  "category": "open|closed|merged",
  "repo": "repo-name",
  "org": "org-name",
  "html_url": "https://github.com/org/repo/pull/7",
  "created_at": "YYYY-MM-DD",
  "merged_at": "YYYY-MM-DD or null"
}
```

- `state`: raw GitHub state (`"open"` or `"closed"`)
- `category`: `"merged"` when PR came from the merged query, `"closed"` when from closed-unmerged query, `"open"` when still open
- `repo`: extracted from `repository.name` in gh JSON output
- `created_at`: date portion of the PR creation timestamp
- `merged_at`: date portion of the merge timestamp, or `null` if not merged

After the script completes, read the file with `readFile`. If no PRs are found across all orgs, the file contains an empty array `[]`.

### Exit codes

| Code | Meaning | Agent behavior |
|------|---------|----------------|
| 0 | Success (including zero results) | Read output file, proceed |
| 1 | `gh` not installed or auth failed | Report error, stop for PR source |
| 2 | API error (partial results written) | Include warning, continue with other sources |

### Error handling (per org)

- `gh` not installed: `⚠️ GitHub data unavailable: gh CLI not found. Install from https://cli.github.com/`
- Auth failed: `⚠️ GitHub data unavailable: not authenticated. Run 'gh auth login'.`
- API error for one org: `⚠️ GitHub PR data unavailable for {org}: {error}`
- Continue with other orgs and data sources.
- Zero results across all orgs: `_No GitHub PR activity found for this period._`

---

## Commits — via httpx + GitHub REST/GraphQL API

Tool: Direct GitHub API via `weekly_recap/fetchers/fetch_github_commits.py`

Commits are sourced from GitHub Search API and GraphQL API via httpx (async HTTP). This captures all commits pushed to GitHub across all orgs.

### Authentication

Same pattern as PRs: uses `gh auth token` to extract OAuth token, then makes direct API calls with httpx.

### Hybrid Strategy (2 phases)

**Phase 1**: GitHub Search API for default-branch commits + repo discovery
**Phase 2**: GraphQL API for non-default branch commits (1 query per repo)

All HTTP calls are async via httpx — no subprocess overhead.

### Invocation

```bash
python3 -m weekly_recap.fetchers.fetch_github_commits <github_handle> <orgs_json> <start_date> <end_date>
```

Example:
```bash
python3 -m weekly_recap.fetchers.fetch_github_commits "your-github-username" '["your-org-1", "your-company-wam"]' 2026-05-01 2026-05-07
```

**ALWAYS use `weekly-recap generate`** — never run raw GitHub API calls in chat.

The `orgs_json` parameter is a JSON array of org name strings from `github_orgs` in `user-config.json`.

### Search queries per org

**Phase 1 - Search API** (default branch commits):
```
q=author:{github_handle} author-date:{start_date}..{end_date} org:{org}
```

**Phase 2 - GraphQL API** (per repository, all branches):
```graphql
query($owner: String!, $name: String!, $since: GitTimestamp!, $until: GitTimestamp!, $author: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, since: $since, until: $until, author: {emails: [$author]}) {
            nodes { oid message committedDate author { name } }
          }
        }
      }
    }
  }
}
```

The script collects up to 1000 results per org across both phases. Async httpx handles concurrent requests.

### Deduplication

Results are deduplicated by SHA across all orgs. When the same commit appears in multiple orgs, the first occurrence's org is retained.

### Output file

`reports/.cache/git-commits.json` — JSON array of commit objects:

```json
[
  {
    "sha": "a3fec1a7b2c4d5e6f7890123456789abcdef0123",
    "short_sha": "a3fec1a",
    "message": "AWS-18276: fix lambda timeout configuration",
    "date": "2026-04-10",
    "author": "your-github-username",
    "repo": "terraform-aws-dev",
    "org": "your-company-wam"
  }
]
```

After the script completes, read the file with `readFile`.

### Exit codes

| Code | Meaning | Agent behavior |
|------|---------|----------------|
| 0 | Success (including zero results) | Read output file, proceed |
| 1 | `gh` not installed or auth failed | Report error, stop for commit source |
| 2 | API error (partial results written) | Include warning, continue with other sources |

### Grouping

Group commits by repository name for report rendering.

### URL construction

For each commit:
```
https://github.com/{org}/{repo}/commit/{sha}
```

Where `org` and `repo` come from the GitHub Search API response.

### Error handling

- Script runs in parallel with other fetch scripts — a failure never blocks Jira, PRs, or Calendar
- Exit code 0 with empty array → no commits found (not an error)
- Exit code 1 (`gh` not installed or auth failed) → `⚠️ Commit data unavailable: gh CLI not found or not authenticated.`
- Exit code 2 (API error) → `⚠️ Commit data partially unavailable: {error}` — partial results are still usable
- Script crash or unexpected exit code → log warning, proceed with Jira, PRs, and Calendar

---

## Calendar (MS Graph API)

Full details in `calendar-source.md`. Summary:

- **Endpoint**: `GET /me/calendarView` with `Prefer: outlook.timezone="Europe/Rome"` header
- **Token**: run `ensure_graph_token.py` before every call; capture bearer token with `--token` flag
- **Query**: `startDateTime={start_date}T00:00:00`, `endDateTime={end_date}T23:59:59`, `$top=50`, `$orderby=start/dateTime`
- **Pagination**: follow `@odata.nextLink` until absent
- **Period rule**: calendar `endDateTime` is always at least today's date
- **Grouping**: events grouped per team member (from `team_members` config); remainder to "Other Meetings"
- **Fallback**: when `team_members` is absent/empty, all events in a flat "Meetings" subsection

When `calendar_email` is missing from config, the agent MUST still generate the report (Jira + GitHub) but include a prominent warning in the Calendar section:

```
⚠️ Calendar non configurato: `calendar_email` mancante in user-config.json. Aggiungi la tua email Exchange/Outlook e esegui `python3 -m weekly_recap.auth.setup_graph_token` per abilitare il calendario.
```

The agent MUST also inform the user in chat that the calendar is not configured and needs setup.

---

## Date defaults

- Default period: `today - 6 days` to `today` (7 calendar days inclusive)
- GitHub PR search uses `YYYY-MM-DD..YYYY-MM-DD` range syntax (no time component)
- GitHub commit search uses `--author-date=YYYY-MM-DD..YYYY-MM-DD` range syntax
- **Jira `updated` filter**: JQL interprets `updated <= "YYYY-MM-DD"` as "before the start of that day", effectively excluding the entire day. To include the full end date, use `updated < "{end_date_plus_1}"` where `end_date_plus_1 = end_date + 1 day`. For example, if `end_date = 2026-04-15`, use `updated < "2026-04-16"`.
- The `DURING` clause in Query 2 is not affected — it uses inclusive date semantics natively.
