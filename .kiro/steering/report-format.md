---
inclusion: always
---

# Report Format — Weekly Recap

Questo file definisce la struttura Markdown esatta che l'agente deve produrre quando genera il weekly recap. L'agente DEVE seguire questo formato con precisione.

## Output File Path

**CRITICO**: Il report DEVE essere salvato in `weekly-recap/reports/weekly-recap-{start_date}.md` (es. `weekly-recap/reports/weekly-recap-2026-03-19.md`). NON scrivere il file nella root di `weekly-recap/`. La cartella `reports/` è gitignored — i report sono solo locali e non devono essere committati.

---

## Header del Report

Il report DEVE iniziare con il seguente blocco header:

```
# Weekly Recap — {Nome Utente}
Period: {start_date} – {end_date}
Generated: {data_generazione}
```

- `{Nome Utente}` è il campo `name` da `user-config.json`
- `{start_date}` e `{end_date}` sono date in formato ISO 8601 (es. `2025-01-06`)
- `{data_generazione}` è la data corrente al momento della generazione (ISO 8601)
- Il separatore tra le date è un en-dash (`–`), NON un trattino

---

## Ordine delle Sezioni

Il recap DEVE contenere le sezioni in questo ordine esatto:

1. **Riepilogo Personale** — sempre presente
2. **Jira** (sezioni per stato) — sempre presente (con dati, messaggio vuoto, o errore)
3. **GitHub** — sempre presente (con dati, messaggio vuoto, o errore)
4. **Calendar** — sempre presente (con dati, messaggio vuoto, o errore)
5. **Riepilogo** — sempre presente alla fine

Le sezioni sono separate da linee orizzontali (`---`).

---

## Sezione Riepilogo Personale

```
## Riepilogo Personale
- Ticket Jira: Done (N), In Progress (N), To Do (N)
- Commits: N
- PRs aperte: N
- PRs merged: N
- Meeting: N (Xh totali)
```

- "Ticket Jira" mostra i conteggi per macro-stato: Done (completati/resolved/closed), In Progress (in corso/take in charge/in test), To Do (da fare/backlog). I conteggi si basano sulle **attività deduplicate** (ticket con stessa descrizione uniti contano come 1).
- Se una sorgente dati non è disponibile, il suo contributo è 0.
- "Meeting" sempre presente nel riepilogo. Se il calendario non è configurato, mostra 0 (0h totali).

---

## Sezione Jira — Raggruppamento per Stato

I ticket Jira sono raggruppati per **stato** usando intestazioni H2. Ogni gruppo ha una tabella flat.

### Gruppi di Stato e Ordine

| Ordine | Label H2 | Stati Jira inclusi |
|--------|----------|-------------------|
| 1 | Completati | Done, Resolved, Closed |
| 2 | In Test / In Attesa | In Test, Waiting for Customer |
| 3 | In Corso | In Progress, Take in charge |
| 4 | Da Fare | To Do, Backlog |
| 5 | Annullati | Cancelled, Declined, Rejected |

### Regole

- Gruppi senza ticket vengono **omessi**
- All'interno di ogni gruppo, ticket ordinati per key

### Formato Tabella


>## {Label Stato}
>| Ticket | Tenant | Ambiente | Descrizione | Commits | Scadenza |
>|--------|--------|----------|-------------|---------|----------|
>| [KEY](url) | TENANT | ENV | Summary | [`sha`](url) | YYYY-MM-DD |


**Colonne:**
1. **Ticket** — Link Markdown: `[AWS-18634](https://your-company.atlassian.net/browse/AWS-18634)`. Se due ticket (AWS-* e CPS-*) hanno la stessa descrizione, unirli in una riga: `[AWS-18634](url), [CPS-1205](url)`
2. **Tenant** — Estratto dal titolo (o "—")
3. **Ambiente** — DEV, STAG, PREPROD, DEMO, PROD, MT (o "—"). Più ambienti separati da virgola.
4. **Descrizione** — Il campo summary del ticket
5. **Commits** — SHA corti linkati dei commit il cui messaggio contiene la key del ticket (cross-reference GitHub). Se nessun commit corrisponde: "—"
6. **Scadenza** — ISO 8601. In grassetto se entro 30 giorni. "—" se assente.

### Deduplicazione Ticket con Stessa Descrizione

Quando due ticket (tipicamente uno AWS-* e uno CPS-*) hanno lo stesso campo `summary` (case-insensitive, ignorando spazi extra), vengono uniti in una singola riga:
- La colonna **Ticket** mostra entrambi i link separati da virgola: `[AWS-18634](url), [CPS-1205](url)`
- La colonna **Commits** mostra i commit di entrambi i ticket
- Conta come **1 attività** nel riepilogo (non 2)
- Lo stato usato è quello del ticket più "avanzato" (Done > In Progress > To Do)

---

## Sezione GitHub

Raggruppata per repository:

```
## GitHub

### {repo_name}
**Commits:** N
| SHA | Message | Date |
|-----|---------|------|
| [`abc1234`](url) | Message | 2025-01-10 |

**Pull Requests:**
| # | Title | Status | URL |
|---|-------|--------|-----|
| 42 | Title | opened/merged/closed | url |
```

---

## Sezione Calendar

Sempre presente nel report. Orari in CET/CEST.

Quando `team_members` è configurato: eventi raggruppati per team member + "Other Meetings".
Quando assente: lista flat "Meetings".

---

## Sezione Riepilogo Finale

```
## Riepilogo

### Per Stato
| Stato | Conteggio |
|-------|-----------|
| Completati | N |
| In Corso | N |
| Da Fare | N |

### Scadenze Imminenti (≤30 giorni)
| Ticket | Scadenza | Descrizione |
|--------|----------|-------------|
| [KEY](url) | **YYYY-MM-DD** | Summary |
```

- Solo gruppi con conteggio > 0
- Solo ticket con scadenza effettiva entro 30 giorni **E che NON sono in stato Completati/Annullati** (Done, Resolved, Closed, Rejected, Cancelled). Le scadenze di ticket già chiusi non sono rilevanti.
- I conteggi si basano sulle righe della tabella (attività deduplicate), non sui singoli ticket ID

---

## Messaggi Sezione Vuota

| Condizione | Messaggio |
|------------|-----------|
| Nessuna attività Jira | `_Nessuna attività Jira trovata per questo periodo._` |
| Nessuna attività GitHub | `_No GitHub activity found for this period._` |
| Nessun evento calendar | `_No calendar events found for this period._` |

---

## Formato Errori

```
⚠️ Jira data unavailable: {error}. Ensure acli is authenticated (acli jira auth login).
⚠️ GitHub data unavailable: {error}. Ensure gh is authenticated (gh auth login).
⚠️ Calendar data unavailable: {error}.
```

Quando una sorgente ha un errore, il suo contributo al Riepilogo Personale è 0.
