"""Where internships are published, and how each kind of page is read.

Four kinds of source:

  posts    a page that lists openings (a jobs portal, a press-release list).
           Each internship link is one item; a link not seen before is new.
  page     a programme's own page (CM IT Internship, Climate Leadership...).
           There is no list: the item is a change to its text -- a new
           cohort, registration opening, a new deadline.
  news     press coverage, which often reports an announcement before the
           official page changes. Labelled as news, never as the source,
           and kept only when the article gives a last date not yet passed.
  jobs     the government jobs on the two portals that are not internships,
           in a list of their own.

Every item keeps the address it was found on, and a new post's own page is
read for its posting date and last date to apply, so what the portal shows
can be checked against the website it came from.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qs, quote, urljoin, urlparse

import feedparser
import requests
import urllib3

import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
NEWS_MAX_AGE_DAYS = 45
# Seconds between two Bing News searches, so a check is not a burst.
NEWS_PAUSE = 1.5
# News stories read per check for their last date (each is one page fetch;
# a story is read once per run of the app).
NEWS_MAX_ARTICLES = 30

SOURCES = [
    # ---- Punjab -----------------------------------------------------------
    {"id": "punjab-jobs", "name": "Punjab Jobs Portal", "level": "Punjab", "kind": "punjab_jobs",
     "home": "https://jobs.punjab.gov.pk/new_recruit/jobs",
     "urls": ["https://jobs.punjab.gov.pk/new_recruit/jobs"]},
    {"id": "pitb", "name": "PITB news and press releases", "level": "Punjab", "kind": "links",
     "home": "https://pitb.gov.pk/press_releases",
     "urls": ["https://pitb.gov.pk/press_releases", "https://pitb.gov.pk/news_and_events",
              "https://pitb.gov.pk/"]},
    {"id": "cm-it", "name": "CM IT Internship Program", "level": "Punjab", "kind": "page",
     "home": "https://punjab.gov.pk/cm-it-internship",
     "urls": ["https://punjab.gov.pk/cm-it-internship"]},
    {"id": "cm-it-portal", "name": "CM IT Internship portal", "level": "Punjab", "kind": "page",
     "home": "https://cmitinterns.punjab.gov.pk/",
     "urls": ["https://cmitinterns.punjab.gov.pk/"]},
    {"id": "climate", "name": "CM Climate Leadership Internship", "level": "Punjab", "kind": "page",
     "home": "https://epd.punjab.gov.pk/Climateinternship",
     "urls": ["https://epd.punjab.gov.pk/Climateinternship"]},
    {"id": "tourism", "name": "CM Tourism Internship Program", "level": "Punjab", "kind": "page",
     "home": "https://mpip.punjab.gov.pk/",
     "urls": ["https://mpip.punjab.gov.pk/"]},
    # ---- Federal ----------------------------------------------------------
    {"id": "njp", "name": "National Jobs Portal", "level": "Federal", "kind": "njp",
     "home": "https://www.njp.gov.pk/jobs/search?q=internship",
     # The keyword searches and the portal's own "Internship" grade (scale 135).
     "urls": ["https://www.njp.gov.pk/jobs/search?q=intern",
              "https://www.njp.gov.pk/jobs/search?q=internship",
              "https://www.njp.gov.pk/jobs/search?q=internee",
              "https://www.njp.gov.pk/jobs/search?scale=135"]},
    {"id": "pkcert", "name": "PKCERT (National CERT) internships", "level": "Federal", "kind": "links",
     "home": "https://pkcert.gov.pk/internships",
     "urls": ["https://pkcert.gov.pk/internships"]},
    {"id": "pkcert-page", "name": "PKCERT internship page", "level": "Federal", "kind": "page",
     "home": "https://pkcert.gov.pk/internships",
     "urls": ["https://pkcert.gov.pk/internships"]},
    {"id": "pseb", "name": "PSEB ICT Internship Program", "level": "Federal", "kind": "page",
     "home": "https://techdestination.com/ict-internship-prorgam/",
     "urls": ["https://techdestination.com/ict-internship-prorgam/"]},
    {"id": "navttc", "name": "NAVTTC news", "level": "Federal", "kind": "links",
     "home": "https://navttc.gov.pk/news/",
     "urls": ["https://navttc.gov.pk/news/", "https://navttc.gov.pk/"]},
    # ---- Press coverage ---------------------------------------------------
    # Only stories whose article states a last date that has not passed are
    # kept. Every feed here links to the article itself: Google News was
    # dropped because its links are encoded redirects, not the article.
    {"id": "news", "name": "News reports", "level": "News", "kind": "news",
     "home": "https://www.bing.com/news/search?q=internship+Punjab+Pakistan",
     "urls": [],
     "queries": ["internship Punjab Pakistan", "internship program Punjab stipend",
                 "internship federal ministry Pakistan", "paid internship Islamabad stipend",
                 "National Jobs Portal internship", "internship registration last date Pakistan"],
     # News sites' own search feeds: (publisher, feed).
     "feeds": [("ProPakistani", "https://propakistani.pk/?s=internship&feed=rss2"),
               ("Pakistan Observer", "https://pakobserver.net/?s=internship&feed=rss2"),
               ("TechJuice", "https://www.techjuice.pk/?s=internship&feed=rss2"),
               ("Daily Times", "https://dailytimes.com.pk/?s=internship&feed=rss2"),
               ("APP", "https://www.app.com.pk/?s=internship&feed=rss2")]},
    # ---- Government jobs (everything on the two portals that is not an internship)
    {"id": "punjab-gov-jobs", "name": "Punjab Jobs Portal: all jobs", "level": "Punjab", "kind": "punjab_jobs",
     "jobs": True, "home": "https://jobs.punjab.gov.pk/new_recruit/jobs",
     "urls": ["https://jobs.punjab.gov.pk/new_recruit/jobs"]},
    {"id": "njp-gov-jobs", "name": "National Jobs Portal: all jobs", "level": "Federal", "kind": "njp",
     "jobs": True, "home": "https://www.njp.gov.pk/jobs/search",
     "urls": ["https://www.njp.gov.pk/jobs/search"]},
]
SOURCE_BY_ID = {s["id"]: s for s in SOURCES}

# "intern", "interns", "internee(s)", "internship(s)", "apprentice(ship)" and the
# federal "Young Development Fellows" scheme -- but not "internal" or
# "international", which a bare "intern" substring matched on every page.
WORD = re.compile(r"\b(intern|interns|internee|internees|internship|internships|"
                  r"apprentice|apprentices|apprenticeship|apprenticeships|"
                  r"development fellows?)\b", re.I)

PUNJAB_MARKERS = re.compile(
    r"\b(punjab|lahore|pitb|maryam nawaz|cm punjab|chief minister|rawalpindi|faisalabad|"
    r"multan|gujranwala|sialkot|bahawalpur|sargodha|rescue 1122|pmiu|tevta|psdf)\b", re.I)
# Bodies that exist only in Pakistan's federal government: enough on their own.
FEDERAL_BODIES = re.compile(
    r"\b(islamabad|navttc|hec|pseb|pkcert|ppra|secp|state bank of pakistan|sbp|fbr|nadra|"
    r"national jobs portal|njp|planning commission|fpsc|pta|tdap|nepra|ogra|wapda|fospah|"
    r"pakistan software export board|moitt|pakistan bureau of statistics|pm youth)\b", re.I)
# Words every country's government uses: they count only with a sign of Pakistan
# ("Ministry of Agriculture announces internships" was a Kenyan story).
FEDERAL_GENERIC = re.compile(
    r"\b(federal|ministry|ministries|prime minister|pm's|senate|national assembly|ombuds\w*)\b", re.I)
PAKISTAN = re.compile(r"\b(pakistan|pakistani|islamabad)\b", re.I)
PAKISTANI_OUTLETS = re.compile(
    r"\b(propakistani|dawn|express tribune|the news|geo|ary|urdupoint|pakistan today|pakistan observer|"
    r"business recorder|daily pakistan|aaj|dunya|samaa|minute mirror|daily times|the nation|"
    r"associated press of pakistan|app|radio pakistan|hum news|92 news|mettis|brecorder)\b", re.I)
OTHER_PROVINCES = re.compile(r"\b(sindh|karachi|khyber|kp|kpk|peshawar|balochistan|quetta|"
                             r"ajk|azad kashmir|gilgit|baltistan)\b", re.I)
# India has a Punjab too: its universities and schemes filled the news list
# until these were excluded and the Pakistan edition of Google News was used.
INDIA_MARKERS = re.compile(
    r"\b(india|indian|chandigarh|ludhiana|amritsar|jalandhar|patiala|mohali|bathinda|haryana|"
    r"delhi|guru angad|gadvasu|pau|lakh|crore|aicte|ugc|iit|nit|mann|bhagwant)\b", re.I)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class Fetched:
    def __init__(self, url, status, text):
        self.url, self.status, self.text = url, status, text


def fetch(url):
    """The page. Several government sites have certificate chains that fail
    verification; those are retried unverified rather than skipped -- this
    only reads public pages, it sends nothing."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=config.TIMEOUT)
    except requests.exceptions.SSLError:
        response = requests.get(url, headers=HEADERS, timeout=config.TIMEOUT, verify=False)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return Fetched(response.url, response.status_code, response.text)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def text_of(fragment):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def strip_code(html):
    return re.sub(r"<(script|style|noscript|svg|template)\b.*?</\1>", " ", html or "", flags=re.S | re.I)


