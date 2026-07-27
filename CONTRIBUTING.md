# Contributing — Weekly Recap Agent

Guida per contribuire al progetto. Descrive branching, criteri di merge, workflow e regole di sicurezza.

---

## Branch attivi

| Branch | Ruolo | Stato |
|--------|-------|-------|
| `main` | Produzione — merge solo via PR | Protetto |
| `gh-jira-cli` | Sviluppo attivo — CLI-native pipeline | Branch principale di lavoro |
| `test/first-run-experience` | Validazione onboarding su macchina pulita | In attesa di merge da gh-jira-cli |

---

## Come contribuire

### Setup

```bash
git clone git@github.com:your-org-1/kiro-personal-hendrikse.git
cd weekly-report-agent
./setup.sh
```

### Workflow

1. Lavora sul branch `gh-jira-cli` (o crea un feature branch da esso)
2. Implementa la modifica
3. Valida:
   ```bash
   pytest tests/ --tb=short -q
   weekly-recap preflight
   ```
4. Committa (Conventional Commits):
   ```bash
   git add <files>
   git commit -m "feat(<scope>): descrizione breve"
   ```
5. Pusha (mai verso `main`):
   ```bash
   git push origin gh-jira-cli
   ```

### Hotfix

Per correzioni urgenti direttamente in produzione:

1. Crea branch `hotfix/<descrizione>` da `main`
2. Applica fix, esegui test e preflight
3. PR: `hotfix/<descrizione>` → `main`
4. Dopo merge, cherry-pick nei branch attivi

---

## Criteri di merge

### gh-jira-cli → test/first-run-experience

- [ ] `weekly-recap preflight` esce con codice 0
- [ ] `pytest tests/` — tutti i test passano
- [ ] Nessun comando ad-hoc necessario per raggiungere lo stato funzionante

### test/first-run-experience → main

- [ ] First-run completa su macchina pulita
- [ ] `./setup.sh` produce ambiente funzionante senza interventi manuali
- [ ] `weekly-recap preflight` esce con codice 0 dopo il setup
- [ ] `weekly-recap generate` produce un recap completo senza errori fatali
- [ ] `pytest tests/` — tutti i test passano
- [ ] Nessun segreto esposto nei commit

---

## Gestione segreti

### File protetti (mai committare)

| Pattern | Contenuto |
|---------|-----------|
| `*.token` | File token singoli |
| `*tokens.json` | Token JSON (es. `~/.ms-graph-tokens.json`) |
| `user-config.json` | Contiene email e handle personali |

### Verifica pre-commit

Il pre-commit hook (`weekly_recap/infra/pre-commit-check.sh`) blocca automaticamente commit con file segreti. Installato da `setup.sh`.

Verifica manuale:
```bash
git diff --cached --name-only | grep -E '(\.token$|tokens\.json$)'
```

---

## Formato commit

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <descrizione>
```

**Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

**Scope:** componente o area (`preflight`, `jira`, `github`, `calendar`, `steering`)

**Esempi:**
```
feat(github): add branch grouping to commit report
fix(preflight): handle missing gh CLI gracefully
docs(steering): update AGENT.md with CLI-native flow
test(filters): add property-based tests for tenant filter
```

---

## Regole per l'agente AI

Definite in [`.kiro/steering/git-workflow.md`](.kiro/steering/git-workflow.md):

- Non cambia branch autonomamente
- Non pusha mai verso `main`
- Esegue test e preflight prima di ogni commit
- Chiede conferma esplicita prima di ogni push
- Blocca file segreti nello staging
- Propone integrazione di comandi ad-hoc in script versionati
