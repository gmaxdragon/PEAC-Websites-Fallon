# PEAC Community

Public community website and authenticated private workspace, sharing one SQLite database.

## Local setup (Python 3.10+)

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python peac.py
```

On first start, create an administrator in your terminal. There is no default password.
Open `http://127.0.0.1:5000/` for the public site and `/console` for the private workspace.
The default database is `data/peac.sqlite3`. Do not commit or publicly share it.

## Tests

```sh
python -m unittest -v test_peac_newsletter test_regressions
python -m pip install playwright==1.55.0
python -m playwright install --with-deps chromium webkit
python tests/public_ui_check.py
python tests/audit_ui_check.py
```

The audit suite creates disposable data and must never be directed at production.
The existing live UI suite is read-only. See `DEPLOY.md` for hosted settings.
All icons are same-origin SVG symbols in `icons.svg`; public content is never rewritten to remove user-supplied characters.
Template files contain headers only. Fill in actual records before importing. Named weekly records require a Monday date.