def slug_words(url):
    """'.../cm-it-internship-2nd-cohort' -> 'cm it internship 2nd cohort'."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[-_+.]", " ", re.sub(r"\.(html?|aspx?|php)$", "", tail))


def is_internship(text):
    return bool(WORD.search(text or ""))


def level_of(text, default, publisher=""):
    """Punjab, Federal, or None for another province's (or country's) internship."""
    text = text or ""
    if PUNJAB_MARKERS.search(text):
        return "Punjab"
    if FEDERAL_BODIES.search(text):
        return "Federal"
    if FEDERAL_GENERIC.search(text) and (PAKISTAN.search(text) or PAKISTANI_OUTLETS.search(publisher or "")):
        return "Federal"
    if OTHER_PROVINCES.search(text):
        return None
    return default


# ---------------------------------------------------------------------------
# Readers, one per kind of page
# ---------------------------------------------------------------------------

def read_punjab_jobs(html, base, jobs=False):
    """Every row of the portal's job table whose title or project names an
    internship -- or, with `jobs`, every row that does not."""
    items = []
    for row in re.findall(r"<tr\b.*?</tr>", html, flags=re.S | re.I):
        link = re.search(r'href="([^"]*job_detail/[^"]+)"[^>]*>(.*?)</a>', row, flags=re.S | re.I)
        if not link:
            continue
        cells = [text_of(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.S | re.I)]
        title = text_of(link.group(2))
        department = cells[1] if len(cells) > 1 else ""
        project = cells[2] if len(cells) > 2 else ""
        deadline = next((c for c in cells if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{4}", c)), "")
        if is_internship(" ".join([title, project, slug_words(link.group(1))])) == jobs:
            continue
        items.append({"kind": "job" if jobs else "post", "title": title, "url": urljoin(base, link.group(1)),
                      "detail": " · ".join(x for x in (department, project) if x and x != "-"),
                      "deadline": deadline})
    return items


_NJP_CARD = re.compile(r'<h2\b[^>]*>\s*<a[^>]+href="(https?://(?:www\.)?njp\.gov\.pk/jobs/\d+)"[^>]*>(.*?)</a>',
                       re.S | re.I)
_NJP_EMPLOYER = re.compile(r"^\s*by\s+(.{3,160}?)(?=\s+(?:Contract|Permanent|Regular|Internship|Temporary|"
                           r"Daily\s+Wages|Lump-?sum|Ad-?hoc|Project|BPS-|BS-|MP-)\b|\s*$)", re.I)


def read_njp(html, base, filtered=False, jobs=False):
    """Job cards from a National Jobs Portal search page: title, employer,
    grade, places and the "Available till" date. `filtered`: the page is the
    portal's Internship grade, so every card is an internship. `jobs`: keep
    the cards that are not internships instead."""
    items, seen = [], set()
    cards = list(_NJP_CARD.finditer(html))
    for n, match in enumerate(cards):
        url, title = match.group(1), text_of(match.group(2))
        if not title or url in seen:
            continue
        seen.add(url)
        end = cards[n + 1].start() if n + 1 < len(cards) else match.end() + 3000
        text = text_of(strip_code(html[match.end():end]))
        employer = _NJP_EMPLOYER.search(text)
        name = employer.group(1).strip() if employer else ""
        after = text[employer.end(1):][:300] if employer else text[:300]
        internship = filtered or is_internship(title) or bool(re.match(r"\s*Internship\b", after))
        if internship == jobs:
            continue
        # Every employer here is federal, wherever it sits (Karachi Port Trust is
        # a federal body): the portal's own place is not a province's post.
        grade = re.search(r"\b(BPS-\d+|BS-\d+|MP-[IV]+|SPS-\d+|PPS-\d+|PS-\d+|Lump-?sum)\b", after)
        places = re.search(r"\b(\d+)\s+Vacanc", after)
        # The card gives "Available till Nov 29, 2026", "5 days left" or "Last day to apply!".
        till = re.search(r"Available\s+till\s+(" + _MON + r"\.?\s+\d{1,2},?\s+\d{4})", after, re.I)
        left = re.search(r"\b(\d{1,3})\s+days?\s+left\b", after, re.I)
        deadline = (till.group(1) if till else
                    (today() + timedelta(days=int(left.group(1)))).strftime("%d %b %Y") if left else
                    today().strftime("%d %b %Y") if re.search(r"Last\s+day\s+to\s+apply", after, re.I) else "")
        detail = " · ".join(x for x in (name, grade.group(1) if grade else "",
                                        f"{places.group(1)} place(s)" if places else "") if x)
        items.append({"kind": "job" if jobs else "post", "title": title, "url": url,
                      "detail": detail, "deadline": deadline})
    return items


def read_links(html, base):
    """Links whose text (or address) names an internship."""
    items, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*href="([^"#][^"]*)"[^>]*>(.*?)</a>', strip_code(html),
                                  flags=re.S | re.I):
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base, unescape(href))
        title = text_of(inner) or slug_words(url).strip().capitalize()
        if not is_internship(title + " " + slug_words(url)) or url in seen or len(title) < 6:
            continue
        seen.add(url)
        items.append({"kind": "post", "title": title[:200], "url": url, "detail": "", "deadline": ""})
    return items


def page_lines(html):
    """The page's readable text as a list of lines, for comparing two visits.

    Navigation, scripts and very short fragments are left out: they change
    with every build and say nothing about the programme. Numbers inside a
    line are kept -- a new deadline or stipend is exactly what to report."""
    body = strip_code(html)
    body = re.sub(r"<(nav|header|footer)\b.*?</\1>", " ", body, flags=re.S | re.I)
    body = re.sub(r"</?(p|div|li|h[1-6]|tr|td|th|br|section|article|dd|dt|span)\b[^>]*>", "\n", body, flags=re.I)
    lines, seen = [], set()
    for raw in body.split("\n"):
        line = text_of(raw)
        if len(line.split()) < 4 or len(line) > 600 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def page_changes(old_lines, new_lines):
    """Lines the page gained since the last visit."""
    before = set(old_lines or [])
    return [line for line in new_lines if line not in before]


# ---- news ------------------------------------------------------------------

def bing_news_url(query):
    return "https://www.bing.com/news/search?q=" + quote(query) + "&format=rss&cc=PK&setlang=en"


def _bing_link(link):
    """Bing's feed links go through a click counter; the article is its `url=`."""
    target = parse_qs(urlparse(link or "").query).get("url")
    return target[0] if target else link


