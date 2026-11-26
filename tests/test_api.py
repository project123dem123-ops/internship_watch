"""The web app: its page, the JSON it reads, and the notification settings."""
import os
import unittest
from unittest import mock

from tests.helpers import Site, TempDB
import config

with mock.patch.object(config, "WORKER", False):
    import api
from fastapi.testclient import TestClient
import store

B = ''  # the app is served at the root


class ApiTest(TempDB):
    def setUp(self):
        super().setUp()
        self.client = TestClient(api.app)

    def test_page_and_health(self):
        self.assertEqual(self.client.get(B + "/").status_code, 200)
        self.assertIn("Internship", self.client.get(B + "/").text)
        self.assertEqual(self.client.get(B + "/static/app.js").status_code, 200)
        self.assertEqual(self.client.get(B + "/static/../config.py").status_code, 404)
        self.assertTrue(self.client.get(B + "/health").json()["ok"])

    def test_status_lists_every_source(self):
        body = self.client.get(B + "/api/status").json()
        self.assertEqual(len(body["sources"]), 18)
        self.assertIn("worker", body)

    def test_only_what_is_still_open_is_listed(self):
        jobs = {"id": "jobs", "name": "Jobs", "level": "Punjab", "kind": "punjab_jobs", "jobs": True}
        news = {"id": "news", "name": "News reports", "level": "News", "kind": "news"}
        store.record(jobs, {"items": [
            {"kind": "job", "title": "Driver", "url": "https://j/1", "deadline": "30-Nov-2026"},
            {"kind": "job", "title": "Clerk", "url": "https://j/2", "deadline": "10-Nov-2026"},   # passed
            {"kind": "job", "title": "Guard", "url": "https://j/3", "deadline": ""}]})            # no date given
        store.record(news, {"items": [
            {"kind": "news", "title": "CM IT Internship registration", "url": "https://news.google.com/rss/articles/X",
             "_key": "news|cm it", "deadline": ""}]})
        body = self.client.get(B + "/api/items").json()
        self.assertEqual(sorted(i["title"] for i in body["items"]), ["Driver", "Guard"])
        self.assertEqual(body["closed"], 2)                    # the passed job, and news with no last date
        self.assertEqual(body["today"], "2026-11-17")

        # The story seen again with its article's address and last date: corrected, and listed.
        store.record(news, {"items": [{"kind": "news", "title": "CM IT Internship registration",
                                       "url": "https://propakistani.pk/cmit", "_key": "news|cm it",
                                       "deadline": "30 Nov 2026"}]})
        story = next(i for i in self.client.get(B + "/api/items").json()["items"] if i["kind"] == "news")
        self.assertEqual((story["url"], story["closes"]), ("https://propakistani.pk/cmit", "2026-11-30"))

    def test_secrets_are_never_sent_back(self):
        saved = self.client.post(B + "/api/channels/telegram", json={"bot_token": "123456:SECRET-TOKEN", "chat_id": "42"}).json()
        self.assertTrue(saved["configured"])
        self.assertNotIn("SECRET", str(self.client.get(B + "/api/channels").json()))
        # An empty secret keeps the saved one.
        self.client.post(B + "/api/channels/telegram", json={"bot_token": "", "chat_id": "43"})
        self.assertTrue(self.client.get(B + "/api/channels").json()["telegram"]["configured"])
        self.client.post(B + "/api/channels/telegram", json={"clear": True})
        self.assertFalse(self.client.get(B + "/api/channels").json()["telegram"]["configured"])

    def test_a_test_notification_reaches_the_channel_and_the_inbox(self):
        site = Site()
        try:
            self.client.post(B + "/api/channels/webhook", json={"url": site.url + "/hook"})
            result = self.client.post(B + "/api/channels/webhook/test").json()
            self.assertTrue(next(d for d in result["deliveries"] if d["channel"] == "webhook")["ok"])
            self.assertIn("Test notification", site.posts[0]["text"])
            inbox = self.client.get(B + "/api/notifications").json()
            self.assertEqual(inbox["unread"], 1)
            self.assertTrue(inbox["notifications"][0]["is_test"])
            self.client.post(B + "/api/notifications/read", json={})
            self.assertEqual(self.client.get(B + "/api/notifications").json()["unread"], 0)
        finally:
            site.close()

    def test_the_page_is_the_apps_own_and_links_nowhere_else(self):
        page = self.client.get("/").text
        self.assertIn("INTERNSHIP WATCH", page)
        self.assertNotRegex(page, r'(href|src)="/(?!static/)[a-z]')   # no links to other apps on this host

    def test_the_check_interval_is_saved_and_applied(self):
        try:
            self.assertEqual(self.client.post(B + "/api/settings", json={"refresh_minutes": 2}).status_code, 400)
            self.assertEqual(self.client.post(B + "/api/settings", json={"refresh_minutes": 60}).json(),
                             {"refresh_minutes": 60})
            self.assertEqual(api.worker.interval, 3600)
            self.assertEqual(store.get_setting("refresh_minutes"), 60)
            self.assertEqual(self.client.get(B + "/api/settings").json()["refresh_minutes"], 60)
        finally:
            api.worker.set_interval(config.REFRESH_MINUTES)

    def test_check_now_starts_the_worker_once(self):
        with mock.patch.object(api.worker, "check_now", side_effect=[True, False]):
            self.assertEqual(self.client.post(B + "/api/check").status_code, 202)
            self.assertFalse(self.client.post(B + "/api/check").json()["started"])


if __name__ == "__main__":
    unittest.main()
