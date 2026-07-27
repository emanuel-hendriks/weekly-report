# weekly_recap — Guida al Codice

> Riferimento tecnico per il package `weekly_recap`.
> Descrive architettura, flusso dati, moduli e come estendere la pipeline.

---

## Indice

1. [Overview](#overview)
2. [Struttura del package](#struttura-del-package)
3. [Grafo delle dipendenze](#grafo-delle-dipendenze)
4. [Moduli principali](#moduli-principali)
   - [cli.py](#clipy)
   - [preflight.py](#preflightpy)
   - [run_recap.py](#run_recappy)
   - [generate_full_report.py](#generate_full_reportpy)
5. [Fetchers](#fetchers)
   - [fetch_jira.py](#fetch_jirapy)
   - [fetch_github_prs.py](#fetch_github_prspy)
   - [fetch_github_commits.py](#fetch_github_commitspy)
   - [fetch_calendar.py](#fetch_calendarpy)
6. [Processing](#processing)
7. [Auth](#auth)
8. [Exit codes](#exit-codes)
9. [Come aggiungere un nuovo fetcher](#come-aggiungere-un-nuovo-fetcher)

---

## Overview

`weekly_recap` è un package Python installabile che genera un report settimanale personale aggregando dati da tre sorgenti:

| Sorgente | API | Output cache |
|----------|-----|--------------|
| Jira | REST API v3 | `jira-issues.json` |
| GitHub | `gh` CLI (search) | `github-prs.json`, `git-commits.json` |
| Calendar | MS Graph API | `calendar.json` |

**Flusso in 30 secondi:**

```
weekly-recap preflight   →  verifica ambiente (gh, acli, token, config)
weekly-recap generate    →  4 fetcher in parallelo → JSON cache → report Markdown
```

Il report finale è un file Markdown in `reports/weekly-recap-{data}.md`.

---

## Struttura del package

```
weekly_recap/
├── __init__.py                  ← Package marker
├── cli.py                       ← Entry point CLI (weekly-recap)
├── preflight.py                 ← Validazione ambiente
├── run_recap.py                 ← Orchestratore parallelo
├── generate_full_report.py      ← Assemblaggio report Markdown
│
├── fetchers/                    ← Script standalone (subprocess)
│   ├── fetch_jira.py            ← Jira REST API
│   ├── fetch_github_prs.py      ← GitHub PRs (gh CLI)
│   ├── fetch_github_commits.py  ← GitHub commits (gh CLI)
│   └── fetch_calendar.py        ← MS Graph Calendar
│
├── processing/                  ← Moduli di elaborazione (import)
│   ├── models.py                ← Dataclass + costanti
│   ├── tenant_extractor.py      ← Regex tenant fallback
│   ├── environment_extractor.py ← Regex ambiente fallback
│   ├── due_date_formatter.py    ← Scadenze + bold
│   ├── summary_calculator.py    ← Conteggi per stato
│   └── report_generator.py      ← Markdown output
│
├── auth/                        ← OAuth2 MS Graph
│   ├── setup_graph_token.py     ← Device code flow (interattivo)
│   └── ensure_graph_token.py    ← Token refresh (automatico)
│
└── infra/                       ← Script infrastruttura
    ├── apply-branch-protection.sh
    └── pre-commit-check.sh
```

---

## Grafo delle dipendenze

> 📐 Apri [`../graphs/architecturev2.drawio`](../graphs/architecturev2.drawio) con draw.io (VS Code extension o [app.diagrams.net](https://app.diagrams.net)) per il diagramma interattivo.

Il flusso è top-down:

1. **CLI** (`cli.py`) → chiama `preflight` o `run_recap`
2. **Orchestrator** (`run_recap.py`) → lancia 4 fetcher in parallelo via subprocess
3. **Fetchers** → scrivono JSON in `reports/.cache/`
4. **Report Generator** (`generate_full_report.py`) → legge cache, importa `processing/`, produce Markdown

---

## Moduli principali

### cli.py

Entry point registrato in `pyproject.toml` come script `weekly-recap`.

| Comando | Azione |
|---------|--------|
| `weekly-recap preflight` | `preflight.main()` |
| `weekly-recap generate [start] [end]` | `run_recap.main()` |
| `weekly-recap --help` | Mostra usage |

---

### preflight.py

Valida che l'ambiente sia pronto. Esce con codice **0** (ready) o **1** (not ready).

**Check eseguiti (in ordine):**

| # | Check | Bloccante |
|---|-------|-----------|
| 1 | `.setup-complete` esiste | ✓ |
| 2 | `user-config.json` valido, no placeholder | ✓ |
| 3 | `jira_username` è email valida | ✓ |
| 4 | `github_handle` senza `@` o spazi | ✓ |
| 5 | `calendar_email` è email valida | ✓ |
| 6 | `ms_graph_tenant_id` e `client_id` presenti | ✓ |
| 7 | `gh` installato e autenticato | ✓ |
| 8 | `acli` installato e autenticato | ⚠ warning |
| 9 | `python3` disponibile | ✓ |
| 10 | `~/.ms-graph-tokens.json` esiste | ✓ |

**Auto-fix:** se `acli` non è autenticato ma il token file esiste, tenta auto-login.

---

### run_recap.py

Orchestratore. Lancia i 4 fetcher in parallelo, poi genera il report.

**Input:** `[start_date] [end_date]` (default: ultimi 7 giorni)

**Flusso:**
1. Carica `user-config.json`
2. Lancia 4 fetcher in parallelo (`subprocess.Popen`)
3. Attende completamento (timeout 5 min per fetcher)
4. Chiama `generate_full_report.main()` in-process (nessun subprocess)

**Resilienza:** se un fetcher fallisce, gli altri continuano. Il report viene generato con i dati disponibili.

**Nota:** il report generator gira in-process per eliminare l'overhead di un subprocess aggiuntivo (~0.3s). I fetcher restano come subprocess separati per isolamento e parallelismo reale (nessun GIL).

---

### generate_full_report.py

Legge i JSON dalla cache, processa i ticket, genera il report Markdown.

**Input:** `start_date end_date` (argomenti CLI)

**Legge:**
- `reports/.cache/jira-issues.json`
- `reports/.cache/git-commits.json`
- `reports/.cache/github-prs.json`
- `reports/.cache/calendar.json`

**Produce:** `reports/weekly-recap-{start_date}.md`

**Pipeline interna:**

| Step | Funzione | Descrizione |
|------|----------|-------------|
| 1 | `match_commits_to_tickets()` | Associa commit a ticket per key (regex) |
| 2 | `process_tickets()` | Estrae tenant, ambiente, due date |
| 3 | `deduplicate_tickets()` | Unisce ticket con stesso summary |
| 4 | `SummaryCalculator.calculate()` | Conta per status group |
| 5 | `ReportGenerator.generate()` | Assembla Markdown |

---

## Fetchers

Ogni fetcher è uno script standalone. Zero import dal package. Comunicano via JSON su disco in `reports/.cache/`.

### fetch_jira.py

| | |
|---|---|
| **API** | Jira REST v3 (`POST /rest/api/3/search/jql`) |
| **Input CLI** | `jira_username projects_json start_date end_date` |
| **Auth** | Token da `~/.config/.jira/.token` + email da config |
| **Parallelismo** | 3 JQL × N progetti, ThreadPoolExecutor (6 worker) |
| **Output** | `reports/.cache/jira-issues.json` |

**Post-processing:** deduplicazione per key, risoluzione Assets object ID → label (con cache locale `assets-cache.json`), mapping ambiente.

### fetch_github_prs.py

| | |
|---|---|
| **API** | `gh search prs` (subprocess) |
| **Input CLI** | `github_handle orgs_json start_date end_date` |
| **Query** | 3 per org (created, merged, closed-unmerged), parallelo |
| **Output** | `reports/.cache/github-prs.json` |

### fetch_github_commits.py

| | |
|---|---|
| **API** | `gh search commits` + `gh api graphql` (subprocess) |
| **Input CLI** | `[--full] github_handle orgs_json start_date end_date` |
| **Strategia** | Ibrida: Search API (default branch) + GraphQL (non-default branch) |
| **Parallelismo** | Phase 1: 1 search per org (parallelo). Phase 2: 1 GraphQL per repo (parallelo) |
| **Output** | `reports/.cache/git-commits.json` |

**Modalità (default = fast):**

| Modalità | Flag | Strategia | Copertura | Tempo |
|----------|------|-----------|-----------|-------|
| Fast (default) | — | Search API + GraphQL | 100% | ~2-3s |
| Full (legacy) | `--full` | Search → list branches → Commits API per branch | 100% | ~5-6s |

**Phase 1 (Search API):** `gh search commits --author=... --owner=...` per org. Restituisce commit sul default branch + scopre i repo attivi.

**Phase 2 (GraphQL):** Una singola query GraphQL per repo che combina listing branch + commit history di tutti i branch non-default. Filtra per email autore lato client. Solo i commit non già trovati in Phase 1 vengono aggiunti.

### fetch_calendar.py

| | |
|---|---|
| **API** | MS Graph (`GET /me/calendarView`) |
| **Input CLI** | `start_date end_date` |
| **Auth** | Token da `~/.ms-graph-tokens.json`, refresh automatico |
| **Paginazione** | Max 20 pagine (1000 eventi) |
| **Output** | `reports/.cache/calendar.json` |

---

## Processing

Moduli di elaborazione importati da `generate_full_report.py`.

| Modulo | Ruolo |
|--------|-------|
| `models.py` | Dataclass (`JiraTicket`, `ProcessedTicket`, ecc.) + costanti (`STATUS_GROUPS`, `STATUS_ORDER`, `STATUS_TO_GROUP`) |
| `tenant_extractor.py` | Regex fallback: `[TENANT]` prefix o `tenant-env-` pattern |
| `environment_extractor.py` | Regex fallback: `-env-` o word boundary. Riconosce DEV, STAG, PREPROD, DEMO, PROD, MT |
| `due_date_formatter.py` | Fallback chain: `duedate` → `customfield_11674` → "—". Bold se ≤30 giorni |
| `summary_calculator.py` | Conteggi per status group + scadenze imminenti |
| `report_generator.py` | Assembla Markdown finale (header, tabelle, riepilogo) |

---

## Auth

| Script | Ruolo | Interattivo | Exit codes |
|--------|-------|-------------|------------|
| `setup_graph_token.py` | Setup iniziale OAuth2 (device code flow) | Sì (browser) | — |
| `ensure_graph_token.py` | Refresh automatico token | No | 0=ok, 1=refresh fallito, 2=file mancante |

Token salvato in `~/.ms-graph-tokens.json`. Config (`tenant_id`, `client_id`) letta da `user-config.json`.

---

## Exit codes

Convenzione condivisa da tutti gli script:

| Codice | Significato |
|--------|-------------|
| **0** | Successo (incluso zero risultati) |
| **1** | Prerequisito mancante (CLI non installata, auth fallita, config mancante) |
| **2** | Errore API dopo auth riuscita (risultati parziali possono essere scritti) |

---

## Come aggiungere un nuovo fetcher

1. Crea `weekly_recap/fetchers/fetch_nuovo.py` con `main()` standalone
2. Accetta argomenti CLI, scrivi output JSON in `reports/.cache/`
3. Aggiungi la entry nella lista `fetchers` in `run_recap.py`
4. Aggiorna `generate_full_report.py` per leggere il nuovo JSON
5. Aggiungi test in `tests/test_fetch_nuovo.py`
