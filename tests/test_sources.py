"""Reading each kind of page. Fixtures copy the real sites' markup (16 Nov 2026)."""
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from unittest import mock

import requests

from tests import helpers  # noqa: F401  (puts the app on the path)
import sources as src

PUNJAB_TABLE = """<table><tbody>
<tr><td data-label="Job Title"><strong><a href="https://jobs.punjab.gov.pk/new_recruit/job_detail/driver-95">Driver</a></strong></td>
<td data-label="Department">Punjab energy efficiency and conservation agency (PEECA)</td><td>PEECA</td><td>PUNJAB</td><td>30-Nov-2026</td></tr>
<tr><td data-label="Job Title"><strong><a href="https://jobs.punjab.gov.pk/new_recruit/job_detail/shrimp-internship-program-2">Internee (Aquaculture)</a></strong></td>
<td data-label="Department">Fisheries Department</td><td>Punjab Shrimp Internship Program</td><td>PUNJAB</td><td>05-Dec-2026</td></tr>
<tr><td><a href="https://jobs.punjab.gov.pk/new_recruit/job_detail/internal-auditor-23">Internal Auditor</a></td><td>Audit</td><td>-</td><td>PUNJAB</td><td>01-Dec-2026</td></tr>
</tbody></table>"""

NJP_PAGE = """
<h2><a href="https://www.njp.gov.pk/jobs/10701">Internship Program 2026</a></h2>
<p>by National Vocational and Technical Training Commission (NAVTTC)</p><span>Internship</span>
<h2><a href="https://www.njp.gov.pk/jobs/10655">Senior Associate / Legal Adviser</a></h2><p>by Prime Minister Office</p>
<h2><a href="https://www.njp.gov.pk/jobs/10656">International Relations Officer</a></h2><p>by Ministry of Foreign Affairs</p>
"""

# The full listing's cards, as njp.gov.pk/jobs/search words them (17 Nov 2026).
NJP_JOBS = """
<h2 class="text-xl"><a href="https://www.njp.gov.pk/jobs/10655">Senior Associate (MP-II)</a></h2>
<p>by Prime Minister Office (Public) Islamabad</p><span>Contract</span><span>MP-II</span><span>1 Vacancy</span>
<span>Experience: 5 Years+</span><span>Available till Nov 29, 2026</span><a href="https://www.njp.gov.pk/jobs/10655">View Details</a>
<h2><a href="https://www.njp.gov.pk/jobs/10701">Internship Program 2026</a></h2>
<p>by National Vocational and Technical Training Commission (NAVTTC)</p><span>Internship</span>
<h2><a href="https://www.njp.gov.pk/jobs/10690">Assistant Private Secretary</a></h2>
<p>by National Telecommunication Corporation (NTC)</p><span>Regular</span><span>BPS-16</span><span>Last day to apply!</span>
<h2><a href="https://www.njp.gov.pk/jobs/10691">Cook KPT PS-3</a></h2>
<p>by Karachi Port Trust</p><span>Regular</span><span>PS-3</span><span>1 Vacancy</span><span>5 days left</span>
"""

# The text of real detail pages, as the sites word them.
PUNJAB_DETAIL = ("<div>Job Details Division Lahore District LAHORE Domicile Only LAHORE Industry Government "
                 "Posted 16-11-2026 Level Not Applicable Last Date to Apply 30-11-2026 Preferred Candidates</div>")
NJP_DETAIL = ("<div>Deadline 29 Nov 2026 13 days left Quick Overview Posted: 15 Nov 2026 Deadline: 29 Nov 2026 "
              "Vacancies: 15 Experience: none</div>")


def _jobz_row(slug, title, employer, city, posted, positions):
    return f"""<div class="row_container">
  <div class="cell1"><a href="https://www.jobz.pk/{slug}"  target="_blank">{title}</a></div>
  <div class="cell2"><a href="https://www.jobz.pk/x-vacancies/" title="{employer} jobs">{employer}</a></div>
  <div class="cell_three">
    <div class="inner_cell"><a href="https://www.jobz.pk/jobs_in_x/" title="jobs in {city}">{city}</a></div>
    <div class="inner_cell">{posted}<br><a href="https://www.jobz.pk/x-employment/">Management</a></div>
  </div>
  <div class="cell1" style="width:100%"><br>Vacant Positions: <a href="https://www.jobz.pk/x-jobs/">{positions}</a></div>
</div>"""


