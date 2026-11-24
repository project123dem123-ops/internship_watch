/* Internship Watch page: lists what the background worker scraped, shows the
   worker's own log, and raises notifications for anything new. */
(function () {
'use strict';

const BASE = '';
const APP_NAME = 'Internship Watch';
const api = path => fetch(BASE + '/api/' + path, { headers: { 'Accept': 'application/json' } }).then(r => {
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
});
const post = (path, body) => fetch(BASE + '/api/' + path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
}).then(r => r.json().catch(() => ({})));

// ---- Light or dark, remembered in this browser.
(function () {
  const btn = document.getElementById('theme-btn');
  let theme = null;
  try { theme = localStorage.getItem('internship-watch-theme'); } catch (e) {}
  if (!theme) theme = (window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  const apply = t => { document.documentElement.dataset.theme = t; btn.innerHTML = t === 'dark' ? '&#9788;' : '&#9790;'; };
  apply(theme);
  btn.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    apply(theme);
    try { localStorage.setItem('internship-watch-theme', theme); } catch (e) {}
  });
})();

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeHref = u => /^(https?:\/\/|\/(?![\/\\]))/i.test(String(u || '')) ? u : '#';
const local = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private window */ } },
};
function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 0) return 'in ' + Math.round(-s / 60) + ' min';
  if (s < 90) return 'just now';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 86400) return Math.round(s / 3600) + ' h ago';
  return Math.round(s / 86400) + ' d ago';
}
function stamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
const KIND = { post: 'Internship posting', update: 'Programme page changed', news: 'News report', job: 'Government job' };
const LEVELS = [['all', 'All', null], ['Punjab', 'Punjab', 'var(--iw-punjab)'], ['Federal', 'Federal', 'var(--iw-federal)']];
// "internships" is every kind but jobs: the jobs are many and kept to their own view.
const KINDS = [['internships', 'All internships'], ['post', 'Internship postings'], ['update', 'Programme updates'],
  ['news', 'News reports'], ['job', 'Government jobs']];
const kindMatch = (i, kind) => kind === 'internships' ? i.kind !== 'job' : i.kind === kind;
const CHANNEL_INFO = {
  email: ['Email', 'Any SMTP server. For Gmail: smtp.gmail.com, port 587, your address, and an app password (Google account → Security → App passwords).',
    [['smtp_host', 'SMTP server', 'smtp.gmail.com'], ['smtp_port', 'Port', '587'], ['smtp_user', 'User name', 'you@gmail.com'],
     ['smtp_password', 'Password or app password', '', true], ['from', 'From (optional)', ''], ['to', 'Send to (comma-separated)', 'you@example.com']]],
  telegram: ['Telegram', 'Make a bot with @BotFather, send it any message, then put its token and your chat id here (find the id at api.telegram.org/bot<token>/getUpdates).',
    [['bot_token', 'Bot token', '123456:ABC…', true], ['chat_id', 'Chat id', '']]],
  webhook: ['Slack, Discord or webhook', 'An incoming-webhook address from Slack or Discord, or any URL that accepts JSON.',
    [['url', 'Webhook URL', 'https://hooks.slack.com/services/…', true]]],
  ntfy: ['ntfy (phone push)', 'Install the free ntfy app, subscribe to a topic name only you know, and enter it here. Uses ntfy.sh unless you give your own server.',
    [['topic', 'Topic', 'my-internships-x7k2', true], ['server', 'Server', 'https://ntfy.sh']]],
};

// "New" is relative to this browser's previous visit; the ids already shown
// are remembered so each internship raises one notification.
const previousVisit = local.get('internships-last-visit', null);
local.set('internships-last-visit', new Date().toISOString());
const knownItems = new Set(local.get('internships-known', []));
let knownNote = local.get('internships-last-note', 0);
let firstLoad = true;
const view = { level: 'all', kind: 'internships', q: '', onlyNew: false };
let items = [], closed = 0, today = null, status = null, inbox = { notifications: [], unread: 0 };

// "Apply by 29 Nov 2026 · 12 days left", from the item's last date (YYYY-MM-DD).
function daysLeft(i) {
  if (!i.closes || !today) return '';
  const days = Math.round((Date.parse(i.closes) - Date.parse(today)) / 86400000);
  return days <= 0 ? 'last day today' : days === 1 ? '1 day left' : days + ' days left';
}

