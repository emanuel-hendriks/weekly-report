# Weekly Recap Agent

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20WSL2-lightgrey)

Un agente [Kiro](https://kiro.dev) che genera il tuo recap settimanale personale interrogando **Jira** (REST API), **GitHub** (Search API + GraphQL via httpx) e il **calendario Outlook** (MS Graph), in parallelo. Produce un report Markdown strutturato.

> È un tool individuale — genera il recap di una singola persona basandosi sulle sue credenziali e configurazione.

---

## Indice

1. [Prerequisiti](#prerequisiti)
2. [Setup (prima volta)](#setup-prima-volta)
3. [Uso](#uso)
4. [Architettura](#architettura)
6. [Struttura Progetto](#struttura-progetto)
7. [Licenza](#licenza)

---

## Prerequisiti

| Software | Scopo |
|----------|-------|
| Python 3.11+ | Package e script |
| GitHub CLI (`gh`) | Token OAuth per le API GitHub |
| Jira API Token | Fetch ticket via REST API |
| git | Versionamento |

---

## Setup (prima volta)

```
 1. Installa prerequisiti
 2. Autenticati con GitHub
 3. Configura il token Jira
 4. Autentica MS Graph (calendario)
 5. Configura user-config.json
 6. Esegui setup.sh (installa + valida + sentinel)
```

> Se chiedi un recap senza aver completato il setup, il comando `weekly-recap preflight` rileva cosa manca. L'agente, via steering ([`.kiro/steering/AGENT.md`](.kiro/steering/AGENT.md)), auto-fixa ciò che può (config, setup.sh) e ti indica i passi manuali (auth, token).

### 1. Installa prerequisiti

- **Python 3.11+**: [python.org/downloads](https://python.org/downloads/)
- **GitHub CLI**: [cli.github.com](https://cli.github.com/)
- **git**: [git-scm.com](https://git-scm.com)

### 2. Autenticati con GitHub

```bash
gh auth login
```

I fetcher GitHub usano `httpx` per chiamare le API direttamente. `gh` serve solo come portachiavi: all'avvio il fetcher esegue `gh auth token` per leggere il token OAuth, poi fa tutte le richieste HTTP via httpx. Il token è salvato in `~/.config/gh/hosts.yml`.

### 3. Configura il token Jira

Il fetcher Jira (`weekly_recap/fetchers/fetch_jira.py`) chiama la REST API di Jira Cloud via HTTP. Per autenticarsi serve un API token personale.

Genera il token da [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) e salvalo:

```bash
mkdir -p ~/.config/.jira
echo 'export JIRA_API_TOKEN=<YOUR_TOKEN_HERE>' > ~/.config/.jira/.token
```

Il file deve contenere una singola riga:

```
export JIRA_API_TOKEN=<YOUR_TOKEN_HERE>
```

Poi aggiungi al tuo `~/.bashrc` o `~/.zshrc`:

```bash
source ~/.config/.jira/.token
```

`fetch_jira.py` costruisce l'header `Authorization: Basic` con `base64(email:token)` (vedi `_prepare_auth()`).

### 4. Autentica MS Graph (calendario)

```bash
python3 -m weekly_recap.auth.setup_graph_token
```

Segui le istruzioni: apri [microsoft.com/devicelogin](https://microsoft.com/devicelogin), inserisci il codice mostrato, accedi con il tuo account aziendale.

Il token viene salvato in `~/.ms-graph-tokens.json` e si auto-rinnova ad ogni esecuzione. Se scade (~90 giorni senza uso), ripeti questo step.

### 5. Configura user-config.json

```bash
cp user-config.json.template user-config.json
```

Il template ha già i valori condivisi del team (tenant_id, client_id, workspace_id, orgs, projects). Devi solo cambiare i campi personali:

```json
{
  "name": "Il Tuo Nome",
  "jira_username": "tuo.nome@company.com",
  "github_handle": "TuoGitHubUsername",
  "calendar_email": "tuo.nome@company.com"
}
```

| Campo | Descrizione |
|-------|-------------|
| `name` | Il tuo nome (appare nel report) |
| `jira_url` | URL dell'istanza Jira |
| `jira_username` | La tua email Jira (usata anche per auth REST API) |
| `github_handle` | Il tuo username GitHub |
| `github_orgs` | Organizzazioni GitHub da interrogare |
| `jira_projects` | Progetti Jira da interrogare |
| `jira_assets_workspace_id` | ID workspace Jira Assets (pre-compilato) |
| `calendar_email` | Email per il calendario MS Graph |
| `ms_graph_tenant_id` | Azure AD tenant ID (pre-compilato) |
| `ms_graph_client_id` | Azure AD app client ID (pre-compilato) |
| `team_members` | (opzionale) Colleghi per raggruppare eventi calendario |
| `language` | Lingua report: `"it"` o `"en"` |

### 6. Esegui setup

```bash
./setup.sh
```

Lo script:
- Verifica che `gh` sia installato e autenticato
- Valida `user-config.json` (no placeholder)
- Installa il package in editable mode (`pip install -e .`)
- Scrive `.setup-complete` (sentinel per il preflight)

Se `weekly-recap` non viene trovato dopo il setup:

```bash
# ~/.zshrc o ~/.bashrc
export PATH="$HOME/.local/bin:$PATH"
source ~/.zshrc
```

Oppure usa un virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
./setup.sh
```

---

## Uso

### Configurazione Kiro (`.kiro/`)

La cartella `.kiro/` configura il comportamento dell'agente AI nell'IDE Kiro: steering files (regole always-on), hooks (automazioni), skills e un custom agent con permessi ristretti.

> 📖 Documentazione completa: [wiki — Kiro Configuration](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Kiro-Configuration)

### One-click (Hook Kiro) — modo più veloce

Bottone **"Generate Weekly Recap"** nella sezione *Agent Hooks* dell'explorer Kiro. Un click: preflight + generazione. Nessun comando da digitare.

### Chat Kiro

Dalla chat dell'IDE Kiro, con il workspace `weekly-report-agent` aperto:

```
genera il recap settimanale
weekly recap dal 2026-05-05 al 2026-05-11
```

### Custom Agent

Il progetto include un **custom agent** dedicato in `.kiro/agents/weekly-report.json`. È un agente con permessi ristretti pensato per l'uso quotidiano, attivabile dalla Kiro CLI o dalla chat Kiro IDE quando il workspace `weekly-report-agent` è aperto:

- **Read-only** sul codice sorgente — può leggere ma non modificare `weekly_recap/`, `tests/`, `.kiro/`
- **Write** solo su `user-config.json` e `reports/`
- **Shell** limitata a comandi allowlistati: `weekly-recap preflight`, `weekly-recap generate`, `setup.sh`
- **Nessun accesso** a git push, rm -rf, o comandi distruttivi

**Attivazione:**

```bash
# All'inizio di una sessione
kiro-cli --agent weekly-report

# Oppure durante una sessione attiva
kiro /agent swap
# → seleziona "weekly-report" dalla lista
```

Una volta attivo, l'agente risponde ai prompt di generazione recap rispettando i permessi scoped.

### CLI

Da un terminale qualsiasi (IDE integrato, iTerm, Terminal.app), posizionato nella root del progetto (`weekly-report-agent/`):

```bash
weekly-recap preflight                    # Verifica prerequisiti
weekly-recap generate                     # Recap ultimi 7 giorni
weekly-recap generate 2026-05-05 2026-05-11  # Periodo specifico
weekly-recap --help
```

### Rotazione Credenziali

Da un terminale posizionato nella root del progetto (per MS Graph) o da qualsiasi directory (per `gh` e Jira):

| Credenziale | Comando | Quando |
|-------------|---------|--------|
| GitHub | `gh auth refresh` | Se revocato |
| Jira | Rigenera token da [Atlassian](https://id.atlassian.com/manage-profile/security/api-tokens), aggiorna `~/.config/.jira/.token` | Se revocato |
| MS Graph | `python3 -m weekly_recap.auth.setup_graph_token` | Dopo ~90 giorni di inattività |

---

## Architettura

> Per il diagramma completo e le decisioni architetturali, vedi la [wiki — Architecture](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Architecture).

```
┌─────────────────────────────────────────────────────────────┐
│  Utente → "weekly recap" / click hook / CLI                 │
└──────────┬──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│  weekly-recap CLI (Python package installabile)              │
│  1. preflight (validazione)                                  │
│  2. generate (orchestratore parallelo)                       │
└──────────┬───────────────────────────────────────────────────┘
           │ subprocess.Popen (4 processi paralleli)
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Fetcher Paralleli                                           │
│  • fetch_jira.py       → Jira REST API (6 query parallele)   │
│  • fetch_github_prs.py → httpx async (6 query parallele)     │
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

## Struttura Progetto

> Per il dettaglio di ogni modulo (ruolo, input/output, dipendenze), vedi la [wiki — Modules](https://github.com/your-org-1/kiro-personal-hendrikse/wiki/WRA-Modules).

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

## Licenza

[MIT](LICENSE) © 2026 your-org-1