def news_key(title):
    """The same story from two feeds is one item."""
    return "news|" + re.sub(r"\W+", " ", (title or "").lower()).strip()


def http_status(exc):
    """The HTTP status a failed fetch got, or None if it got no answer."""
    return getattr(getattr(exc, "response", None), "status_code", None)


def read_feed(url, get=None, publisher=""):
    """Punjab and federal internship stories in one RSS feed: a Bing News
    search, or a news site's own search. Each links to the article itself."""
    get = get or fetch
    feed = feedparser.parse(get(url).text)
    if not feed.entries and not feed.feed.get("title"):
        raise ValueError("no RSS feed at this address")
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    for entry in feed.entries[:40]:
        title = text_of(entry.get("title", ""))
        link = _bing_link(entry.get("link"))
        outlet = entry.get("news_source") or publisher or "News"
        summary = text_of(entry.get("summary", ""))
        if not link or not is_internship(title) or INDIA_MARKERS.search(title + " " + summary):
            continue
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        when = datetime(*parsed[:6], tzinfo=timezone.utc) if parsed else None
        if when and when < cutoff:
            continue
        level = level_of(title + " " + summary, None, outlet)
        if level is None:
            continue           # another province or country, or no sign it is Punjab or federal
        items.append({"kind": "news", "title": title, "url": link, "level": level,
                      "detail": outlet, "deadline": "", "_key": news_key(title),
                      "published": when.isoformat(timespec="seconds") if when else None})
    return items


