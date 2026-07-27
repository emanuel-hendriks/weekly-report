---
inclusion: auto
description: MS Graph Calendar API integration for fetching calendar events and token management
---

# Calendar Data Source — MS Graph API

Calendar events are retrieved from Microsoft Graph API using the `calendarView` endpoint. The `calendar_email` field is required in `user-config.json`. If missing, the report is still generated (Jira + GitHub) but the Calendar section shows a configuration warning and the agent informs the user that setup is needed.

All times use CET/CEST (`Europe/Rome`) timezone throughout — in API queries, in the report output, and in duration calculations.

---

## Prerequisites

- MS Graph token file at `~/.ms-graph-tokens.json` (created via `setup_graph_token.py` device code flow)
- Token management scripts in `weekly_recap/auth/`:
  - `setup_graph_token.py` — one-time initial authentication (device code flow, requires browser)
  - `ensure_graph_token.py` — ongoing token validation and auto-refresh (no browser needed)
- App registration: "Kiro Integration CandP" (Client ID: `c2785dcf-0678-43ab-bc63-96ec5d0dc301`, Tenant: `b0d66366-8b8a-4831-ae5f-9d15669342ce`)
- Delegated permissions: `Calendars.ReadWrite`, `Schedule.Read.All`

---

## Authentication Flow — How It Works

Calendar uses OAuth2 with Microsoft's device code flow. There are two scripts with distinct roles:

**`setup_graph_token.py`** — Initial setup (run once, or when refresh token expires)
1. Contacts Microsoft to get a temporary device code
2. Prints the code and a URL for the user to visit in their browser
3. Polls Microsoft every 5 seconds for up to 3 minutes
4. When the user completes browser login, saves `access_token` + `refresh_token` to `~/.ms-graph-tokens.json`
5. This is interactive — the user MUST open a browser and sign in

**`ensure_graph_token.py`** — Ongoing use (run before every Graph call)
1. Checks if the token is still valid (based on file mtime + expires_in, with 5min buffer)
2. If expired, automatically refreshes using the stored refresh_token (no browser needed)
3. If refresh fails (refresh_token expired after ~90 days), exits with code 1
4. If token file is missing, exits with code 2
5. With `--token` flag, prints the access_token to stdout for use in curl/scripts

**The agent only calls `ensure_graph_token.py`** — it never runs the setup script. When ensure fails (exit 1 or 2), the agent shows an error note telling the user to run `setup_graph_token.py` manually.

---

## Token Management — MANDATORY FIRST STEP

**RULE**: Before ANY MS Graph API call, ALWAYS run `ensure_graph_token.py` first. Do NOT attempt a Graph call to "see if it works".

```bash
# Step 1: ensure token is valid (auto-refreshes if expired)
python3 -m weekly_recap.auth.ensure_graph_token

# Step 2: capture token for use
TOKEN=$(python3 -m weekly_recap.auth.ensure_graph_token --token)
```

### Exit codes

| Code | Meaning | Agent action |
|------|---------|-------------|
| `0` | Token valid (existing or just refreshed) | Proceed with Graph calls using the token |
| `1` | Refresh failed, device code flow required | Skip Calendar section with error note, instruct user to re-authenticate |
| `2` | Token file missing, device code flow required | Skip Calendar section with error note, instruct user to run initial setup |

### Error notes for token failures

Exit code 1:
```
⚠️ Calendar data unavailable: Token refresh failed. Run device code flow to re-authenticate: python3 -m weekly_recap.auth.setup_graph_token
```

Exit code 2:
```
⚠️ Calendar data unavailable: Token file missing (~/.ms-graph-tokens.json). Run: python3 -m weekly_recap.auth.setup_graph_token to set up authentication.
```

---

## CalendarView Query

### Endpoint

```
GET https://graph.microsoft.com/v1.0/me/calendarView
  ?startDateTime={start_date}T00:00:00
  &endDateTime={end_date}T23:59:59
  &$top=50
  &$orderby=start/dateTime
  &$select=subject,start,end,attendees,isAllDay,isCancelled,organizer
```

### Headers

```
Authorization: Bearer {token}
Prefer: outlook.timezone="Europe/Rome"
```

The `Prefer` header ensures all returned event times are in CET/CEST. No UTC conversion needed.

### How to fetch calendar events

**ALWAYS use the dedicated script** — never write inline Python or use curl for Graph API calls:

```bash
python3 -m weekly_recap.fetchers.fetch_calendar {START_DATE} {END_DATE}
```

