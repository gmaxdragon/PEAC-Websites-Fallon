# PEAC Websites Fallon

Source of truth for the PEAC public website and private team-console interface.

## Direct editing from ChatGPT

This repository is connected to ChatGPT with write access. Future requests such as:

- "center the ribbon"
- "change the public homepage copy"
- "move the quote card"
- "change the private dashboard"
- "update sign-up"
- "change Compliments or Lunch Buddies UI"

can be applied directly to the files in this repository from chat.

## Website files

| File | Purpose |
| --- | --- |
| `public.html` | Public PEAC website |
| `public.js` | Public-site behavior and Lunch Buddies form |
| `community.css` | Shared public/login styling and v7.1 ribbon/quote layout |
| `login.html` | Private-console sign-in and sign-up request page |
| `login.js` | Login and approval-gated sign-up behavior |
| `console.html` | Private PEAC team console |
| `console.css` | Private-console layout and responsive styling |
| `console.js` | Private-console navigation, Compliments, Lunch Buddies, Assistant, settings |
| `style.css` | Dashboard, charts, imports, reports and shared console styles |
| `script.js` | Dashboard data, chart, import, note and campaign behavior |
| `auth.js` | Authenticated API helper |
| `charts.js` | Chart/date aggregation helpers |
| `ribbon.svg` | PEAC green-ribbon asset |

## Privacy

This GitHub repository is currently public. Do **not** commit:

- student names or rosters
- Lunch Buddies requests
- email credentials
- passwords
- `.env` files
- SQLite databases
- exported private PEAC data

Those belong only in the protected application database or approved hosting environment.

## Current source version

Frontend source is aligned to PEAC Community **v7.1**, including:

- centered/stable green ribbon
- Quote of the Day bubble
- public site
- approval-gated sign-up
- private console
- Compliments workflows
- Lunch Buddies
- PEAC Assistant

The tested v7.1 release package remains the reference for the full Python runtime until all backend runtime files are mirrored here.

## Repo

Owner: `gmaxdragon`
Repository: `PEAC-Websites-Fallon`
Default branch: `main`