def article_text(html):
    """The story's own text: its <article> when the page has one, so the
    sidebar's other headlines (and their dates) are left out."""
    body = re.search(r"<article\b.*?</article>", strip_code(html), flags=re.S | re.I)
    return text_of(body.group(0) if body else strip_code(html))


# A story read once is not read again while the app runs: address -> last date (or None).
_ARTICLES = {}


def news_deadline(item, get, pages):
    """The last date the story's article gives, or None. Raises if the
    article cannot be fetched (it is tried again on the next check)."""
    url = item["url"]
    if url not in _ARTICLES:
        try:
            page = get(url)
        except Exception as exc:
            pages.append({"url": url, "status": http_status(exc), "error": f"{type(exc).__name__}"})
            raise
        pages.append({"url": url, "status": page.status})
        published = item.get("published")
        ref = datetime.fromisoformat(published).astimezone(PKT).date() if published else today()
        if len(_ARTICLES) > 3000:
            _ARTICLES.clear()
        _ARTICLES[url] = find_deadline(article_text(page.text), ref)
    return _ARTICLES[url]


# ---------------------------------------------------------------------------
# Dates: last dates in the many ways the sites write them
# ---------------------------------------------------------------------------

PKT = timezone(timedelta(hours=5))
_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# 28-Nov-2026, 30 November 2026, 30th of November · Nov 29, 2026, November 30 · 30-11-2026 (day first)
_ANY_DATE = re.compile(
    r"\b(?:(?P<d1>\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s\-/.,]*(?P<m1>" + _MON + r")\b\.?(?:[\s\-/.,]*(?P<y1>\d{4}|\d{2})\b)?"
    r"|(?P<m2>" + _MON + r")\b\.?\s*(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s*(?P<y2>\d{4})\b)?"
    r"|(?P<d3>\d{1,2})[-/.](?P<m3>\d{1,2})[-/.](?P<y3>\d{4}|\d{2})\b)", re.I)