const isNew = i => !i.baseline && previousVisit && Date.parse(i.first_seen) > Date.parse(previousVisit);

// ---- rendering -----------------------------------------------------------
function renderRail() {
  const count = fn => items.filter(fn).length;
  document.getElementById('levelFilters').innerHTML = LEVELS.map(([key, label, colour]) => `
    <button class="rail-btn" data-level="${key}" aria-pressed="${view.level === key}">
      <span class="lbl">${colour ? `<span class="dot" style="background:${colour}"></span>` : ''}${esc(label)}</span>
      <span class="n">${count(i => kindMatch(i, view.kind) && (key === 'all' || i.level === key))}</span></button>`).join('');
  document.getElementById('kindFilters').innerHTML = KINDS.map(([key, label]) => `
    <button class="rail-btn" data-kind="${key}" aria-pressed="${view.kind === key}">
      <span class="lbl">${esc(label)}</span>
      <span class="n">${count(i => kindMatch(i, key))}</span></button>`).join('');
  if (!status) return;
  const open = new Set([...document.querySelectorAll('#sources details[open]')].map(d => d.dataset.id));
  document.getElementById('sources').innerHTML = status.sources.map(s => {
    const ok = s.status === 'ok', err = String(s.status).startsWith('error');
    const pages = (s.pages || []).map(p => `<li><b class="${p.status && p.status < 400 ? '' : 'bad'}">${p.status ? 'HTTP ' + p.status : 'failed'}</b> ${
      /^https?:/.test(p.url) ? `<a href="${esc(safeHref(p.url))}" target="_blank" rel="noopener">${esc(p.url)}</a>` : esc(p.url)}${
      p.error ? `<br>${esc(p.error)}` : ''}</li>`).join('');
    return `<li><details data-id="${esc(s.id)}"${open.has(s.id) ? ' open' : ''}><summary>
      <span class="st ${ok ? 'ok' : err ? 'err' : ''}"></span>
      <span><span class="nm">${esc(s.name)}</span>
      <small>${esc(s.level)} · ${s.last_check ? (err ? 'could not be read ' : `read ${ago(s.last_check)} · ${s.found} ${
        s.jobs ? 'job' : s.kind === 'news' ? 'open stor' + (s.found === 1 ? 'y' : 'ie') : 'internship'}${s.found === 1 ? '' : 's'}`) : 'not checked yet'}</small></span>
      </summary><ul class="pages">${pages || '<li>Not fetched yet.</li>'}</ul></details></li>`;
  }).join('');
}

function renderList() {
  const q = view.q.toLowerCase();
  const shown = items.filter(i =>
    (view.level === 'all' || i.level === view.level) &&
    kindMatch(i, view.kind) &&
    (!view.onlyNew || isNew(i)) &&
    (!q || [i.title, i.detail, i.source].join(' ').toLowerCase().includes(q)));
  const box = document.getElementById('list');
  document.getElementById('closedNote').textContent = closed
    ? `${closed} closed item${closed === 1 ? '' : 's'} hidden: the last date has passed, or a news report gave no last date.` : '';
  if (!shown.length) {
    const checking = status && status.worker.checking;
    const what = view.kind === 'job' ? 'government jobs' : view.kind === 'news' ? 'news reports with a last date still ahead' : 'internships';
    box.innerHTML = `<div class="empty">${items.length && (q || view.onlyNew || view.level !== 'all') ? 'Nothing matches these filters.'
      : checking || !(status && status.worker.last_cycle) ? `The worker is reading the sources; ${what} appear here in a minute or two.`
      : `No open ${what} on these sources right now. New ones will appear here, with a notification.`}</div>`;
    return;
  }
  box.innerHTML = shown.map(i => `
    <article class="item${isNew(i) ? ' fresh' : ''}">
      <div>
        <h3><a href="${esc(safeHref(i.url))}" target="_blank" rel="noopener">${esc(i.title)}</a></h3>
        <div class="meta">
          <span class="chip ${esc(i.level)}">${esc(i.level)}</span>
          <span class="chip kind">${esc(KIND[i.kind] || i.kind)}</span>
          ${isNew(i) ? '<span class="chip new">New</span>' : ''}
          ${i.baseline ? '<span class="chip old" title="Already on the website when the worker first read it">Listed before the watch began</span>' : ''}
          <span>${esc(i.source)}</span>
          ${i.posted ? `<span>Posted ${esc(i.posted)}</span>` : ''}
          ${i.deadline ? `<span class="deadline">Apply by ${esc(i.deadline)}${daysLeft(i) ? ' · ' + esc(daysLeft(i)) : ''}</span>` : ''}
        </div>
      </div>
      <div class="when" title="${esc(i.first_seen)}">found ${esc(ago(i.first_seen))}${i.published ? `<br>published ${esc(ago(i.published))}` : ''}</div>
      ${i.detail ? `<div class="detail">${esc(i.detail)}</div>` : ''}
      <div class="proof">${i.kind === 'news' ? 'Reported by ' + esc(i.detail || 'a news outlet') + '; the last date is read from the article' :
        `Scraped from <a href="${esc(safeHref(i.found_on || i.url))}" target="_blank" rel="noopener">${esc(i.found_on || i.url)}</a>`}
        · last seen there ${esc(ago(i.last_seen))}</div>
    </article>`).join('');
}

