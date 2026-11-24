"""The worker end to end, against a local website: a post added to the site
after the first check is found, read for its dates, and notified."""
import os
import unittest
from unittest import mock

from tests.helpers import Site, TempDB
import notify
import store
from worker import Worker

LISTING_BEFORE = """<table><tbody>
<tr><td><a href="{base}/job_detail/driver-95">Driver</a></td><td>PEECA</td><td>PEECA</td><td>PUNJAB</td><td>30-Nov-2026</td></tr>
<tr><td><a href="{base}/job_detail/it-internship-1">IT Internship (Cohort 2)</a></td><td>PITB</td><td>CM IT Internship</td><td>PUNJAB</td><td>20-Nov-2026</td></tr>
</tbody></table>"""
NEW_ROW = """<tr><td><a href="{base}/job_detail/shrimp-internship-2">Shrimp Internship Program 2026-27</a></td>
<td>Fisheries Department</td><td>Shrimp Internship</td><td>PUNJAB</td><td></td></tr></tbody>"""
NEW_DETAIL = "<div>Posted 16-11-2026 Last Date to Apply 05-12-2026 District MUZAFFARGARH Domicile Punjab</div>"


class WorkerEndToEndTest(TempDB):
    def setUp(self):
        super().setUp()
        self.site = Site()
        base = self.site.url
        self.site.pages["/jobs"] = LISTING_BEFORE.format(base=base)
        self.site.pages["/programme"] = "<p>Total vacancies: 2,000 for the second cohort of interns</p>"
        self.sources = [
            {"id": "punjab-jobs", "name": "Punjab Jobs Portal", "level": "Punjab", "kind": "punjab_jobs",
             "home": base + "/jobs", "urls": [base + "/jobs"]},
            {"id": "cm-it", "name": "CM IT Internship Program", "level": "Punjab", "kind": "page",
             "home": base + "/programme", "urls": [base + "/programme"]},
            {"id": "down", "name": "A site that is down", "level": "Federal", "kind": "links",
             "home": base + "/missing", "urls": [base + "/missing"]},
        ]
        # Deliveries go to the local site's webhook, never anywhere real.
        os.environ["INTERNSHIPS_WEBHOOK_URL"] = base + "/hook"
        self.worker = Worker(self.sources, interval_minutes=5)

    def tearDown(self):
        self.site.close()
        super().tearDown()

    def test_first_check_is_the_baseline_and_a_later_post_is_new_and_notified(self):
        first = self.worker.run_cycle("schedule")
        self.assertEqual((first["sources_ok"], first["sources_failed"]), (2, 1))
        self.assertEqual(first["new"], [])                      # already there: not announced
        self.assertEqual(self.site.posts, [])
        self.assertEqual(store.notifications()[0], [])

        # The site publishes a new internship, and the programme page a new line.
        base = self.site.url
        self.site.pages["/jobs"] = self.site.pages["/jobs"].replace("</tbody>", NEW_ROW.format(base=base))
        self.site.pages["/job_detail/shrimp-internship-2"] = NEW_DETAIL
        self.site.pages["/programme"] += "<p>Registration for the third cohort of interns opens on 1 December</p>"

        second = self.worker.run_cycle("manual")
        titles = sorted(i["title"] for i in second["new"])
        self.assertEqual(titles, ["CM IT Internship Program: the page changed", "Shrimp Internship Program 2026-27"])
        post = next(i for i in store.items() if i["title"].startswith("Shrimp"))
        self.assertEqual(post["deadline"], "05-12-2026")        # read from the post's own page
        self.assertEqual(post["posted"], "16-11-2026")
        self.assertEqual(post["found_on"], base + "/jobs")
        self.assertFalse(post["baseline"])

        notes, unread = store.notifications()
        self.assertEqual(unread, 1)
        self.assertEqual(notes[0]["title"], "2 new internships posted")
        self.assertEqual({d["channel"]: bool(d["ok"]) for d in notes[0]["deliveries"]}, {"inbox": True, "webhook": True})
        self.assertEqual(len(self.site.posts), 1)               # the webhook really received it
        self.assertIn("Shrimp Internship Program 2026-27", self.site.posts[0]["text"])

        third = self.worker.run_cycle("schedule")               # nothing changed: nothing new
        self.assertEqual(third["new"], [])
        self.assertEqual(len(self.site.posts), 1)
        self.assertEqual([r["new_items"] for r in store.runs()], [0, 2, 0])

    def test_the_timer_runs_checks_in_the_background(self):
        self.worker.start(first_delay=0)
        try:
            for _ in range(100):
                if store.runs():
                    break
                import time
                time.sleep(0.1)
            self.assertTrue(self.worker.alive())
            self.assertEqual(store.runs()[-1]["trigger"], "schedule")
        finally:
            self.worker.stop()
            self.worker._thread.join(timeout=30)   # let a check in progress finish inside the test's database

    def test_a_failing_channel_does_not_stop_the_others(self):
        os.environ["INTERNSHIPS_WEBHOOK_URL"] = self.site.url + "/hook"
        os.environ["INTERNSHIPS_TELEGRAM_BOT_TOKEN"] = "x"
        os.environ["INTERNSHIPS_TELEGRAM_CHAT_ID"] = "1"
        with mock.patch.dict(notify.SENDERS, telegram=mock.Mock(side_effect=RuntimeError("Telegram answered 401"))):
            result = notify.dispatch([{"id": "a", "title": "Internship", "level": "Punjab", "source": "X"}])
        by = {d["channel"]: d for d in result["deliveries"]}
        self.assertTrue(by["webhook"]["ok"])
        self.assertFalse(by["telegram"]["ok"])
        self.assertIn("401", by["telegram"]["detail"])


if __name__ == "__main__":
    unittest.main()
