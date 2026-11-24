# Internship Watch

Punjab and federal government internships in one list, and the government
jobs on the same portals in another. A background worker scrapes the
websites below every 30 minutes, keeps everything it finds, shows what is
still open, and sends a notification when something new is posted.

## Run it

| How | Command | Then open |
|---|---|---|
| Windows, no Docker | `start.bat` | http://127.0.0.1:8700/ |
| Docker | `docker compose up -d --build` | http://127.0.0.1:8700/ |
| Any OS, Python 3.11+ | `pip install -r requirements.txt` then `python serve.py` | http://127.0.0.1:8700/ |

Settings (how often to check, notification channels) are on the page under
**Settings**, or in a `.env` file next to this one (copy `.env.example`).
Data is kept in `data/` (in Docker, the `internship-data` volume).

## Sources

| Government | Source | How it is read |
|---|---|---|
| Punjab | Punjab Jobs Portal (jobs.punjab.gov.pk) | every row of the jobs table naming an internship; each new post's page is read for its posting date and last date to apply |
| Punjab | PITB news and press releases | links naming an internship |
| Punjab | CM IT Internship (punjab.gov.pk, cmitinterns.punjab.gov.pk), CM Climate Leadership Internship (EPD), CM Tourism Internship (mpip) | the programme page's text: a new line (new cohort, registration open, deadline) is reported as an update |
| Federal | National Jobs Portal (njp.gov.pk) | its searches for "intern", "internship", "internee" and its Internship grade; each new post's page is read for its dates and vacancies |
| Federal | PKCERT, NAVTTC | links naming an internship |
| Federal | PSEB ICT Internship Program, PKCERT internship page | page text, as above |
| News | Bing News, and the search feeds of ProPakistani, Pakistan Observer, TechJuice, Daily Times and APP | stories about Punjab or federal internships (India's Punjab, other provinces and other countries are left out). Each story's article is read for its last date to apply; **only stories whose last date has not passed are kept**, linked to the article itself |
| Punjab jobs | Punjab Jobs Portal: all jobs | every row of the jobs table that is *not* an internship, with its last date |
| Federal jobs | National Jobs Portal: all jobs (njp.gov.pk/jobs/search) | every card that is not an internship: employer, grade, places, last date ("Available till", "5 days left") |

The list is `SOURCES` in `sources.py`. The first check of a source records
what is already there without announcing it; only later additions are "new".

Only what is still open is listed: an internship or job whose last date has
passed is kept in the database but hidden (the page says how many), and a
news report counts only with a last date still ahead. Google News is not
used: its links are encoded redirects, not the article, and it rate-limits.
Government jobs are under "Government jobs" on the page, apart from the
internships; a check's notification lists new internships first, then jobs.
Each item shows the page it was scraped from, and each source shows every
address the worker fetched and the HTTP status it got.

## The background worker

`worker.py`. It runs on a thread in the web app (started by `serve.py`), on a
timer: 30 minutes unless changed on the page or by `INTERNSHIP_REFRESH_MINUTES`.
Each run is logged and shown on the page under "Worker log". "Check now" on
the page starts one at once. `python worker.py --once` runs a single check
from the command line.

Run one copy only: two would notify twice.

## Notifications

Every notification goes to the bell on the page. On top of that, any channel
that is set up, on the page (Settings, with a "Send a test" button) or in the
environment:

| Channel | Settings |
|---|---|
| Email | `INTERNSHIPS_SMTP_HOST`, `INTERNSHIPS_SMTP_PORT` (587; 465 for SSL), `INTERNSHIPS_SMTP_USER`, `INTERNSHIPS_SMTP_PASSWORD`, `INTERNSHIPS_EMAIL_FROM`, `INTERNSHIPS_EMAIL_TO` (comma-separated) |
| Telegram | `INTERNSHIPS_TELEGRAM_BOT_TOKEN`, `INTERNSHIPS_TELEGRAM_CHAT_ID` |
| Slack, Discord or any webhook | `INTERNSHIPS_WEBHOOK_URL` |
| ntfy (phone push) | `INTERNSHIPS_NTFY_TOPIC`, optional `INTERNSHIPS_NTFY_SERVER` |

Each delivery and its result (sent, or the error) is recorded and shown under
the notification in the bell.

Desktop pop-ups ("Desktop alerts" on the page) work while the page is open,
and only where the browser allows notifications: https addresses and
localhost. On a plain http server address use the bell or a channel.

## Other settings

| Variable | Default | |
|---|---|---|
| `INTERNSHIPS_DATA_DIR` | `./data` (`/data` in the image) | the SQLite database |
| `INTERNSHIPS_HOST` | 0.0.0.0 | `start.bat` uses 127.0.0.1 (this PC only) |
| `INTERNSHIPS_PORT` | 8700 | |
| `INTERNSHIPS_PUBLIC_URL` | | the app's address, for links in messages |
| `INTERNSHIP_REFRESH_MINUTES` | 30 | how often the worker checks; can be changed on the page |
| `INTERNSHIPS_WORKER` | on | `off` serves the page without the worker |

## Files

| File | |
|---|---|
| `sources.py` | the sources, and how each kind of page is read |
| `worker.py` | the background worker |
| `notify.py` | the notification channels |
| `store.py` | the SQLite database |
| `api.py`, `serve.py` | the web app and its start-up |
| `static/` | the page |

## Tests

    python -m unittest discover -s tests -t .

They need no internet: the worker test runs against a small local website,
adds a post to it, and checks that the post is found, read for its dates,
put in the bell and delivered to a (local) webhook.