function renderStatus() {
  if (!status) return;
  const w = status.worker;
  const fresh = items.filter(isNew).length;
  const state = !w.enabled ? '<span class="pulse off"></span><b>Worker off</b>'
    : !w.alive ? '<span class="pulse off"></span><b>Worker stopped</b>'
    : w.checking ? '<span class="pulse busy"></span><b>Checking the websites now…</b>'
    : '<span class="pulse"></span><b>Worker running</b>';
  document.getElementById('worker').innerHTML = [state,
    `every ${w.interval_minutes} min`,
    w.last_cycle ? `last check ${esc(ago(w.last_cycle))}` : 'first check pending',
    w.next_cycle && !w.checking ? `next ${esc(ago(w.next_cycle))}` : '',
    `${items.length} found`,
    previousVisit ? `<b>${fresh} new</b> since your last visit` : ''].filter(Boolean).join(' · ');
  const btn = document.getElementById('checkNow');
  btn.disabled = !!w.checking;
  btn.textContent = w.checking ? 'Checking…' : 'Check now';
  const channels = status.channels || [];
  const desktop = 'Notification' in window && window.isSecureContext;
  document.getElementById('channelNote').textContent = (channels.length
    ? `New internships are also sent by ${channels.join(', ')}, even when this page is closed.`
    : 'New internships go to the bell (top right)' + (desktop ? ' and to desktop alerts while this page is open' : '') +
      '. To be told when the page is closed, set up email, Telegram, a webhook or ntfy under "Notification channels".') +
    (desktop ? '' : ' Desktop pop-ups need the portal on https (or this PC); on this address use the bell or a channel.');
  document.getElementById('runs').innerHTML = (status.runs || []).map(r => {
    const took = r.finished ? Math.max(1, Math.round((Date.parse(r.finished) - Date.parse(r.started)) / 1000)) + ' s' : 'running';
    return `<tr><td>${esc(stamp(r.started))}</td><td>${r.trigger === 'manual' ? 'Check now' : 'Scheduled'}</td>
      <td>${r.sources_ok}</td><td>${r.sources_failed}</td><td>${r.found}</td><td>${r.new_items}</td><td>${took}</td></tr>`;
  }).join('') || '<tr><td colspan="7">No checks yet.</td></tr>';
  document.title = (inbox.unread ? `(${inbox.unread}) ` : '') + APP_NAME;
}

function renderInbox() {
  const badge = document.getElementById('bellCount');
  badge.hidden = !inbox.unread;
  badge.textContent = inbox.unread > 99 ? '99+' : inbox.unread;
  document.getElementById('inboxList').innerHTML = inbox.notifications.length ? inbox.notifications.map(n => `
    <div class="note-row${n.read ? '' : ' unread'}">
      <b>${esc(n.title)}</b>${n.is_test ? ' <span class="chip Test">test</span>' : ''}
      <div style="color:var(--iw-muted); font-size:11.5px">${esc(stamp(n.created))}</div>
      <pre>${esc(n.body)}</pre>
      <div class="deliv">${(n.deliveries || []).map(d => `<span class="${d.ok ? 'ok' : 'bad'}" title="${esc(d.detail)}">${esc(d.channel)} ${d.ok ? '✓' : '✗'}</span>`).join('')}</div>
    </div>`).join('') : '<div class="empty">No notifications yet. When the worker finds a new internship it appears here.</div>';
}

