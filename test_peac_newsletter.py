"""Isolated model and router checks for the on-site newsletter.

Run with ``python -m unittest -v test_peac_newsletter``. Every test uses a
temporary synthetic SQLite database; no hosted service or real account is used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
import uuid

from peac_core import APIError, Store
from peac_newsletter import NewsletterService


ADMIN = {"id": "synthetic-admin", "role": "admin"}
COORDINATOR = {"id": "synthetic-coordinator", "role": "coordinator"}
STAMP = "2026-10-20T12:00:00+00:00"
PUBLIC_KEYS = {"id", "title", "body", "published_at", "updated_at"}
PRIVATE_KEYS = PUBLIC_KEYS | {"status", "created_at", "version"}
ROOT = Path(__file__).resolve().parent


def request_key():
    return str(uuid.uuid4())


class NewsletterModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="peac-newsletter-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.sqlite3"
        self.store = Store(self.path)
        self.newsletter = NewsletterService(self.store, now_fn=lambda: STAMP)

    def draft(self, title="A school update", body="Meet us at lunch."):
        return self.newsletter.create_draft(
            {"title": title, "body": body}, request_key(), ADMIN
        )["item"]

    def publish(self, item):
        return self.newsletter.publish_post(
            item["id"], {"version": item["version"]}, request_key(), ADMIN
        )["item"]

    def assert_api_error(self, status, function, *args):
        with self.assertRaises(APIError) as raised:
            function(*args)
        self.assertEqual(raised.exception.status, status)

    def test_drafts_are_private_and_new_database_starts_empty(self):
        self.assertEqual(self.newsletter.public_list(), {"items": []})
        self.assertEqual(self.newsletter.admin_list(ADMIN), {"items": []})
        item = self.draft()
        self.assertEqual(item["status"], "draft")
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["version"], 1)
        self.assertEqual(set(item), PRIVATE_KEYS)
        self.assertEqual(self.newsletter.public_list(), {"items": []})
        self.assertEqual(self.newsletter.admin_list(ADMIN)["items"], [item])

    def test_public_fields_are_allowlisted_and_survive_reopening(self):
        draft = self.draft()
        published = self.publish(draft)
        reopened = NewsletterService(Store(self.path))
        self.assertEqual(reopened.admin_list(ADMIN)["items"], [published])
        public = reopened.public_list()["items"]
        self.assertEqual(len(public), 1)
        self.assertEqual(set(public[0]), PUBLIC_KEYS)
        self.assertEqual(public[0]["title"], draft["title"])
        self.assertEqual(public[0]["published_at"], STAMP)
        self.assertNotIn(ADMIN["id"], json.dumps(public))

    def test_edit_published_unpublish_and_republish_have_explicit_effects(self):
        published = self.publish(self.draft())
        self.newsletter.now_fn = lambda: "2026-10-21T12:00:00+00:00"
        edited = self.newsletter.update_post(
            published["id"],
            {"title": "Updated plan", "body": "A new meeting time.", "version": published["version"]},
            request_key(), ADMIN,
        )["item"]
        self.assertEqual(edited["status"], "published")
        self.assertEqual(edited["published_at"], published["published_at"])
        self.assertEqual(self.newsletter.public_list()["items"][0]["body"], "A new meeting time.")
        unpublished = self.newsletter.unpublish_post(
            edited["id"], {"version": edited["version"]}, request_key(), ADMIN
        )["item"]
        self.assertEqual(unpublished["status"], "draft")
        self.assertEqual(unpublished["published_at"], published["published_at"])
        self.assertEqual(self.newsletter.public_list(), {"items": []})
        self.newsletter.now_fn = lambda: "2026-10-22T12:00:00+00:00"
        republished = self.publish(unpublished)
        self.assertEqual(republished["published_at"], "2026-10-22T12:00:00+00:00")
        self.assertEqual(republished["version"], 5)

    def test_public_list_has_no_silent_small_cap_and_order_is_stable(self):
        identities = [self.publish(self.draft(f"Update {index}"))["id"] for index in range(65)]
        self.draft("This draft must stay private")
        public = self.newsletter.public_list()["items"]
        self.assertEqual([item["id"] for item in public], sorted(identities, reverse=True))
        self.newsletter.now_fn = lambda: "2026-10-21T00:00:00+00:00"
        newest = self.publish(self.draft("Most recent publication"))
        self.assertEqual(self.newsletter.public_list()["items"][0]["id"], newest["id"])

    def test_retries_replay_once_across_a_restart_and_keys_cannot_change_data(self):
        payload = {"title": "One update", "body": "Only one copy."}
        create_key = request_key()
        created = self.newsletter.create_draft(payload, create_key, ADMIN)
        self.newsletter = NewsletterService(Store(self.path), now_fn=lambda: STAMP)
        retry = self.newsletter.create_draft(payload, create_key, ADMIN)
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["item"], created["item"])
        self.assertEqual(retry["revision"], created["revision"])
        self.assertEqual(len(self.newsletter.admin_list(ADMIN)["items"]), 1)
        self.assert_api_error(409, self.newsletter.create_draft,
                              {**payload, "body": "Changed payload"}, create_key, ADMIN)
        item = created["item"]
        for action in (self.newsletter.publish_post, self.newsletter.unpublish_post):
            key = request_key()
            result = action(item["id"], {"version": item["version"]}, key, ADMIN)
            retried = action(item["id"], {"version": item["version"]}, key, ADMIN)
            self.assertTrue(retried["replayed"])
            self.assertEqual(retried["item"], result["item"])
            self.assertEqual(retried["revision"], result["revision"])
            item = result["item"]
        update_key = request_key()
        changes = {"title": "Edited once", "body": "Retry safely.", "version": item["version"]}
        result = self.newsletter.update_post(item["id"], changes, update_key, ADMIN)
        retry = self.newsletter.update_post(item["id"], changes, update_key, ADMIN)
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["item"], result["item"])
        self.assertEqual(self.newsletter.admin_list(ADMIN)["items"][0]["version"], 4)

    def test_admin_authorization_is_checked_before_any_receipt_replay(self):
        key = request_key()
        payload = {"title": "Private draft", "body": "Not ready yet."}
        item = self.newsletter.create_draft(payload, key, ADMIN)["item"]
        for user in (None, COORDINATOR):
            with self.subTest(user=user):
                self.assert_api_error(403, self.newsletter.admin_list, user)
                self.assert_api_error(403, self.newsletter.create_draft, payload, key, user)
                self.assert_api_error(403, self.newsletter.update_post, item["id"],
                                      {**payload, "version": 1}, request_key(), user)
                self.assert_api_error(403, self.newsletter.publish_post, item["id"],
                                      {"version": 1}, request_key(), user)
                self.assert_api_error(403, self.newsletter.unpublish_post, item["id"],
                                      {"version": 1}, request_key(), user)
                self.assert_api_error(403, self.newsletter.dispatch,
                                      "GET", "/api/portal/newsletter", None, "", user)
        other_admin = {"id": "another-synthetic-admin", "role": "admin"}
        self.assert_api_error(409, self.newsletter.create_draft, payload, key, other_admin)

    def test_stale_versions_prevent_edit_publish_and_unpublish(self):
        item = self.draft()
        published = self.publish(item)
        self.assert_api_error(409, self.newsletter.update_post, item["id"],
                              {"title": "Old title", "body": "Old editor", "version": 1}, request_key(), ADMIN)
        self.assert_api_error(409, self.newsletter.publish_post, item["id"],
                              {"version": 1}, request_key(), ADMIN)
        self.assert_api_error(409, self.newsletter.unpublish_post, item["id"],
                              {"version": 1}, request_key(), ADMIN)
        self.assertEqual(self.newsletter.admin_list(ADMIN)["items"], [published])
        self.assert_api_error(409, self.newsletter.publish_post, item["id"],
                              {"version": 2}, request_key(), ADMIN)

    def test_simultaneous_editors_cannot_overwrite_each_other(self):
        item = self.draft()
        services = [self.newsletter, NewsletterService(Store(self.path), now_fn=lambda: STAMP)]
        start = Barrier(2)

        def save(index):
            start.wait(timeout=5)
            try:
                return services[index].update_post(
                    item["id"], {"title": f"Editor {index}", "body": "Concurrent update", "version": 1},
                    request_key(), ADMIN,
                )["item"]
            except APIError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(save, range(2)))
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 1)
        self.assertIn(409, results)
        self.assertEqual(self.newsletter.admin_list(ADMIN)["items"], winners)
        self.assertEqual(winners[0]["version"], 2)

    def test_failed_transaction_leaves_no_draft_or_idempotency_receipt(self):
        def failed_audit(*args):
            raise RuntimeError("Synthetic failure before commit")

        self.newsletter.audit = failed_audit
        key = request_key()
        payload = {"title": "Atomic update", "body": "Rollback on error."}
        with self.assertRaises(RuntimeError):
            self.newsletter.create_draft(payload, key, ADMIN)
        self.assertEqual(self.newsletter.admin_list(ADMIN), {"items": []})
        with self.store.connection() as db:
            self.assertIsNone(db.execute("SELECT key FROM receipts WHERE key=?", (key,)).fetchone())
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0], "0")
        self.newsletter.audit = None
        self.assertFalse(self.newsletter.create_draft(payload, key, ADMIN)["replayed"])

    def test_text_limits_fields_and_versions_are_validated(self):
        invalid = [
            {}, {"title": "Title"}, {"title": "", "body": "Body"},
            {"title": "Title", "body": "  "}, {"title": "T" * 121, "body": "Body"},
            {"title": "Title", "body": "B" * 10001}, {"title": 12, "body": "Body"},
            {"title": "Title", "body": []}, {"title": "Two\nlines", "body": "Body"},
            {"title": "Title", "body": "Bad\x00body"},
            {"title": "Bad\ud800title", "body": "Body"},
            {"title": "Title", "body": "Bad\udfffbody"},
            {"title": "Title", "body": "Body", "status": "published"},
            {"title": "Title", "body": "Body", "created_by": "someone else"},
        ]
        for payload in invalid:
            with self.subTest(payload=repr(payload)[:120]):
                self.assert_api_error(400, self.newsletter.create_draft, payload, request_key(), ADMIN)
        max_item = self.draft("T" * 120, "B" * 10000)
        for value in (True, False, 0, -1, 1.0, "1", None):
            self.assert_api_error(400, self.newsletter.publish_post, max_item["id"],
                                  {"version": value}, request_key(), ADMIN)
        self.assert_api_error(400, self.newsletter.create_draft,
                              {"title": "Title", "body": "Body"}, "short-key", ADMIN)

    def test_html_like_content_is_preserved_as_plain_text(self):
        item = self.draft("  <b>PEAC</b>  ", ' First line\r\n<script>alert("test")</script> ')
        self.assertEqual(item["title"], "<b>PEAC</b>")
        self.assertEqual(item["body"], 'First line\n<script>alert("test")</script>')
        self.publish(item)
        self.assertEqual(self.newsletter.public_list()["items"][0]["body"], item["body"])

    def test_private_route_methods_and_missing_ids_are_rejected(self):
        identity = str(uuid.uuid4())
        self.assert_api_error(404, self.newsletter.update_post, identity,
                              {"title": "Title", "body": "Body", "version": 1}, request_key(), ADMIN)
        self.assert_api_error(404, self.newsletter.publish_post, "../other",
                              {"version": 1}, request_key(), ADMIN)
        self.assert_api_error(405, self.newsletter.dispatch,
                              "DELETE", "/api/portal/newsletter", {}, request_key(), ADMIN)
        self.assert_api_error(405, self.newsletter.dispatch,
                              "GET", f"/api/portal/newsletter/{identity}/publish", None, "", ADMIN)
        self.assert_api_error(404, self.newsletter.dispatch,
                              "POST", f"/api/portal/newsletter/{identity}/unknown", {}, request_key(), ADMIN)


class NewsletterRouterTests(unittest.TestCase):
    def setUp(self):
        from peac_community import CommunityService
        from portal_auth import COOKIE
        from portal_server import PortalRouter

        temporary = tempfile.TemporaryDirectory(prefix="peac-newsletter-router-test-")
        self.addCleanup(temporary.cleanup)
        self.hosted = patch("portal_server.HOSTED", False)
        self.hosted.start()
        self.addCleanup(self.hosted.stop)
        self.path = Path(temporary.name) / "synthetic.sqlite3"
        self.service = CommunityService(self.path, today_fn=lambda: date(2026, 10, 20), use_ml=False)
        self.router = PortalRouter(self.service, ROOT)
        self.sessions = {}
        for name, role in (("peacadmin", "admin"), ("coordinator", "coordinator")):
            password = "Synthetic-Test-Password-Only-2026"
            self.service.auth.create_user(
                {"username": name, "display_name": "Synthetic test account", "password": password, "role": role}
            )
            token, session = self.service.auth.login({"username": name, "password": password}, "127.0.0.1")
            self.sessions[role] = {"Cookie": f"{COOKIE}={token}", "X-CSRF-Token": session["csrf"]}

    def call(self, method, path, payload=None, role=None, key=None, overrides=None):
        headers = {"Host": "localhost"}
        if role:
            headers.update(self.sessions[role])
        if method not in {"GET", "HEAD"}:
            headers.update({"Origin": "http://localhost", "X-PEAC-Client": "1", "Content-Type": "application/json"})
            headers["Idempotency-Key"] = key or request_key()
        if overrides:
            headers.update(overrides)
        try:
            status, body, mime, _ = self.router.handle(
                method, path, headers, body=json.dumps(payload).encode() if payload is not None else b""
            )
        except APIError as exc:
            return exc.status, {"error": str(exc)}
        self.assertTrue(mime.startswith("application/json"))
        return status, json.loads(body)

    def create(self):
        status, result = self.call("POST", "/api/portal/newsletter",
                                   {"title": "School update", "body": "Synthetic announcement."}, "admin")
        self.assertEqual(status, 201)
        return result["item"]

    def test_public_get_is_anonymous_and_private_routes_require_admin(self):
        self.assertEqual(self.call("GET", "/api/public/newsletter"), (200, {"items": []}))
        self.assertEqual(self.call("GET", "/api/portal/newsletter")[0], 401)
        self.assertEqual(self.call("GET", "/api/portal/newsletter", role="coordinator")[0], 403)
        item = self.create()
        self.assertEqual(self.call("GET", "/api/public/newsletter"), (200, {"items": []}))
        for path, payload, method in (
            ("/api/portal/newsletter", {"title": "Title", "body": "Body"}, "POST"),
            (f'/api/portal/newsletter/{item["id"]}', {"title": "Title", "body": "Body", "version": 1}, "PUT"),
            (f'/api/portal/newsletter/{item["id"]}/publish', {"version": 1}, "POST"),
            (f'/api/portal/newsletter/{item["id"]}/unpublish', {"version": 1}, "POST"),
        ):
            self.assertEqual(self.call(method, path, payload)[0], 401)
            self.assertEqual(self.call(method, path, payload, "coordinator")[0], 403)

    def test_existing_csrf_origin_and_json_guards_apply(self):
        payload = {"title": "Synthetic draft", "body": "Do not publish."}
        for overrides, expected in (
            ({"X-CSRF-Token": ""}, 403),
            ({"Origin": "https://other.example"}, 403),
            ({"X-PEAC-Client": ""}, 403),
            ({"Content-Type": "text/plain"}, 415),
            ({"Idempotency-Key": ""}, 400),
        ):
            with self.subTest(headers=overrides):
                status, _ = self.call("POST", "/api/portal/newsletter", payload, "admin", overrides=overrides)
                self.assertEqual(status, expected)
        self.assertEqual(self.call("GET", "/api/portal/newsletter", role="admin"), (200, {"items": []}))

    def test_full_lifecycle_retry_and_public_boundary_through_router(self):
        payload = {"title": "Newsletter", "body": "First draft."}
        key = request_key()
        status, created = self.call("POST", "/api/portal/newsletter", payload, "admin", key)
        self.assertEqual(status, 201)
        status, replay = self.call("POST", "/api/portal/newsletter", payload, "admin", key)
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(created["item"], replay["item"])
        item = created["item"]
        path = f'/api/portal/newsletter/{item["id"]}'
        status, updated = self.call("PUT", path, {"title": "Ready to share", "body": "Final text.", "version": 1}, "admin")
        self.assertEqual(status, 200)
        self.assertEqual(updated["item"]["version"], 2)
        self.assertEqual(self.call("POST", path + "/publish", {"version": 1}, "admin")[0], 409)
        status, published = self.call("POST", path + "/publish", {"version": 2}, "admin")
        self.assertEqual(status, 200)
        status, public = self.call("GET", "/api/public/newsletter")
        self.assertEqual(status, 200)
        self.assertEqual(len(public["items"]), 1)
        self.assertEqual(set(public["items"][0]), PUBLIC_KEYS)
        self.assertEqual(public["items"][0]["body"], "Final text.")
        self.assertEqual(self.call("GET", "/api/public/newsletter", role="coordinator"), (200, public))
        status, _ = self.call("POST", path + "/unpublish", {"version": published["item"]["version"]}, "admin")
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/api/public/newsletter"), (200, {"items": []}))
        with self.service.store.connection() as db:
            actions = [row[0] for row in db.execute("SELECT action FROM portal_audit WHERE action LIKE 'newsletter.%' ORDER BY created_at")]
        self.assertEqual(actions, ["newsletter.draft_created", "newsletter.draft_updated", "newsletter.published", "newsletter.unpublished"])

    def test_restarting_router_preserves_published_content(self):
        from peac_community import CommunityService
        from portal_server import PortalRouter

        item = self.create()
        self.assertEqual(self.call("POST", f'/api/portal/newsletter/{item["id"]}/publish', {"version": 1}, "admin")[0], 200)
        expected = self.call("GET", "/api/public/newsletter")
        self.service = CommunityService(self.path, use_ml=False)
        self.router = PortalRouter(self.service, ROOT)
        self.assertEqual(self.call("GET", "/api/public/newsletter"), expected)
        status, private = self.call("GET", "/api/portal/newsletter", role="admin")
        self.assertEqual(status, 200)
        self.assertEqual(private["items"][0]["status"], "published")


if __name__ == "__main__":
    unittest.main()
