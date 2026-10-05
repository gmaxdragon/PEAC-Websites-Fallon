# Deploy PEAC

The recommended deployment target is Railway because this app needs Python plus persistent SQLite storage.

## 1. Protect the source repository

Before using real student or Lunch Buddies data, change `gmaxdragon/PEAC-Websites-Fallon` to a **private** GitHub repository.

No database or private data belongs in GitHub.

## 2. Create the hosted service

Connect Railway to:

```text
gmaxdragon/PEAC-Websites-Fallon
```

Deploy the `main` branch.

The repository already contains `railway.toml`, which starts:

```text
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60 wsgi:app
```

and checks:

```text
/api/health
```

## 3. Add persistent storage

Attach a Railway volume at:

```text
/data
```

Set:

```text
PEAC_DB_PATH=/data/peac.sqlite3
```

Without a persistent volume, the database can disappear during a redeploy.

## 4. First-start variables

Set these variables for the first deployment:

```text
PEAC_DEPLOY_MODE=hosted
PEAC_DB_PATH=/data/peac.sqlite3
PEAC_ADMIN_USERNAME=<your admin username>
PEAC_ADMIN_DISPLAY_NAME=<your display name>
PEAC_ADMIN_PASSWORD=<a unique 12+ character password>
```

The app creates that administrator only when the hosted database has no users.

After you have successfully signed in to the hosted console, remove `PEAC_ADMIN_PASSWORD` from the hosting environment. Do not put it in GitHub.

## 5. Generate HTTPS domain

Generate a public HTTPS domain in Railway.

Verify:

- `/` loads the public site
- `/api/health` returns healthy status
- `/console` redirects unsigned users to sign-in
- sign-up requests require administrator approval
- restarting/redeploying keeps the same database records

## 6. Automatic updates

Keep Railway connected to the `main` branch.

Then this workflow becomes:

1. Ask ChatGPT for a website change.
2. ChatGPT edits this GitHub repository.
3. GitHub Actions checks the push.
4. Railway redeploys the new `main`.
5. Verify the live site.

## School use

A working public URL is not the same as school approval. Before storing real student names or Lunch Buddies requests, confirm your school's requirements for student data, account access and external hosting. Test the final HTTPS domain on the actual managed Chromebook/network.