// ---- notifications in the browser ---------------------------------------
function announce(note) {
  const toast = document.getElementById('toast');
  toast.innerHTML = `<b>${esc(note.title)}</b><br>${esc(note.body.split('\n').slice(2, 5).join(' '))}`;
  toast.hidden = false;
  clearTimeout(announce.timer);
  announce.timer = setTimeout(() => { toast.hidden = true; }, 12000);
  if (local.get('internships-alerts', false) && 'Notification' in window && Notification.permission === 'granted') {
    const n = new Notification(note.title, { body: note.body.split('\n').slice(2, 6).join('\n'), tag: 'internship-' + note.id });
    n.onclick = () => { window.focus(); openDrawer('inbox'); };
  }
}

// ---- loading ---------------------------------------------------------------
async function load() {
  try {
    const [a, b, c] = await Promise.all([api('items'), api('status'), api('notifications')]);
    items = a.items; closed = a.closed || 0; today = a.today || null; status = b; inbox = c;
  } catch (e) {
    document.getElementById('worker').textContent = 'Could not reach the Internship Watch (' + e.message + ').';
    schedule(30000);
    return;
  }
  items.forEach(i => knownItems.add(i.id));
  local.set('internships-known', [...knownItems].slice(-3000));
  // A notification the worker recorded since this browser last looked.
  const newest = inbox.notifications[0];
  if (newest && newest.id > knownNote) {
    if (!firstLoad) inbox.notifications.filter(n => n.id > knownNote).reverse().forEach(announce);
    knownNote = newest.id;
    local.set('internships-last-note', knownNote);
  }
  firstLoad = false;
  renderRail(); renderStatus(); renderList(); renderInbox();
  schedule(status.worker.checking ? 4000 : 30000);
}
function schedule(ms) { clearTimeout(load.timer); load.timer = setTimeout(load, ms); }

// ---- controls --------------------------------------------------------------
document.querySelector('aside').addEventListener('click', e => {
  const b = e.target.closest('[data-level],[data-kind]');
  if (!b) return;
  if (b.dataset.level) view.level = b.dataset.level;
  if (b.dataset.kind) view.kind = b.dataset.kind;
  renderRail(); renderList();
});
document.getElementById('find').addEventListener('input', e => { view.q = e.target.value.trim(); renderList(); });
document.getElementById('onlyNew').addEventListener('change', e => { view.onlyNew = e.target.checked; renderList(); });
document.getElementById('checkNow').addEventListener('click', async () => {
  await post('check');
  if (status) { status.worker.checking = true; renderStatus(); }
  schedule(2500);
});

function openDrawer(id) {
  document.querySelectorAll('.drawer').forEach(d => { d.hidden = d.id !== id; });
  if (id === 'channels') { loadSchedule(); loadChannels(); }
}
document.getElementById('bell').addEventListener('click', () => openDrawer('inbox'));
document.getElementById('openChannels').addEventListener('click', () => openDrawer('channels'));
document.getElementById('openSettings').addEventListener('click', () => openDrawer('channels'));

// ---- how often the worker checks ------------------------------------------
async function loadSchedule() {
  try { document.getElementById('refreshMinutes').value = (await api('settings')).refresh_minutes; } catch (e) { /* shown on save */ }
}
document.getElementById('scheduleForm').addEventListener('submit', async e => {
  e.preventDefault();
  const msg = e.target.querySelector('.msg');
  const minutes = Number(document.getElementById('refreshMinutes').value);
  const res = await fetch(BASE + '/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_minutes: minutes }) });
  const body = await res.json().catch(() => ({}));
  msg.className = 'msg ' + (res.ok ? 'ok' : 'err');
  msg.textContent = res.ok ? `Saved: the worker now checks every ${body.refresh_minutes} minutes.` : (body.detail || 'Could not save.');
  load();
});
document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => { b.closest('.drawer').hidden = true; }));
document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('.drawer').forEach(d => { d.hidden = true; }); });
document.getElementById('markRead').addEventListener('click', async () => {
  await post('notifications/read');
  inbox.notifications.forEach(n => { n.read = true; });
  inbox.unread = 0;
  renderInbox(); renderStatus();
});