Example:
```bash
python3 -m weekly_recap.fetchers.fetch_calendar 2026-04-10 2026-04-16
```

The script:
1. Reads the token from `~/.ms-graph-tokens.json` internally (never prints it)
2. Calls `GET /me/calendarView` with the correct headers and SSL context
3. Handles pagination automatically (`@odata.nextLink`)
4. Auto-refreshes the token if expired (401)
5. Filters cancelled events
6. Writes processed events to `reports/.cache/calendar.json`
7. Prints only a summary to stdout (e.g., `4 events`)

Exit codes:
- `0` — success, events written to `reports/.cache/calendar.json`
- `1` — token refresh failed (device code flow needed)
- `2` — token file missing (device code flow needed)
- `3` — API error

After running the script, read `reports/.cache/calendar.json` with `readFile` to get the processed events.

**FORBIDDEN**: Never use `curl`, inline `python3 -c`, `cat`, or any other method to call Graph API. The `fetch_calendar.py` script handles everything — tokens, SSL, pagination, error handling.

### Calendar period rule

The calendar query `endDateTime` MUST always be at least today's date. If the user-specified end date is before today, adjust the calendar query end date to today. This ensures the recap always includes the present day's meetings.

### Pagination

The CalendarView endpoint returns max 50 events per page. After each response, check for `@odata.nextLink`:

- If present: call the `@odata.nextLink` URL (with the same Authorization and Prefer headers) to get the next page
- If absent: all events have been retrieved

Continue until `@odata.nextLink` is absent.

---

## Event Field Extraction

From each event in the response, extract:

| Field | Source | Description |
|-------|--------|-------------|
| `subject` | `event.subject` | Event title |
| `start_dt` | `event.start.dateTime` | Start time in CET/CEST (format: `YYYY-MM-DD HH:MM`) |
| `end_dt` | `event.end.dateTime` | End time in CET/CEST |
| `is_all_day` | `event.isAllDay` | Whether the event spans the entire day |
| `is_cancelled` | `event.isCancelled` | Whether the event was cancelled |
| `organizer` | `event.organizer.emailAddress` | Organizer name and email |
| `attendee_emails` | `event.attendees[]` | Flat list of attendee email strings (e.g., `["alice@company.com", "bob@company.com"]`). Extracted from `emailAddress.address` — names are not stored to keep JSON compact. |

### Filtering

- **Exclude cancelled events**: skip any event where `isCancelled = true`

### Duration calculation

- For non-all-day events: `duration_min = (end_dt - start_dt)` in minutes
- For all-day events: display "All day" instead of a minute count

---

## Per-Team-Member Grouping

Events are grouped by team member using the `team_members` array from `user-config.json`.

### When `team_members` is configured (non-empty array)

```
team_members = load from user-config.json
tracked_emails = {member.email.lower(): member.name for each member in team_members}

for each non-cancelled event:
    matched_members = []
    for each email in event.attendee_emails:
        if email.lower() in tracked_emails:
            matched_members.append(tracked_emails[email.lower()])
    
    if matched_members is not empty:
        for each member_name in matched_members:
            add event to member_name's subsection
    else:
        add event to "Other Meetings" subsection
```

- Email matching is **case-insensitive**
- A single event can appear under multiple team members if more than one tracked member is an attendee
- Team member subsections are ordered **alphabetically by name**
- Events within each subsection are ordered **chronologically by start time**
- Attendee count is computed as `len(event.attendee_emails)`

### When `team_members` is absent or empty

Render all non-cancelled events in a single flat "Meetings" subsection, ordered chronologically. No per-member grouping.

---

## Error Handling

Calendar errors are **non-fatal**. A failure in the Calendar Connector never blocks Jira or GitHub data.

| Scenario | Agent behavior |
|----------|---------------|
| Token file missing (exit 2) | Error note in Calendar section, continue with Jira/GitHub |
| Token refresh failed (exit 1) | Error note in Calendar section, continue with Jira/GitHub |
| HTTP 4xx/5xx from CalendarView | `⚠️ Calendar data unavailable: HTTP {status} — {message}.` Continue with Jira/GitHub |
| Network timeout | `⚠️ Calendar data unavailable: Connection timeout.` Continue with Jira/GitHub |
| `calendar_email` not in config | Generate report without calendar. Show warning in Calendar section: `⚠️ Calendar non configurato: calendar_email mancante in user-config.json.` Inform user in chat that calendar setup is required. |
| Zero events (no error) | `_No calendar events found for this period._` |

When Calendar has an error, its contribution to the Personal Summary is 0 (0 meetings, 0h).
