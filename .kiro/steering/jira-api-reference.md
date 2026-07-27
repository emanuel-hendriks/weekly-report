---
inclusion: auto
description: your-company Jira Cloud REST API reference for custom fields, Assets resolution, and tenant/environment extraction
---

# your-company Jira API Reference

Technical reference for integrating with **your-company's Jira Cloud instance** (`your-company.atlassian.net`) to extract structured tenant, environment, and service data for weekly reports.

**Key challenges addressed:**
- Custom fields contain object IDs requiring Assets API resolution
- Different projects (AWS vs CPS) use different field schemas  
- Low data coverage (30-90%) requires intelligent fallback strategies

---

## Authentication & Base Configuration

**API Token**: Stored at `~/.config/.jira/.token` (format: `JIRA_API_TOKEN=your_token` or just the token)
**Base URL**: `https://your-company.atlassian.net`
**Assets Workspace**: `8ce4b273-d96f-4c70-8b75-752b50b42b06`
**Authentication**: Basic auth with `base64(email:token)`

---

## Core API Endpoints

### Issue Search (Enhanced JQL)

**POST** `/rest/api/3/search/jql`

Primary endpoint for bulk issue retrieval with all custom fields in a single call.

**Request payload:**
```json
{
  "jql": "assignee = \"user@company.com\" AND project = \"AWS\" AND updated >= \"2026-05-01\" AND updated < \"2026-05-08\"",
  "fields": [
    "key", "summary", "status", "priority", "issuetype", "duedate", "assignee", "reporter",
    "customfield_11674",   // Desired Closure Date
    "customfield_11530",   // CPS: Customers (Assets)
    "customfield_11562",   // CPS: Services (Assets)
    "customfield_11693",   // CPS: Environment Cloud (select)
    "customfield_10346",   // AWS: Assets (Assets)
    "customfield_10272",   // AWS: Cloud environments (multiselect)
    "customfield_10269"    // AWS: Tenant (text)
  ],
  "maxResults": 100,
  "nextPageToken": "optional_for_pagination"
}
```

**Response structure:**
```json
{
  "issues": [
    {
      "key": "AWS-18634",
      "fields": {
        "summary": "[BMEDPFT] Richiesta aggiornamento lambda",
        "status": {"name": "In Progress"},
        "customfield_11530": [
          {"objectId": "131", "workspaceId": "8ce4b273-d96f-4c70-8b75-752b50b42b06"}
        ],
        "customfield_11693": {"value": "Staging"}
      }
    }
  ],
  "isLast": false,
  "nextPageToken": "next_page_token_here"
}
```

### Assets Object Resolution

**GET** `/gateway/api/jsm/assets/workspace/{workspaceId}/v1/object/{objectId}`

Resolves Assets object IDs to human-readable labels.

**Example:**
```
GET /gateway/api/jsm/assets/workspace/8ce4b273-d96f-4c70-8b75-752b50b42b06/v1/object/131
```

**Response:**
```json
{
  "id": "131",
  "label": "BMEDPFT",
  "objectType": {
    "name": "Customers"
  },
  "attributes": [
    {
      "objectTypeAttribute": {"name": "Name"},
      "objectAttributeValues": [{"value": "BMEDPFT"}]
    }
  ]
}
```

---

## your-company Custom Field Schema

### CPS Project Fields (High Coverage ~90%)

| Field ID | Name | Type | Purpose | Coverage |
|----------|------|------|---------|----------|
| `customfield_11530` | **Customers** | Assets (cmdb-object) | Tenant/cliente | 90% |
| `customfield_11562` | **Services** | Assets (cmdb-object) | Servizio specifico | 85% |
| `customfield_11693` | **Environment Cloud** | Select option | Ambiente | 80% |
| `customfield_11674` | **Desired Closure Date** | Date | Scadenza secondaria | 60% |

**Assets field format:**
```json
[{"objectId": "131", "workspaceId": "8ce4b273-d96f-4c70-8b75-752b50b42b06"}]
```

**Select field format:**
```json
{"value": "Staging"}
```

### AWS Project Fields (Low Coverage ~30%)

| Field ID | Name | Type | Purpose | Coverage |
|----------|------|------|---------|----------|
| `customfield_10346` | **Assets** | Assets (cmdb-object) | Servizio (same format as CPS) | 30% |
| `customfield_10272` | **Cloud environments** | Multiselect | Ambiente | 20% |
| `customfield_10269` | **Tenant** | Text | Tenant name (free text) | 15% |
| `customfield_11674` | **Desired Closure Date** | Date | Scadenza secondaria | 60% |

**Multiselect field format:**
```json
[{"value": "Development"}, {"value": "Staging"}]
```

**Text field format:**
```json
"bmedpft"
```

---

## Data Extraction Strategy

### Tenant Extraction (Priority Order)

