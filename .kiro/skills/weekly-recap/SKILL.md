---
name: weekly-recap
description: Generate a personal weekly activity recap from Jira, GitHub, and Outlook calendar. Produces a Markdown report.
---

# Weekly Recap

Genera il recap settimanale personale. Esegue preflight, fetching parallelo da 4 sorgenti (Jira, GitHub PRs, GitHub commits, Calendar) e genera un report Markdown.

---

## Trigger

- "generate weekly recap"
- "/weekly-recap"
- "create my weekly recap"
- "weekly recap for last week"
- "recap my activity"
- "genera il recap settimanale"
- "weekly recap dal {start_date} al {end_date}"

---

## Flow

### 1. Preflight (obbligatorio)

```bash
weekly-recap preflight
```

- Exit 0 → procedi al passo 2
- Exit 1 → mostra output all'utente, tenta auto-fix dove possibile (vedi `.kiro/steering/AGENT.md` sezione "Onboarding Check")

### 2. Generate

```bash
# Ultimi 7 giorni (default)
weekly-recap generate

# Periodo specifico
weekly-recap generate {start_date} {end_date}
```

Il comando orchestra tutto: fetch parallelo → report Markdown.

### 3. Output

- Report: `reports/weekly-recap-{start_date}.md`

---

## Regole

- Eseguire sempre dalla root del progetto (`weekly-report-agent/`)
- Mai chiamare script individuali (fetch_jira.py, fetch_github_commits.py, ecc.)
- Mai riusare dati cachati da esecuzioni precedenti
- Mai saltare il preflight
- Se una sorgente fallisce, le altre continuano (report parziale)

---

## Reference

- [`.kiro/steering/AGENT.md`](.kiro/steering/AGENT.md) — workflow completo, preflight gate, error handling
- [`.kiro/steering/report-format.md`](.kiro/steering/report-format.md) — struttura output Markdown