# Words that put a last date right after them. Strong ones name it; "till" and
# "until" also introduce a programme's own end date, so they count only alone.
_STRONG_CUE = re.compile(r"(last\s+date|deadline|closing\s+date|clos(?:e|es|ing)\s+(?:on|by)|"
                         r"apply\s+(?:by|before|till|until|on\s+or\s+before)|on\s+or\s+before|"
                         # not "by"/"on": "Registrations Closing Soon By Staff Report | Nov 11"
                         # is a byline's date, not a deadline
                         r"(?:registration|registrations|applications?|portal|submission)s?\b[^.|]{0,40}?"
                         r"\b(?:till|until|up\s*to|before)|extended\s+(?:till|until|to|up\s*to))", re.I)
_WEAK_CUE = re.compile(r"\b(?:till|until)\b", re.I)


def today():
    return datetime.now(PKT).date()


def _date_of(match, ref):
    g = match.groupdict()
    day = g["d1"] or g["d2"] or g["d3"]
    month = g["m1"] or g["m2"]
    month = _MONTHS.index(month[:3].lower()) + 1 if month else int(g["m3"])
    year = g["y1"] or g["y2"] or g["y3"]
    ref = ref or today()
    try:
        if year:
            return datetime(int(year) + (2000 if len(year) == 2 else 0), month, int(day)).date()
        found = datetime(ref.year, month, int(day)).date()
        # "closes on 5 January" in a December story is next year's January.
        return found.replace(year=ref.year + 1) if found < ref - timedelta(days=60) else found
    except ValueError:
        return None


