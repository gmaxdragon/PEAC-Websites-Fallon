"""Local PEAC account/session controls with admin-approved sign-up requests."""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
import time
from http.cookies import SimpleCookie
from peac_core import APIError, now_iso, object_payload, text

ITERATIONS = 600_000
SESSION_SECONDS = 4 * 60 * 60
IDLE_SECONDS = 30 * 60
COOKIE = "peac_session"


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise APIError("Use a password of 12 to 256 characters.")
    salt = secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${value}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 2_000_000:
            return False
        result = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(result, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def account_email(value, required=False):
    raw = "" if value is None else str(value).strip()
    if not raw and not required:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", raw):
        raise APIError("Enter one valid email address.")
    local, domain = raw.rsplit("@", 1)
    if len(raw) > 254 or len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in raw:
        raise APIError("Enter one valid email address.")
    return local + "@" + domain.lower()


def account_identity(payload):
    p = object_payload(payload)
    username = text(p.get("username", ""), "username", 60, True).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,59}", username):
        raise APIError("Username: 3 to 60 letters, numbers, dots, hyphens or underscores.")
    display = text(p.get("display_name", username), "display name", 80, True)
    return username, display


class Auth:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portal_users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','coordinator')),
                    password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES portal_users(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL, last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_limits (
                    bucket TEXT PRIMARY KEY, started REAL NOT NULL, hits INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_audit (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    target TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portal_signup_requests (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL, display_name TEXT NOT NULL,
                    email TEXT NOT NULL, password_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')) DEFAULT 'pending',
                    created_at TEXT NOT NULL, reviewed_at TEXT NOT NULL DEFAULT '', reviewed_by TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS portal_signup_status ON portal_signup_requests(status, created_at);
            """)
            cols = {r[1] for r in db.execute("PRAGMA table_info(portal_users)")}
            if "email" not in cols:
                db.execute("ALTER TABLE portal_users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS portal_user_email_unique ON portal_users(lower(email)) WHERE email<>''")
            db.commit()

    def audit(self, db, actor, action, target=""):
        db.execute("INSERT INTO portal_audit VALUES(?,?,?,?,?)",
                   (secrets.token_hex(16), actor, action, target, now_iso()))

    def has_users(self):
        with self.store.connection() as db:
            return bool(db.execute("SELECT 1 FROM portal_users WHERE active=1 LIMIT 1").fetchone())

    def create_user(self, payload, actor="local-setup"):
        p = object_payload(payload)
        if set(p) - {"username", "display_name", "email", "password", "role"}:
            raise APIError("Unsupported account field.")
        username, display = account_identity(p)
        email = account_email(p.get("email", ""), False)
        role = p.get("role", "coordinator")
        if not isinstance(role, str) or role not in {"admin", "coordinator"}:
            raise APIError("Choose admin or coordinator.")
        encoded = hash_password(p.get("password"))
        uid = secrets.token_hex(16)
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM portal_users WHERE username=?", (username,)).fetchone():
                raise APIError("That username already exists.", 409)
            if email and db.execute("SELECT 1 FROM portal_users WHERE lower(email)=lower(?)", (email,)).fetchone():
                raise APIError("That email is already attached to a PEAC account.", 409)
            db.execute("INSERT INTO portal_users(id,username,display_name,role,password_hash,active,created_at,email) VALUES(?,?,?,?,?,1,?,?)",
                       (uid, username, display, role, encoded, now_iso(), email))
            self.audit(db, actor, "account.created", uid)
        return {"id": uid, "username": username, "display_name": display, "email": email, "role": role, "active": True}

    def request_signup(self, payload, peer):
        p = object_payload(payload)
        if set(p) - {"username", "display_name", "email", "password"}:
            raise APIError("Unsupported sign-up field.")
        self.rate_limit("signup-ip:" + peer, 8, 3600)
        username, display = account_identity(p)
        email = account_email(p.get("email"), True)
        encoded = hash_password(p.get("password"))
        sid = secrets.token_hex(16)
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM portal_users WHERE username=?", (username,)).fetchone():
                raise APIError("That username is already in use.", 409)
            if db.execute("SELECT 1 FROM portal_users WHERE lower(email)=lower(?)", (email,)).fetchone():
                raise APIError("That email is already attached to a PEAC account.", 409)
            existing = db.execute("SELECT id FROM portal_signup_requests WHERE status='pending' AND (username=? OR lower(email)=lower(?))", (username, email)).fetchone()
            if existing:
                raise APIError("A sign-up request for that username or email is already waiting for approval.", 409)
            db.execute("INSERT INTO portal_signup_requests(id,username,display_name,email,password_hash,status,created_at) VALUES(?,?,?,?,?,'pending',?)",
                       (sid, username, display, email, encoded, now_iso()))
            self.audit(db, "public-signup", "signup.requested", sid)
        return {"ok": True, "status": "pending", "message": "Sign-up request sent. A PEAC administrator must approve it before you can sign in."}

    def signup_requests(self):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,username,display_name,email,status,created_at FROM portal_signup_requests WHERE status='pending' ORDER BY created_at")]

    def approve_signup(self, sid, actor):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM portal_signup_requests WHERE id=? AND status='pending'", (sid,)).fetchone()
            if not row:
                raise APIError("Pending sign-up request not found.", 404)
            if db.execute("SELECT 1 FROM portal_users WHERE username=? OR lower(email)=lower(?)", (row["username"], row["email"])).fetchone():
                raise APIError("That username or email is already in use. Reject this request or resolve the existing account.", 409)
            uid = secrets.token_hex(16)
            db.execute("INSERT INTO portal_users(id,username,display_name,role,password_hash,active,created_at,email) VALUES(?,?,?,'coordinator',?,1,?,?)",
                       (uid, row["username"], row["display_name"], row["password_hash"], now_iso(), row["email"]))
            db.execute("UPDATE portal_signup_requests SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=?", (now_iso(), actor, sid))
            self.audit(db, actor, "signup.approved", uid)
        return {"ok": True, "id": uid}

    def reject_signup(self, sid, actor):
        with self.store.transaction() as db:
            row = db.execute("SELECT id FROM portal_signup_requests WHERE id=? AND status='pending'", (sid,)).fetchone()
            if not row:
                raise APIError("Pending sign-up request not found.", 404)
            db.execute("UPDATE portal_signup_requests SET status='rejected',reviewed_at=?,reviewed_by=?,password_hash='' WHERE id=?", (now_iso(), actor, sid))
            self.audit(db, actor, "signup.rejected", sid)
        return {"ok": True}

    def rate_limit(self, bucket, maximum, seconds):
        bucket = hashlib.sha256(bucket.encode()).hexdigest()
        now = self.clock()
        with self.store.transaction() as db:
            db.execute("DELETE FROM portal_limits WHERE started < ?", (now - 86400,))
            row = db.execute("SELECT * FROM portal_limits WHERE bucket=?", (bucket,)).fetchone()
            if not row or now - row["started"] >= seconds:
                db.execute("INSERT OR REPLACE INTO portal_limits VALUES(?,?,1)", (bucket, now))
            elif row["hits"] >= maximum:
                raise APIError("Too many attempts. Please wait and try again later.", 429)
            else:
                db.execute("UPDATE portal_limits SET hits=hits+1 WHERE bucket=?", (bucket,))

    def login(self, payload, peer):
        p = object_payload(payload)
        name = text(p.get("username", ""), "username", 60, True).lower()
        password = p.get("password")
        if not isinstance(password, str) or len(password) > 256:
            raise APIError("Invalid sign-in details.", 401)
        self.rate_limit("login-ip:" + peer, 20, 900)
        self.rate_limit("login-user:" + name, 10, 900)
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM portal_users WHERE username=? AND active=1", (name,)).fetchone()
        correct = check_password(password, row["password_hash"] if row else self.dummy_hash)
        if not row or not correct:
            raise APIError("Invalid sign-in details.", 401)
        token, csrf, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), self.clock()
        with self.store.transaction() as db:
            db.execute("DELETE FROM portal_sessions WHERE expires<? OR last_seen<?", (now, now-IDLE_SECONDS))
            db.execute("INSERT INTO portal_sessions VALUES(?,?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), row["id"], csrf, now+SESSION_SECONDS, now))
            self.audit(db, row["id"], "account.signed_in")
        return token, {"user": self.public_user(row), "csrf": csrf}

    @staticmethod
    def public_user(row):
        out = {k: row[k] for k in ("id", "username", "display_name", "role")}
        out["email"] = row["email"] if "email" in row.keys() else ""
        return out

    @staticmethod
    def token_hash(cookie):
        try:
            parsed = SimpleCookie(); parsed.load(cookie or "")
            token = parsed[COOKIE].value if COOKIE in parsed else ""
        except Exception:
            token = ""
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, cookie):
        now, digest = self.clock(), self.token_hash(cookie)
        with self.store.transaction() as db:
            row = db.execute("""SELECT s.*,u.username,u.display_name,u.role,u.active,u.id,u.email
                FROM portal_sessions s JOIN portal_users u ON u.id=s.user_id
                WHERE token_hash=?""", (digest,)).fetchone()
            if not row or not row["active"] or row["expires"] <= now or row["last_seen"]+IDLE_SECONDS <= now:
                if row: db.execute("DELETE FROM portal_sessions WHERE token_hash=?", (digest,))
                return None
            db.execute("UPDATE portal_sessions SET last_seen=? WHERE token_hash=?", (now, digest))
            return {"user": self.public_user(row), "csrf": row["csrf"]}

    def logout(self, cookie):
        with self.store.transaction() as db:
            db.execute("DELETE FROM portal_sessions WHERE token_hash=?", (self.token_hash(cookie),))

    def users(self):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,username,display_name,email,role,active,created_at FROM portal_users ORDER BY username")]

    def disable(self, uid, actor):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM portal_users WHERE id=? AND active=1", (uid,)).fetchone()
            if not row: raise APIError("Active account not found.", 404)
            if row["id"] == actor: raise APIError("You cannot disable your own current account.")
            if row["role"] == "admin" and db.execute("SELECT COUNT(*) FROM portal_users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise APIError("Keep at least one administrator.")
            db.execute("UPDATE portal_users SET active=0 WHERE id=?", (uid,))
            db.execute("DELETE FROM portal_sessions WHERE user_id=?", (uid,))
            self.audit(db, actor, "account.disabled", uid)
        return {"ok": True}

    def change_password(self, user, payload):
        p = object_payload(payload)
        with self.store.connection() as db:
            row = db.execute("SELECT password_hash FROM portal_users WHERE id=?", (user["id"],)).fetchone()
        if not check_password(p.get("current_password", ""), row[0]):
            raise APIError("Current password is incorrect.", 400)
        encoded = hash_password(p.get("new_password"))
        with self.store.transaction() as db:
            db.execute("UPDATE portal_users SET password_hash=? WHERE id=?", (encoded, user["id"]))
            db.execute("DELETE FROM portal_sessions WHERE user_id=?", (user["id"],))
            self.audit(db, user["id"], "account.password_changed")
        return {"ok": True, "sign_in_again": True}


def require_admin(user):
    if not user or user.get("role") != "admin":
        raise APIError("Administrator access is required.", 403)