1. **CPS: Assets API** → `customfield_11530` (Customers) → resolve via Assets API → use `label`
2. **AWS: Assets API** → `customfield_10346` (Assets) → resolve via Assets API → extract customer from service label
3. **AWS: Text field** → `customfield_10269` (Tenant) → use directly (uppercase)
4. **Fallback: Regex** → Extract from `summary` field using patterns:
   - `^\[([A-Za-z0-9_-]+)\]` → `[BMEDPFT] Title` → `BMEDPFT`
   - `^([a-z0-9]+)-(?:dev|stag|preprod|demo|prod|mt)-` → `bmedpft-dev-lambda` → `BMEDPFT`

### Environment Extraction (Priority Order)

1. **CPS: Select field** → `customfield_11693` (Environment Cloud) → use `.value` directly
2. **AWS: Multiselect** → `customfield_10272` (Cloud environments) → join multiple `.value` with `, `
3. **Fallback: Regex** → Extract from `summary` field using patterns:
   - `-(?:dev|stag|preprod|demo|prod|mt)-` (case-insensitive, dash-separated)
   - `\b(?:dev|stag|preprod|demo|prod|mt)\b` (case-insensitive, word boundary)

### Due Date Extraction (Priority Order)

1. **Primary** → `duedate` field (ISO 8601 date)
2. **Secondary** → `customfield_11674` (Desired Closure Date)
3. **Fallback** → "—"

**Formatting rules:**
- Date within 30 days → `**YYYY-MM-DD**` (bold)
- Date beyond 30 days → `YYYY-MM-DD` (normal)
- No date → `—`

---

## Assets API Integration

### Caching Strategy

**Cache file**: `reports/.cache/assets-cache.json`
**Format**: `{"objectId": "resolved_label", ...}`
**Behavior**: Persistent across runs, new objectIds resolved and cached automatically

### Resolution Process

1. Check local cache first
2. If not cached, call Assets API: `/gateway/api/jsm/assets/workspace/{workspaceId}/v1/object/{objectId}`
3. Extract `label` from response
4. Store in cache for future use
5. Use concurrent resolution (max 5 parallel requests)

### Error Handling

- **401 Unauthorized** → Token expired, needs refresh
- **404 Not Found** → Object deleted, use objectId as fallback
- **Rate limiting** → Retry with exponential backoff
- **Network errors** → Use cached value or objectId as fallback

---

## JQL Query Patterns

### Three Queries Per Project

**Query 1 - Assigned tickets:**
```
assignee = "user@company.com" AND project = "AWS" AND updated >= "2026-05-01" AND updated < "2026-05-08"
```

**Query 2 - Previously assigned (WAS DURING):**
```
assignee WAS "user@company.com" DURING ("2026-05-01", "2026-05-07") AND assignee != "user@company.com" AND project = "AWS"
```

**Query 3 - Reported tickets:**
```
reporter = "user@company.com" AND project = "AWS" AND updated >= "2026-05-01" AND updated < "2026-05-08"
```

**AWS-specific addition**: Add `AND issuetype not in subTaskIssueTypes()` to exclude subtasks.

### Date Handling

- **JQL date semantics**: `updated <= "2026-05-07"` excludes the entire day
- **Inclusive end date**: Use `updated < "2026-05-08"` to include 2026-05-07
- **DURING clause**: Uses inclusive semantics natively

---

## Implementation Notes

### Field Access Patterns

Custom fields can be accessed from two locations in the API response:
```python
# Method 1: From fields object (preferred)
customer_ids = fields.get("customfield_11530")

# Method 2: From raw issue object (fallback)
customer_ids = raw.get("customfield_11530")
```

### Assets Object ID Extraction

```python
def extract_asset_object_ids(field_value) -> list[str]:
    """Extract objectId values from cmdb-object-cftype field."""
    if not field_value or not isinstance(field_value, list):
        return []
    return [
        item.get("objectId", "")
        for item in field_value
        if isinstance(item, dict) and item.get("objectId")
    ]
```

### Pagination Handling

The enhanced search endpoint uses `nextPageToken` for pagination:
```python
payload = {"jql": "...", "fields": [...], "maxResults": 100}
if next_page_token:
    payload["nextPageToken"] = next_page_token
```

Continue until `response.get("isLast", True)` is `True`.

---

## Error Codes & Troubleshooting

| HTTP Code | Meaning | Solution |
|-----------|---------|----------|
| 401 | Authentication failed | Check token validity, create new token |
| 403 | Permission denied | Verify project access permissions |
| 400 | Invalid JQL | Check JQL syntax, field names |
| 404 | Resource not found | Verify project keys, field IDs |
| 429 | Rate limited | Implement exponential backoff |

### Common Issues

- **Empty custom fields**: Normal for AWS project (~70% empty), implement fallbacks
- **Assets resolution failures**: Use objectId as fallback label
- **JQL date exclusion**: Remember `updated <= "date"` excludes the entire day
- **Field name changes**: Custom field IDs are stable, but names can change in Jira admin
