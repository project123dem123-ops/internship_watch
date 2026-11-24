"""Telling people a new internship was posted.

Every notification lands in the app's own inbox (the bell), which works
on any address. On top of that, any of these channels that is set up:

  email     any SMTP server (Gmail with an app password, Outlook, the office server)
  telegram  a Telegram bot: its token and the chat it posts to
  webhook   a Slack or Discord incoming webhook, or any URL that takes JSON
  ntfy      an ntfy topic: phone and desktop push with the free ntfy app

Settings come from the environment (INTERNSHIPS_SMTP_HOST, ...) and can be
changed on the page's Settings panel, which stores them here. Every
delivery and its result is recorded, so "did it send?" has an answer.
"""
import json
import smtplib
from email.message import EmailMessage

import requests

import config
import store

TIMEOUT = 15

# name: (environment variable, secret?)
FIELDS = {
    "email": {"smtp_host": ("INTERNSHIPS_SMTP_HOST", False), "smtp_port": ("INTERNSHIPS_SMTP_PORT", False),
              "smtp_user": ("INTERNSHIPS_SMTP_USER", False), "smtp_password": ("INTERNSHIPS_SMTP_PASSWORD", True),
              "from": ("INTERNSHIPS_EMAIL_FROM", False), "to": ("INTERNSHIPS_EMAIL_TO", False)},
    "telegram": {"bot_token": ("INTERNSHIPS_TELEGRAM_BOT_TOKEN", True), "chat_id": ("INTERNSHIPS_TELEGRAM_CHAT_ID", False)},
    "webhook": {"url": ("INTERNSHIPS_WEBHOOK_URL", True)},
    "ntfy": {"server": ("INTERNSHIPS_NTFY_SERVER", False), "topic": ("INTERNSHIPS_NTFY_TOPIC", True)},
}
REQUIRED = {"email": ("smtp_host", "to"), "telegram": ("bot_token", "chat_id"), "webhook": ("url",), "ntfy": ("topic",)}


def _env(name):
    import os
    return os.environ.get(name, "").strip()


def channel_config(name):
    """A channel's settings: saved on the portal, else from the environment."""
    saved = (store.get_setting("channels", {}) or {}).get(name, {})
    out = {}
    for field, (env, _) in FIELDS[name].items():
        value = saved.get(field)
        out[field] = str(value).strip() if value not in (None, "") else _env(env)
    if name == "ntfy" and not out.get("server"):
        out["server"] = "https://ntfy.sh"
    if name == "email" and not out.get("smtp_port"):
        out["smtp_port"] = "587"
    return out


def configured(name):
    cfg = channel_config(name)
    return all(cfg.get(f) for f in REQUIRED[name])


def active_channels():
    return [name for name in FIELDS if configured(name)]


def public_config():
    """For the settings panel: secrets are never sent back, only whether they are set."""
    out = {}
    for name, fields in FIELDS.items():
        cfg = channel_config(name)
        shown = {}
        for field, (_, secret) in fields.items():
            value = cfg.get(field, "")
            shown[field] = ({"set": bool(value), "preview": ("…" + value[-4:]) if len(value) > 8 else ""}
                            if secret else value)
        out[name] = {"configured": configured(name), "fields": shown}
    return out


def save_config(name, values):
    """Save a channel's settings. An empty secret field keeps the saved one;
    `clear: true` removes the channel's saved settings."""
    if name not in FIELDS:
        raise ValueError("Unknown channel.")
    channels = store.get_setting("channels", {}) or {}
    if values.get("clear"):
        channels.pop(name, None)
    else:
        current = channels.get(name, {})
        for field, (_, secret) in FIELDS[name].items():
            if field not in values:
                continue
            value = str(values[field] or "").strip()
            if secret and not value:
                continue
            current[field] = value
        channels[name] = current
    store.set_setting("channels", channels)
    return public_config()[name]


# ---------------------------------------------------------------------------
# Senders
# ---------------------------------------------------------------------------

def _email(cfg, message):
    mail = EmailMessage()
    mail["Subject"] = message["title"]
    mail["From"] = cfg.get("from") or cfg.get("smtp_user") or "internships@localhost"
    recipients = [a.strip() for a in cfg["to"].replace(";", ",").split(",") if a.strip()]
    mail["To"] = ", ".join(recipients)
    mail.set_content(message["text"])
    port = int(cfg.get("smtp_port") or 587)
    smtp_class = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_class(cfg["smtp_host"], port, timeout=TIMEOUT) as smtp:
        if port != 465:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
        if cfg.get("smtp_user") and cfg.get("smtp_password"):
            smtp.login(cfg["smtp_user"], cfg["smtp_password"])
        smtp.send_message(mail, to_addrs=recipients)
    return f"sent to {', '.join(recipients)}"