def parse_date(text, ref=None):
    """The first date in `text` ("28-Nov-2026", "29 Nov 2026", "Nov 29, 2026",
    "30-11-2026"), or None."""
    match = _ANY_DATE.search(text or "")
    return _date_of(match, ref) if match else None


def find_deadline(text, ref=None):
    """The last date to apply that a story states, or None. Dates right after
    "last date", "deadline", "apply by", "registration ... till" count; of
    those the latest (a deadline that was extended). Without one, the
    earliest date after a bare "till"/"until"."""
    def after(cues):
        out = []
        for cue in cues.finditer(text or ""):
            match = _ANY_DATE.search(text[cue.end():cue.end() + 70])
            found = _date_of(match, ref) if match else None
            if found:
                out.append(found)
        return out
    strong = after(_STRONG_CUE)
    if strong:
        return max(strong)
    weak = after(_WEAK_CUE)
    return min(weak) if weak else None


# ---------------------------------------------------------------------------
# A post's own page: when it was posted and the last date to apply
# ---------------------------------------------------------------------------

_DATE = (r"(\d{1,2}[-/ .](?:\d{1,2}|[A-Za-z]{3,9})[-/ .,]+\d{2,4}"
         r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})")
_DEADLINE = re.compile(r"(?:last\s+date(?:\s+to\s+apply|\s+for\s+submission)?|deadline|closing\s+date|apply\s+by|"
                       r"apply\s+before|submission\s+date)\s*[:\-]?\s*" + _DATE, re.I)
_POSTED = re.compile(r"(?:posted(?:\s+on)?|published(?:\s+on)?|date\s+of\s+advertisement)\s*[:\-]?\s*" + _DATE, re.I)
_VACANCIES = re.compile(r"(?:vacancies|no\.?\s+of\s+posts|number\s+of\s+posts|total\s+(?:seats|posts|vacancies))"
                        r"\s*[:\-]?\s*(\d[\d,]*)", re.I)


