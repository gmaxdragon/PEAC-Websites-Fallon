"""On-site PEAC newsletter stored in the existing private SQLite database.

Text is plain text, never HTML. Only administrators may author or publish.
Public reads use an explicit field allowlist and never return drafts or authors.
The existing Store supplies process-safe SQLite transactions, idempotent writes,
and the persistent database path already used by the Railway volume.
"""
from __future__ import annotations

import re
import uuid

from peac_core import APIError, now_iso, object_payload, text
from portal_auth import require_admin


TITLE_LIMIT = 120
BODY_LIMIT = 10_000
PRIVATE_PATH = "/api/portal/newsletter"
IDENTITY = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
ITEM_PATH = re.compile(rf"{PRIVATE_PATH}/({IDENTITY})(?:/(publish|unpublish))?")
PUBLIC_FIELDS = ("id", "title", "body", "published_at", "updated_at")
PRIVATE_FIELDS = ("id", "title", "body", "status", "created_at", "updated_at", "published_at", "version")


class NewsletterService:
    def __init__(self, store, audit=None, now_fn=now_iso):
        self.store = store
        self.audit = audit
        self.now_fn = now_fn
        # Initialization is idempotent across workers and never seeds public content.
        with self.store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS newsletter_posts (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
                body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 10000),
                status TEXT NOT NULL CHECK(status IN ('draft','published')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                published_at TEXT,
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                CHECK(status = 'draft' OR published_at IS NOT NULL)
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS newsletter_posts_public
                ON newsletter_posts(status, published_at DESC, id DESC)""")

    @staticmethod
    def _fields(row, fields):
        return {name: row[name] for name in fields}

    @staticmethod
    def _body(payload, with_version=False):
        p = object_payload(payload)
        expected = {"title", "body", "version"} if with_version else {"title", "body"}
        if set(p) != expected:
            raise APIError("Send title and body" + (" and the current version." if with_version else "."))
        title = text(p["title"], "Newsletter title", TITLE_LIMIT, True)
        if "\n" in title or "\t" in title:
            raise APIError("Newsletter title must be one line.")
        # Normalize line endings while preserving the content as plain text.
        body = p["body"].replace("\r\n", "\n") if isinstance(p["body"], str) else p["body"]
        body = text(body, "Newsletter body", BODY_LIMIT, True)
        # JSON can represent lone surrogate code points that SQLite cannot store.
        try:
            title.encode("utf-8")
            body.encode("utf-8")
        except UnicodeEncodeError:
            raise APIError("Newsletter text contains an invalid Unicode character.")
        cleaned = {"title": title, "body": body}
        if with_version:
            cleaned["version"] = NewsletterService._version(p["version"])
        return cleaned

    @staticmethod
    def _version(value):
        if type(value) is not int or value < 1:
            raise APIError("Send the current whole-number newsletter version.")
        return value

    @staticmethod
    def _identity(value):
        if not isinstance(value, str) or not re.fullmatch(IDENTITY, value):
            raise APIError("Newsletter post not found.", 404)
        return value

    @staticmethod
    def _get(db, identity, version):
        row = db.execute("SELECT * FROM newsletter_posts WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise APIError("Newsletter post not found.", 404)
        if row["version"] != version:
            raise APIError("This newsletter changed in another session. Reload the list before saving or publishing.", 409)
        return row

    def _audit(self, db, user, action, identity):
        if self.audit is not None:
            self.audit(db, user["id"], action, identity)

    def public_list(self):
        with self.store.connection() as db:
            rows = db.execute("""SELECT id,title,body,published_at,updated_at
                FROM newsletter_posts WHERE status='published'
                ORDER BY published_at DESC, id DESC""").fetchall()
        return {"items": [self._fields(row, PUBLIC_FIELDS) for row in rows]}

    def admin_list(self, user):
        require_admin(user)
        with self.store.connection() as db:
            rows = db.execute("""SELECT id,title,body,status,created_at,updated_at,published_at,version
                FROM newsletter_posts ORDER BY updated_at DESC, id DESC""").fetchall()
        return {"items": [self._fields(row, PRIVATE_FIELDS) for row in rows]}

    def create_draft(self, payload, key, user):
        require_admin(user)
        cleaned = self._body(payload)

        def create(db):
            identity, stamp = str(uuid.uuid4()), self.now_fn()
            db.execute("""INSERT INTO newsletter_posts
                (id,title,body,status,created_at,updated_at,published_at,created_by,updated_by,version)
                VALUES(?,?,?,'draft',?,?,NULL,?,?,1)""",
                (identity, cleaned["title"], cleaned["body"], stamp, stamp, user["id"], user["id"]))
            self._audit(db, user, "newsletter.draft_created", identity)
            row = db.execute("SELECT * FROM newsletter_posts WHERE id=?", (identity,)).fetchone()
            return {"item": self._fields(row, PRIVATE_FIELDS)}

        return self.store.mutate(key, "newsletter:create:" + user["id"], cleaned, create)

    def update_post(self, identity, payload, key, user):
        require_admin(user)
        identity = self._identity(identity)
        cleaned = self._body(payload, with_version=True)

        def update(db):
            current = self._get(db, identity, cleaned["version"])
            db.execute("""UPDATE newsletter_posts
                SET title=?,body=?,updated_at=?,updated_by=?,version=version+1 WHERE id=?""",
                (cleaned["title"], cleaned["body"], self.now_fn(), user["id"], identity))
            self._audit(db, user, "newsletter.published_updated" if current["status"] == "published" else "newsletter.draft_updated", identity)
            row = db.execute("SELECT * FROM newsletter_posts WHERE id=?", (identity,)).fetchone()
            return {"item": self._fields(row, PRIVATE_FIELDS)}

        return self.store.mutate(key, "newsletter:update:" + identity + ":" + user["id"], cleaned, update)

    def _set_status(self, identity, target, payload, key, user):
        require_admin(user)
        identity = self._identity(identity)
        p = object_payload(payload)
        if set(p) != {"version"}:
            raise APIError("Send only the current newsletter version.")
        version = self._version(p["version"])

        def change(db):
            current = self._get(db, identity, version)
            if current["status"] == target:
                raise APIError("This newsletter is already " + target + ". Reload the list.", 409)
            stamp = self.now_fn()
            published_at = stamp if target == "published" else current["published_at"]
            db.execute("""UPDATE newsletter_posts SET status=?,updated_at=?,published_at=?,
                updated_by=?,version=version+1 WHERE id=?""",
                (target, stamp, published_at, user["id"], identity))
            self._audit(db, user, "newsletter.published" if target == "published" else "newsletter.unpublished", identity)
            row = db.execute("SELECT * FROM newsletter_posts WHERE id=?", (identity,)).fetchone()
            return {"item": self._fields(row, PRIVATE_FIELDS)}

        return self.store.mutate(key, "newsletter:" + target + ":" + identity + ":" + user["id"], {"version": version}, change)

    def publish_post(self, identity, payload, key, user):
        return self._set_status(identity, "published", payload, key, user)

    def unpublish_post(self, identity, payload, key, user):
        return self._set_status(identity, "draft", payload, key, user)

    def dispatch(self, method, path, payload=None, key="", user=None):
        """Private routes, called only after the router's session/CSRF checks."""
        require_admin(user)
        if path == PRIVATE_PATH:
            if method == "GET":
                return self.admin_list(user), 200
            if method == "POST":
                result = self.create_draft(payload, key, user)
                return result, 200 if result["replayed"] else 201
            raise APIError("Method not allowed for the newsletter list.", 405)
        match = ITEM_PATH.fullmatch(path)
        if match is None:
            raise APIError("Newsletter route not found.", 404)
        identity, action = match.groups()
        if action is None and method == "PUT":
            return self.update_post(identity, payload, key, user), 200
        if action == "publish" and method == "POST":
            return self.publish_post(identity, payload, key, user), 200
        if action == "unpublish" and method == "POST":
            return self.unpublish_post(identity, payload, key, user), 200
        raise APIError("Method not allowed for this newsletter action.", 405)
