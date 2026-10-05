# PEAC Websites Fallon

Complete runnable source of truth for the PEAC public website and private team console.

## Direct editing from ChatGPT

This repository is connected to ChatGPT with write access. Future requests such as:

- "center the ribbon"
- "change the public homepage copy"
- "move the quote card"
- "change the private dashboard"
- "update sign-up"
- "change Compliments or Lunch Buddies"
- "fix a bug and publish it"

can be applied directly to `main`. When the hosted service is connected to this repository, successful pushes can redeploy the live site automatically.

## Current version

PEAC Community **v7.1**:

- public PEAC website
- centered/stable green ribbon
- daily Quote of the Day
- Lunch Buddies public request form
- approval-gated PEAC member sign-up
- private authenticated console
- compliment logging and spreadsheet imports
- line, bar and pie reporting
- campaigns and notes
- private Lunch Buddies queue
- PEAC Assistant
- SQLite persistence
- local demo mode
- Railway/Gunicorn hosted-mode configuration

The Python backend in this repository was reconstructed byte-for-byte from the tested v7.1 runtime archive and syntax-checked before commit.

## Key files

| File | Purpose |
| --- | --- |
| `peac.py` | App entrypoint |
| `wsgi.py` | Gunicorn entrypoint |
| `peac_core.py` | Data, analytics and forecasting core |
| `peac_community.py` | Public/private community services |
| `portal_auth.py` | Accounts, sessions and permissions |
| `portal_server.py` | HTTP/API routing |
| `peac_people.py` | Named weekly compliment logging |
| `peac_import.py` | Spreadsheet import |
| `peac_assistant.py` | Private PEAC Assistant |
| `peac_mail.py` | Notification draft/send safeguards |
| `public.html`, `public.js`, `community.css` | Public site |
| `login.html`, `login.js` | Team sign-in and sign-up requests |
| `console.html`, `console.js`, `console.css` | Private console |
| `style.css`, `script.js`, `charts.js` | Dashboard, charts and imports |
| `railway.toml` | Railway deployment configuration |
| `.github/workflows/ci.yml` | Push validation |

## Local demo

On Windows, double-click:

```text
START_DEMO.bat
```

Or create a real local database with:

```text
START_PEAC.bat
```

Public site:

```text
http://127.0.0.1:5000/
```

Private console:

```text
http://127.0.0.1:5000/console
```

## Publishing

See [DEPLOY.md](DEPLOY.md).

Hosted deployment requires:

- HTTPS
- a persistent database volume
- `PEAC_DEPLOY_MODE=hosted`
- a private database path such as `/data/peac.sqlite3`
- an administrator bootstrap account on first start

## Privacy

This GitHub repository is currently **public**. Do not commit:

- student names or rosters
- Lunch Buddies submissions
- PEAC member passwords
- SMTP/email credentials
- `.env` files
- SQLite databases
- private JSON/CSV exports

The included `.gitignore` blocks the common private/runtime files, but repository visibility should still be changed to **private before real school use**.

## Validation

GitHub Actions checks every push for:

- Python syntax
- JavaScript syntax
- hosted-mode startup
- `/api/health` availability

Local v7.1 release validation also covered the larger backend and browser regression suites before this repository was promoted to the source of truth.
