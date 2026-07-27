# tests/

166 test, ~4 secondi. Nessun mock di rete — i test verificano logica di parsing, filtering e normalizzazione.

## Esecuzione

```bash
pytest tests/ -q              # Rapido
pytest tests/ -v              # Verbose
pytest tests/ -k "jira"       # Solo test Jira
```

## Struttura

| File | Cosa testa | Tipo |
|------|-----------|------|
| `test_preflight.py` | Validazione ambiente (config, tools, auth) | Unit |
| `test_cli.py` | Dispatch sottocomandi (`preflight`, `generate`, `--help`) | Unit |
| `test_fetch_jira.py` | Parsing response Jira, normalizzazione campi, deduplicazione | Unit |
| `test_fetch_github_commits.py` | Validazione input, normalizzazione commit API, deduplicazione per SHA, branch merge | Unit |
| `test_fetch_github_prs.py` | Parsing PR, categorizzazione (open/merged/closed), deduplicazione per URL | Unit |
| `test_resolve_assets.py` | Risoluzione Assets object ID → label, cache hit/miss | Unit |
| `test_setup.py` | Validazione `setup.sh` (sentinel file, dipendenze) | Unit |

## Property-based testing (Hypothesis)

Hypothesis è usato per generare input random e verificare proprietà invarianti.

La cartella `.hypothesis/` (gitignored) contiene il database locale di Hypothesis: controesempi trovati, costanti di copertura. Si rigenera automaticamente al primo `pytest`.

## Convenzioni

- Nessun test chiama API reali — solo logica locale
- Fixture in-file (no `conftest.py` condiviso)
- Nomi classi raggruppano test per funzionalità (`TestValidateDate`, `TestDeduplicateCommits`)
- Exit code convention testata: 0 = ok, 1 = prerequisito mancante, 2 = errore API