# jobz.pk's government internships list, as it words its rows (26 Nov 2026).
JOBZ_LIST = ('<div class="row_container"><div class="cell1">Vacancy</div><div class="inner_cell">Job City</div></div>' +
             "".join(_jobz_row(*row) for row in [
                 ("cbd-punjab-internship-2026_jobs-780001.html", "Central Business District CBD Punjab Internship 2026",
                  "Punjab Central Business District Development Authority", "Lahore", "25-Sep-2026", "Internee"),
                 ("balochistan-safe-cities-authority-bsca-internship-2026_jobs-779000.html",
                  "Balochistan Safe Cities Authority BSCA Internship 2026", "Balochistan Safe Cities Authority PSCA",
                  "Quetta", "13-Oct-2026", "Internship"),
                 ("special-education-department-sed-punjab-jobs-2026_jobs-779500.html",
                  "Special Education Department SED Punjab Jobs 2026", "Special Education Department", "Jhang",
                  "13-Oct-2026", "Junior Special Education Teacher"),
                 ("sngpl-apprenticeship-training-course-2026_jobs-785582.html", "SNGPL Apprenticeship Training Course 2026",
                  "Sui Northern Gas Pipelines Limited SNGPL", "Gujranwala", "30-Oct-2026", "Electrician"),
                 ("ministry-of-law-justice-islamabad-internship-2026_jobs-770100.html",
                  "Ministry of Law &amp; Justice Islamabad Internship 2026", "Ministry of Law &amp; Justice", "Islamabad",
                  "31-Jul-2026", "Internship"),
                 ("sbp-internship-program-2026_jobs-781000.html", "State Bank of Pakistan Internship Program 2026",
                  "State Bank of Pakistan", "Karachi", "02-Oct-2026", "Internee"),
             ]))
# An ad's own page.
JOBZ_AD = ("<div>Job Type: Intern Expected Last Date: {} or as per paper ad Published on: 03-NOV-2014 "
           "Date Posted / Updated: 25 September, 2026 Newspaper: Jang Jobs</div>")


class Fake:
    def __init__(self, pages):
        self.pages = pages

    def __call__(self, url):
        if url not in self.pages:
            raise ConnectionError("refused")
        return src.Fetched(url, 200, self.pages[url])


class Refusing(Fake):
    """A Fake that answers some addresses with an HTTP error (a site that blocks readers: 403)."""
    def __init__(self, pages, refuse):
        super().__init__(pages)
        self.refuse, self.asked = refuse, []

    def __call__(self, url):
        self.asked.append(url)
        if url in self.refuse:
            response = requests.Response()
            response.status_code = self.refuse[url]
            raise requests.HTTPError(f"{response.status_code}", response=response)
        return super().__call__(url)