def details(html):
    """Posting date, last date and number of places, where the page states them."""
    text = text_of(strip_code(html))
    out = {}
    for key, pattern in (("deadline", _DEADLINE), ("posted", _POSTED), ("vacancies", _VACANCIES)):
        match = pattern.search(text)
        if match:
            out[key] = match.group(1).strip(" ,")
    district = re.search(r"\bDistrict\s+([A-Z][A-Za-z .]{2,40}?)\s+(?:Domicile|Industry|Level|Posted|$)", text)
    if district:
        out["place"] = district.group(1).strip()
    return out


def enrich(item, get=None):
    """Read a post's (or job's) own page for its dates. Never raises; returns the item."""
    get = get or fetch
    if item.get("kind") not in ("post", "job") or not item.get("url") or not urlparse(item["url"]).scheme.startswith("http"):
        return item
    try:
        found = details(get(item["url"]).text)
    except Exception:  # noqa: BLE001 -- the listing is still the post; its page is extra
        return item
    if found.get("deadline") and not item.get("deadline"):
        item["deadline"] = found["deadline"]
    item["posted"] = found.get("posted") or item.get("posted")
    extra = [f"{found['vacancies']} place(s)" if found.get("vacancies") else "", found.get("place", "")]
    extra = " · ".join(x for x in extra if x)
    if extra:
        item["detail"] = " · ".join(x for x in (item.get("detail"), extra) if x)
    return item


# ---------------------------------------------------------------------------
# One check of one source
# ---------------------------------------------------------------------------

def check(source, get=None):
    """Fetch and read one source.

    Returns {"items", "lines", "error", "pages"}: `pages` records every address
    fetched with its HTTP status, so a source's result can be traced to the
    website it came from."""
    get = get or fetch
    kind = source["kind"]
    items, lines, errors, pages = [], None, [], []
    if kind == "news":
        feeds = ([(bing_news_url(q), "") for q in source.get("queries", [])] +
                 [(url, outlet) for outlet, url in source.get("feeds", [])])
        found = []
        for n, (url, outlet) in enumerate(feeds):
            if n and get is fetch and "bing.com" in url:
                time.sleep(NEWS_PAUSE)
            try:
                found.extend(read_feed(url, get, outlet))
                pages.append({"url": url, "status": 200})
            except Exception as exc:  # noqa: BLE001 -- one feed failing is not the source failing
                status = http_status(exc)
                errors.append(f"{urlparse(url).netloc}: " + (f"HTTP {status}" if status else type(exc).__name__))
                pages.append({"url": url, "status": status, "error": errors[-1]})
        if errors and len(errors) == len(feeds):
            return {"items": [], "lines": None, "error": "; ".join(errors), "pages": pages}
        # Keep a story only if its article gives a last date that has not passed.
        for item in _dedupe(found)[:NEWS_MAX_ARTICLES]:
            try:
                closes = news_deadline(item, get, pages)
            except Exception:  # noqa: BLE001 -- recorded in `pages`; read again next check
                continue
            if closes and closes >= today():
                item["deadline"] = closes.strftime("%d %b %Y")
                items.append(item)
        return {"items": items, "lines": None, "error": None, "pages": pages}

    for url in source["urls"]:
        try:
            page = get(url)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
            pages.append({"url": url, "status": status, "error": errors[-1]})
            continue
        pages.append({"url": url, "status": page.status})
        if kind == "punjab_jobs":
            found = read_punjab_jobs(page.text, url, jobs=source.get("jobs", False))
        elif kind == "njp":
            found = read_njp(page.text, url, filtered="scale=135" in url, jobs=source.get("jobs", False))
        elif kind == "links":
            found = read_links(page.text, url)
        else:
            found = []
            lines = (lines or []) + page_lines(page.text)
        for item in found:
            item["found_on"] = url
        items.extend(found)
    error = errors[0] if errors and len(errors) == len(source["urls"]) else None
    return {"items": [] if error else _dedupe(items), "lines": None if error else lines,
            "error": error, "pages": pages}


def _dedupe(items):
    out, seen = [], set()
    for item in items:
        key = item.get("_key") or item.get("url") or item["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