const alertsBtn = document.getElementById('alertsBtn');
function paintAlerts() {
  if (!('Notification' in window) || !window.isSecureContext) {
    alertsBtn.textContent = 'Desktop alerts: need https';
    alertsBtn.disabled = true;
    alertsBtn.title = 'Browsers only show desktop notifications for https pages (or this PC). Use the bell or a notification channel.';
    return;
  }
  const on = local.get('internships-alerts', false) && Notification.permission === 'granted';
  alertsBtn.setAttribute('aria-pressed', String(on));
  alertsBtn.textContent = 'Desktop alerts: ' + (on ? 'on' : Notification.permission === 'denied' ? 'blocked in the browser' : 'off');
}
alertsBtn.addEventListener('click', async () => {
  if (local.get('internships-alerts', false) && Notification.permission === 'granted') {
    local.set('internships-alerts', false);
  } else {
    const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
    local.set('internships-alerts', permission === 'granted');
    if (permission === 'granted') new Notification('Desktop alerts are on', { body: 'New internships will appear like this while the portal is open.' });
  }
  paintAlerts();
});

// ---- notification channels -------------------------------------------------
async function loadChannels() {
  const box = document.getElementById('channelList');
  box.innerHTML = '<div class="note">Loading…</div>';
  let config;
  try { config = await api('channels'); } catch (e) { box.innerHTML = `<div class="note">Could not load: ${esc(e.message)}</div>`; return; }
  box.innerHTML = `<p class="note" style="margin:0">Every notification also goes to the bell. Settings saved here are kept by the
    Internship Watch; passwords and tokens are never shown again, only whether they are set.</p>` +
    Object.entries(CHANNEL_INFO).map(([name, [label, help, fields]]) => {
      const c = config[name] || { configured: false, fields: {} };
      return `<form class="chan" data-channel="${name}">
        <h3>${esc(label)} ${c.configured ? '<span class="on">● on</span>' : '<span class="offl">not set up</span>'}</h3>
        <p>${esc(help)}</p>
        ${fields.map(([key, title, placeholder, secret]) => {
          const value = c.fields[key];
          const hint = secret ? (value && value.set ? `saved ${esc(value.preview || '')} (leave empty to keep)` : 'not set') : '';
          return `<label for="${name}-${key}">${esc(title)}${hint ? ` · <span style="text-transform:none; font-weight:400">${hint}</span>` : ''}</label>
            <input id="${name}-${key}" name="${key}" ${secret ? 'type="password" autocomplete="new-password"' : 'type="text"'}
              placeholder="${esc(placeholder)}" value="${secret ? '' : esc(value || '')}">`;
        }).join('')}
        <div class="row"><button class="btn small" type="submit">Save</button>
          <button class="btn ghost small" type="button" data-test>Send a test</button>
          ${c.configured ? '<button class="btn ghost small" type="button" data-clear>Remove</button>' : ''}
          <span class="msg" aria-live="polite"></span></div>
      </form>`;
    }).join('');
}
document.getElementById('channelList').addEventListener('submit', async e => {
  e.preventDefault();
  const form = e.target, msg = form.querySelector('.msg');
  const body = Object.fromEntries(new FormData(form).entries());
  msg.className = 'msg'; msg.textContent = 'Saving…';
  const saved = await post('channels/' + form.dataset.channel, body);
  msg.className = 'msg ' + (saved.configured ? 'ok' : 'err');
  msg.textContent = saved.configured ? 'Saved. Send a test to check it.' : 'Saved, but some required fields are still empty.';
  setTimeout(loadChannels, 1500);
  load();
});
document.getElementById('channelList').addEventListener('click', async e => {
  const form = e.target.closest('form');
  if (!form) return;
  const msg = form.querySelector('.msg');
  if (e.target.matches('[data-test]')) {
    msg.className = 'msg'; msg.textContent = 'Sending…';
    const result = await post('channels/' + form.dataset.channel + '/test');
    const d = (result.deliveries || []).find(x => x.channel === form.dataset.channel) || {};
    msg.className = 'msg ' + (d.ok ? 'ok' : 'err');
    msg.textContent = d.ok ? 'Sent: ' + d.detail : 'Not sent: ' + (d.detail || 'unknown error');
    load();
  }
  if (e.target.matches('[data-clear]')) {
    await post('channels/' + form.dataset.channel, { clear: true });
    loadChannels(); load();
  }
});

paintAlerts();
load();
})();