def _telegram(cfg, message):
    response = requests.post(f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage", timeout=TIMEOUT,
                             json={"chat_id": cfg["chat_id"], "text": message["text"][:4000],
                                   "disable_web_page_preview": True})
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if not response.ok or not body.get("ok", response.ok):
        raise RuntimeError(f"Telegram answered {response.status_code}: {body.get('description', response.text[:200])}")
    return "posted to the chat"


def _webhook(cfg, message):
    url = cfg["url"]
    if "hooks.slack.com" in url:
        payload = {"text": message["text"]}
    elif "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        payload = {"content": message["text"][:1900]}
    else:
        payload = {"title": message["title"], "text": message["text"], "items": message.get("items", [])}
    response = requests.post(url, json=payload, timeout=TIMEOUT)
    if not response.ok:
        raise RuntimeError(f"the webhook answered {response.status_code}")
    return f"accepted ({response.status_code})"


def _ntfy(cfg, message):
    headers = {"Title": message["title"].encode("utf-8"), "Tags": "briefcase"}
    if message.get("click"):
        headers["Click"] = message["click"]
    response = requests.post(cfg["server"].rstrip("/") + "/" + cfg["topic"], data=message["text"].encode("utf-8"),
                             headers=headers, timeout=TIMEOUT)
    if not response.ok:
        raise RuntimeError(f"ntfy answered {response.status_code}")
    return "published"


SENDERS = {"email": _email, "telegram": _telegram, "webhook": _webhook, "ntfy": _ntfy}


# ---------------------------------------------------------------------------
# Composing and sending
# ---------------------------------------------------------------------------

def _plural(n, word):
    return f"{n} new {word}{'s' if n != 1 else ''}"


def compose(items, is_test=False):
    # Internships first, then government jobs.
    items = sorted(items, key=lambda i: i.get("kind") == "job")
    jobs = sum(1 for i in items if i.get("kind") == "job")
    n = len(items) - jobs
    if n == 1 and not jobs:
        title = f"New internship: {items[0]['title'][:80]}"
    elif jobs and not n:
        title = f"New government job: {items[0]['title'][:80]}" if jobs == 1 else _plural(jobs, "government job") + " posted"
    elif jobs:
        title = f"{_plural(n, 'internship')} and {jobs} government job{'s' if jobs != 1 else ''} posted"
    else:
        title = _plural(n, "internship") + " posted"
    if is_test:
        title = "Test notification from the Internship Watch"
    lines = []
    for item in items[:15]:
        label = f"{item['level']} job" if item.get("kind") == "job" else item["level"]
        line = f"• [{label}] {item['title']} — {item.get('source', '')}"
        if item.get("deadline"):
            line += f" (apply by {item['deadline']})"
        if item.get("url"):
            line += f"\n  {item['url']}"
        lines.append(line)
    if n > 15:
        lines.append(f"…and {n - 15} more.")
    if config.PUBLIC_URL:
        lines.append(f"\nAll internships and jobs: {config.PUBLIC_URL}/")
    return {"title": title, "text": title + "\n\n" + "\n".join(lines),
            "click": f"{config.PUBLIC_URL}/" if config.PUBLIC_URL else (items[0].get("url") or ""),
            "items": [{k: i.get(k) for k in ("title", "url", "level", "source", "deadline", "kind")} for i in items[:15]]}


def dispatch(items, is_test=False, only=None):
    """Record the notification in the inbox and send it on every configured
    channel (or just `only`). Returns {"notification_id", "deliveries"}."""
    message = compose(items, is_test)
    notification_id = store.add_notification(message["title"], message["text"],
                                             [i.get("id") for i in items if i.get("id")], is_test=is_test)
    store.add_delivery(notification_id, "inbox", True, "shown on the page")
    results = [{"channel": "inbox", "ok": True, "detail": "shown on the page"}]
    for name in ([only] if only else active_channels()):
        if not configured(name):
            results.append({"channel": name, "ok": False, "detail": "not set up"})
            continue
        try:
            detail = SENDERS[name](channel_config(name), message)
            ok = True
        except Exception as exc:  # noqa: BLE001 -- one dead channel must not stop the others
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
        store.add_delivery(notification_id, name, ok, detail)
        results.append({"channel": name, "ok": ok, "detail": detail})
    return {"notification_id": notification_id, "deliveries": results}


def send_test(channel=None):
    """A test notification, clearly marked as one, on one channel or all."""
    sample = [{"title": "If you can read this, notifications reach you here.", "level": "Test", "source": "Internship Watch",
               "url": f"{config.PUBLIC_URL}/" if config.PUBLIC_URL else "", "kind": "test"}]
    return dispatch(sample, is_test=True, only=channel)


if __name__ == "__main__":
    print(json.dumps(public_config(), indent=2))