class ReadingTest(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(src, "today", return_value=helpers.TODAY)
        patch.start()
        self.addCleanup(patch.stop)

    def test_internship_words_but_not_internal_or_international(self):
        for text in ("Internship Program 2026", "Internee (Aquaculture)", "10 interns wanted",
                     "Young Development Fellows", "Apprenticeship scheme"):
            self.assertTrue(src.is_internship(text), text)
        for text in ("Internal Auditor", "International Relations Officer", "Internet services"):
            self.assertFalse(src.is_internship(text), text)

    def test_punjab_portal_rows(self):
        items = src.read_punjab_jobs(PUNJAB_TABLE, "https://jobs.punjab.gov.pk/new_recruit/jobs")
        self.assertEqual([i["title"] for i in items], ["Internee (Aquaculture)"])
        self.assertEqual(items[0]["deadline"], "05-Dec-2026")
        self.assertIn("Fisheries Department", items[0]["detail"])

    def test_national_jobs_portal_cards(self):
        items = src.read_njp(NJP_PAGE, "")
        self.assertEqual([i["url"] for i in items], ["https://www.njp.gov.pk/jobs/10701"])
        self.assertIn("NAVTTC", items[0]["detail"])
        self.assertEqual(len(src.read_njp(NJP_PAGE, "", filtered=True)), 3)   # the Internship grade

    def test_links_by_text_or_address(self):
        html = ('<a href="/internship-2026.asp">Internship Program 2026</a>'
                '<a href="/node/11101">Candidate Registration Now Open for CM IT Internship Program</a>'
                '<a href="/international">International Events</a>'
                '<a href="mailto:internships@pkcert.gov.pk">internships@pkcert.gov.pk</a>')
        items = src.read_links(html, "https://pkcert.gov.pk/internships")
        self.assertEqual([i["url"] for i in items], ["https://pkcert.gov.pk/internship-2026.asp",
                                                     "https://pkcert.gov.pk/node/11101"])

    def test_a_page_reports_only_the_lines_it_gained(self):
        before = src.page_lines("<p>Total Vacancies: 2,000 for the first cohort</p><nav><a>Home About Contact Us Now</a></nav>")
        after = src.page_lines("<p>Total Vacancies: 2,000 for the first cohort</p>"
                               "<p>Registration for the 3rd cohort opens on 1 December</p>")
        self.assertEqual(src.page_changes(before, after), ["Registration for the 3rd cohort opens on 1 December"])

    def test_news_is_kept_to_punjab_and_federal_pakistan(self):
        self.assertEqual(src.level_of("NAVTTC Announces Internships", None), "Federal")
        self.assertEqual(src.level_of("Punjab CM IT Internship Programme", None), "Punjab")
        self.assertEqual(src.level_of("Ministry announces internships", None, "ProPakistani"), "Federal")
        self.assertIsNone(src.level_of("Ministry of Agriculture announces internships", None, "Tuko News"))
        self.assertIsNone(src.level_of("Sindh announces internships in Karachi", None))
        self.assertTrue(src.INDIA_MARKERS.search("Veterinary students at Guru Angad Dev University"))

    def test_news_is_kept_only_with_a_last_date_still_ahead_and_links_to_the_article(self):
        src._ARTICLES.clear()
        when = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

        def rss(*stories):
            return "<rss><channel><title>Feed</title>" + "".join(
                f"<item><title>{t}</title><link>{link}</link><pubDate>{when}</pubDate></item>" for t, link in stories
            ) + "</channel></rss>"
        bing = rss(("Punjab CM IT Internship Programme opens registration",
                    "http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fpropakistani.pk%2fcmit&amp;c=1"),
                   ("NAVTTC internship batch completes training", "https://propakistani.pk/navttc-done"))
        site = rss(("Punjab CM IT Internship Programme opens registration", "https://propakistani.pk/cmit"),
                   ("PITB internship registration closed last month", "https://propakistani.pk/pitb-old"))
        source = dict(src.SOURCE_BY_ID["news"], queries=["internship Punjab"],
                      feeds=[("ProPakistani", "https://propakistani.pk/feed"), ("Gone", "https://gone.pk/feed")])
        get = Refusing({
            src.bing_news_url("internship Punjab"): bing, "https://propakistani.pk/feed": site,
            "https://propakistani.pk/cmit": "<nav>Deadline 1 Nov 2026</nav><article>By Staff Report | Nov 11, 2026 "
                                            "Registration will remain open till November 30, 2026.</article>",
            "https://propakistani.pk/navttc-done": "<article>96 interns completed the training.</article>",
            "https://propakistani.pk/pitb-old": "<article>The last date to apply was 10-11-2026.</article>",
        }, refuse={"https://gone.pk/feed": 403})
        result = src.check(source, get)
        self.assertIsNone(result["error"])                      # one feed down is not the source down
        self.assertEqual([(i["url"], i["deadline"]) for i in result["items"]],
                         [("https://propakistani.pk/cmit", "30 Nov 2026")])   # the article, not Bing's counter
        statuses = {p["url"]: p["status"] for p in result["pages"]}
        self.assertEqual(statuses["https://gone.pk/feed"], 403)
        self.assertEqual(statuses["https://propakistani.pk/cmit"], 200)      # each article read is listed

        src.check(source, get)                                  # an article is read once per run
        self.assertEqual(get.asked.count("https://propakistani.pk/cmit"), 1)

    def test_last_dates_as_stories_write_them(self):
        ref = date(2026, 11, 17)
        for text, want in [("The last date to apply is November 30, 2026.", date(2026, 11, 30)),
                           ("Last Date: 05-12-2026", date(2026, 12, 5)),
                           ("Candidates can apply till 25th November.", date(2026, 11, 25)),
                           ("Registration will remain open until December 3, 2026; the internship runs until "
                            "30 June 2027.", date(2026, 12, 3)),
                           ("The deadline, earlier 20 November, has been extended to 30 November 2026.", date(2026, 11, 30)),
                           ("Applications are accepted on or before 10 Jan.", date(2027, 1, 10)),
                           ("Registrations Closing Soon By Staff Report | Nov 11, 2026", None),
                           ("Published on: October 14, 2026", None)]:
            self.assertEqual(src.find_deadline(text, ref), want, text)
        for text in ("28-Nov-2026", "28 Nov 2026", "Nov 28, 2026", "28-11-2026"):
            self.assertEqual(src.parse_date(text), date(2026, 11, 28), text)

    def test_government_jobs_are_the_rows_that_are_not_internships(self):
        items = src.read_punjab_jobs(PUNJAB_TABLE, "https://jobs.punjab.gov.pk/new_recruit/jobs", jobs=True)
        self.assertEqual([(i["title"], i["kind"], i["deadline"]) for i in items],
                         [("Driver", "job", "30-Nov-2026"), ("Internal Auditor", "job", "01-Dec-2026")])
        jobs = src.read_njp(NJP_JOBS, "", jobs=True)
        self.assertEqual([(i["title"], i["deadline"]) for i in jobs],
                         [("Senior Associate (MP-II)", "Nov 29, 2026"),
                          ("Assistant Private Secretary", "17 Nov 2026"),       # "Last day to apply!"
                          ("Cook KPT PS-3", "22 Nov 2026")])                   # "5 days left"; federal, in Karachi
        self.assertEqual(jobs[0]["detail"], "Prime Minister Office (Public) Islamabad · MP-II · 1 place(s)")
        self.assertEqual([i["title"] for i in src.read_njp(NJP_JOBS, "")], ["Internship Program 2026"])

    def test_a_posts_own_page_gives_its_dates(self):
        self.assertEqual(src.details(PUNJAB_DETAIL), {"deadline": "30-11-2026", "posted": "16-11-2026", "place": "LAHORE"})
        self.assertEqual(src.details(NJP_DETAIL)["deadline"], "29 Nov 2026")
        self.assertEqual(src.details(NJP_DETAIL)["posted"], "15 Nov 2026")
        item = src.enrich({"kind": "post", "url": "https://www.njp.gov.pk/jobs/1", "title": "Internship", "detail": "NAVTTC"},
                          Fake({"https://www.njp.gov.pk/jobs/1": NJP_DETAIL}))
        self.assertEqual((item["deadline"], item["posted"]), ("29 Nov 2026", "15 Nov 2026"))
        self.assertIn("15 place(s)", item["detail"])

    def test_a_sources_own_words_count_as_internships(self):
        html = ('<a href="/careers/sbots-29th-batch">State Banks Officers Training Scheme (SBOTS)</a>'
                '<a href="/careers/it-operations-on-contract">Information Technology Operations Department</a>')
        self.assertEqual(src.read_links(html, "https://www.sbp.org.pk/careers/"), [])
        items = src.read_links(html, "https://www.sbp.org.pk/careers/", src.SOURCE_BY_ID["sbp"]["words"])
        self.assertEqual([i["url"] for i in items], ["https://www.sbp.org.pk/careers/sbots-29th-batch"])

    def test_newspaper_ads_are_kept_to_punjab_and_federal_internships(self):
        items = src.read_jobz(JOBZ_LIST, "https://www.jobz.pk/government-internships/")
        self.assertEqual([(i["title"], i["level"]) for i in items], [
            ("Central Business District CBD Punjab Internship 2026", "Punjab"),
            ("SNGPL Apprenticeship Training Course 2026", "Punjab"),          # by its city alone
            ("Ministry of Law & Justice Islamabad Internship 2026", "Federal"),
            ("State Bank of Pakistan Internship Program 2026", "Federal"),   # a federal body in Karachi
        ])
        self.assertEqual(items[0]["posted"], "25-Sep-2026")
        self.assertEqual(items[0]["detail"], "Punjab Central Business District Development Authority · Lahore")
        self.assertTrue(all(i["_read"] for i in items))

    def test_newspaper_ads_are_kept_only_while_their_last_date_is_ahead(self):
        ads_read = mock.patch.dict(src._AD_PAGES, clear=True)
        ads_read.start()
        self.addCleanup(ads_read.stop)
        base = "https://www.jobz.pk/"
        fake = Refusing({base + "government-internships/": JOBZ_LIST,
                         base + "cbd-punjab-internship-2026_jobs-780001.html": JOBZ_AD.format("10 December, 2026"),
                         base + "sngpl-apprenticeship-training-course-2026_jobs-785582.html": JOBZ_AD.format("13 November, 2026"),
                         base + "ministry-of-law-justice-islamabad-internship-2026_jobs-770100.html": "<p>No date given</p>"},
                        {base + "sbp-internship-program-2026_jobs-781000.html": 503})
        result = src.check(src.SOURCE_BY_ID["jobz"], fake)
        self.assertIsNone(result["error"])
        self.assertEqual([(i["title"], i["deadline"]) for i in result["items"]],
                         [("Central Business District CBD Punjab Internship 2026", "10 Dec 2026")])
        self.assertEqual([p.get("status") for p in result["pages"]], [200, 200, 200, 200, 503])
        # A second check reads only the ad that could not be read, and the list.
        fake.asked.clear()
        src.check(src.SOURCE_BY_ID["jobz"], fake)
        self.assertEqual(fake.asked, [base + "government-internships/",
                                      base + "sbp-internship-program-2026_jobs-781000.html"])
        # Its page was read for its last date already: storing it reads nothing more.
        fake.asked.clear()
        src.enrich(result["items"][0], fake)
        self.assertEqual(fake.asked, [])

    def test_a_page_two_sources_read_is_fetched_once_per_check(self):
        calls = []
        lock = threading.Lock()

        def slow(url):          # slow enough that the other three ask while it is fetching
            with lock:
                calls.append(url)
            time.sleep(0.1)
            if url.endswith("down"):
                raise ConnectionError("refused")
            return src.Fetched(url, 200, "<p>page</p>")

        cache = src.CycleCache(slow)
        with ThreadPoolExecutor(max_workers=4) as pool:
            pages = list(pool.map(cache, ["https://a.gov.pk/"] * 4))
        self.assertEqual(calls, ["https://a.gov.pk/"])
        self.assertTrue(all(p is pages[0] for p in pages))
        for _ in range(2):
            with self.assertRaises(ConnectionError):
                cache("https://a.gov.pk/down")
        self.assertEqual(calls, ["https://a.gov.pk/", "https://a.gov.pk/down"])
        self.assertFalse(cache.live)                       # a fake: no pauses between requests
        self.assertTrue(src.CycleCache().live)

    def test_check_records_every_address_fetched(self):
        source = {"id": "x", "name": "X", "level": "Federal", "kind": "links", "home": "https://a.gov.pk/",
                  "urls": ["https://a.gov.pk/", "https://a.gov.pk/down"]}
        result = src.check(source, Fake({"https://a.gov.pk/": '<a href="/i">Internship Program 2026</a>'}))
        self.assertIsNone(result["error"])                      # one address answered
        self.assertEqual([p.get("status") for p in result["pages"]], [200, None])
        self.assertEqual(result["items"][0]["found_on"], "https://a.gov.pk/")
        failed = src.check(dict(source, urls=["https://a.gov.pk/down"]), Fake({}))
        self.assertTrue(failed["error"])


if __name__ == "__main__":
    unittest.main()
