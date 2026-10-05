"""Public-safe content, private Lunch Buddies, and staff-only administration.
All tables use the existing PEAC database. Public endpoints are allowlisted.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import uuid
from datetime import date, timedelta
from peac_core import APIError, Service, object_payload, text, now_iso, local_today
from portal_auth import Auth, require_admin

STATES = {"new", "contacted", "scheduled", "completed", "cancelled"}
SUPPORTS = {"company", "new_people", "finding_group"}

DAILY_QUOTES = [
    "Kindness gets stronger when someone decides to start.",
    "A better school day can begin with one good choice.",
    "Notice people. Include people. That is where community starts.",
    "Small acts count because people remember how you made the day feel.",
    "Make room at the table, in the group, and in the conversation.",
    "The easiest way to improve a community is to contribute to it.",
    "Being welcoming is a skill. Practice it every day.",
    "A compliment takes seconds and can change the direction of a day.",
    "Good communities are built by people who pay attention to each other.",
    "Do one useful, kind thing before the day is over.",
    "Connection often starts with a simple hello.",
    "Kindness works best when it becomes a habit, not an event.",
    "If someone looks left out, that is a chance to make a difference.",
    "The culture of a school is made from thousands of small moments.",
    "Help someone feel seen today.",
    "You do not need a big plan to make one moment better.",
    "Respect is something you show before you expect it back.",
    "Community grows when people choose participation over watching.",
    "Make the next person you talk to feel like they belong here.",
    "A strong community makes space for people who are still finding their place.",
    "Be the reason someone has one easier moment today.",
    "Consistency turns good intentions into a better culture.",
    "Kindness is most useful when it becomes action.",
    "A good team notices who has not been invited in yet.",
    "One thoughtful action is better than ten good intentions.",
    "A community improves when everyone believes they can contribute.",
    "Choose curiosity before judgment.",
    "Make belonging something people can actually feel.",
    "The best kind of leadership makes other people stronger.",
    "Leave one interaction better than you found it.",
    "People remember when someone chose to include them.",
]

DEFAULT_CONTENT = {
    "school_label": "Our school community", "about": "",
    "lunch_intro": "A friendly face. A place at the table. Ask the PEAC team about joining Lunch Buddies.",
    "privacy_notice": "Only authorized PEAC coordinators can see your request. Share only what is needed to arrange lunch. This form is not monitored for emergencies; speak to a trusted adult for urgent help.",
    "lunch_enabled": False, "default_contact_ids": [],
}


def email_address(value):
    email = text(value, "email", 254, True)
    # Deliberately accepts a conservative ASCII subset. Never permits headers or lists.
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", email):
        raise APIError("Enter one valid email address.")
    local, domain = email.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in email:
        raise APIError("Enter one valid email address.")
    return local + "@" + domain.lower()


class CommunityService(Service):
    def __init__(self, db_path, today_fn=local_today, use_ml=False):
        super().__init__(db_path, today_fn, use_ml)
        self.auth = Auth(self.store)
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portal_content (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lunch_contacts (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                    active INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lunch_requests (
                    id TEXT PRIMARY KEY, reference TEXT UNIQUE NOT NULL, preferred_name TEXT NOT NULL,
                    email TEXT NOT NULL, grade TEXT NOT NULL, preferred_date TEXT NOT NULL,
                    lunch_period TEXT NOT NULL, support TEXT NOT NULL, details TEXT NOT NULL,
                    status TEXT NOT NULL, staff_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS lunch_outbox (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES lunch_requests(id) ON DELETE CASCADE,
                    contact_id TEXT NOT NULL REFERENCES lunch_contacts(id), recipient TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued', created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    UNIQUE(request_id, contact_id)
                );
                CREATE TABLE IF NOT EXISTS lunch_receipts (
                    key_hash TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, reference TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_knowledge (
                    id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
                    approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_turns (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, intent TEXT NOT NULL,
                    source_ids TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_feedback (
                    id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES assistant_turns(id),
                    user_id TEXT NOT NULL, rating TEXT NOT NULL, suggestion TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(turn_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS compliment_people (
                    entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                    person_name TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS compliment_people_name ON compliment_people(person_name);\n                CREATE TABLE IF NOT EXISTS site_feedback (id TEXT PRIMARY KEY, source TEXT NOT NULL, message TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lunch_buddy_preferences (
                    request_id TEXT PRIMARY KEY REFERENCES lunch_requests(id) ON DELETE CASCADE,
                    requested_name TEXT NOT NULL, matched_user_id TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS portal_notifications (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, href TEXT NOT NULL,
                    created_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS portal_notifications_user ON portal_notifications(user_id, read_at, created_at);
            """)
            db.execute("INSERT OR IGNORE INTO portal_content VALUES(1,?)", (json.dumps(DEFAULT_CONTENT),))
            db.commit()

    def content(self):
        with self.store.connection() as db:
            return {**DEFAULT_CONTENT, **json.loads(db.execute("SELECT payload FROM portal_content WHERE id=1").fetchone()[0])}

    def quote_of_day(self):
        today = self.today_fn()
        day = today.isoformat()
        # Consecutive days advance through the curated PEAC quote set, so the
        # quote always changes day-to-day and repeats only after the full set.
        quote = DAILY_QUOTES[today.toordinal() % len(DAILY_QUOTES)]
        return {"text": quote, "date": day, "source": "PEAC daily quote"}

    def public_content(self):
        config = self.content()
        # Do NOT return settings wholesale. The public site must not expose private IDs/emails.
        return {key: config[key] for key in ("school_label", "about", "lunch_intro", "privacy_notice", "lunch_enabled")} | {
            "compliments": "coming_soon", "today": self.today_fn().isoformat(), "quote": self.quote_of_day(),
            "notice": "Hosted PEAC site." if __import__("os").getenv("PEAC_DEPLOY_MODE","").lower()=="hosted" else "Local preview. Public hosting is not configured.",
        }

    def save_feedback(self, payload, source, user_id="public"):
        p=object_payload(payload)
        if set(p)!={"message"}: raise APIError("Send only the feedback message.")
        message=text(p.get("message",""),"feedback",1500,True)
        self.auth.rate_limit("feedback:"+str(user_id),12,3600)
        identity=str(uuid.uuid4())
        with self.store.transaction() as db:
            db.execute("INSERT INTO site_feedback VALUES(?,?,?,?,?)",(identity,source,message,str(user_id),now_iso()))
        return {"ok":True,"id":identity,"notice":"Feedback saved privately for PEAC administrators."}

    def feedback_items(self, user):
        require_admin(user)
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,source,message,created_by,created_at FROM site_feedback ORDER BY created_at DESC LIMIT 200")]

    @staticmethod
    def _match_name(value):
        return " ".join(str(value or "").strip().casefold().split())

    def _match_buddy_account(self, db, requested_name):
        needle=self._match_name(requested_name)
        if not needle: return ""
        matches=[]
        for row in db.execute("SELECT id,username,display_name FROM portal_users WHERE active=1"):
            if needle in {self._match_name(row["username"]), self._match_name(row["display_name"])}:
                matches.append(row["id"])
        matches=list(dict.fromkeys(matches))
        return matches[0] if len(matches)==1 else ""

    def notifications(self, user):
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute(
                "SELECT id,kind,title,body,href,created_at,read_at FROM portal_notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
                (user["id"],))]
        return {"items":rows,"unread":sum(1 for r in rows if not r["read_at"])}

    def mark_notifications_read(self, user):
        stamp=now_iso()
        with self.store.transaction() as db:
            db.execute("UPDATE portal_notifications SET read_at=? WHERE user_id=? AND read_at=''",(stamp,user["id"]))
        return {"ok":True}

    def contacts(self):
        with self.store.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM lunch_contacts ORDER BY label,email")]

    def save_content(self, payload, key, user):
        require_admin(user)
        p = object_payload(payload)
        if set(p) != set(DEFAULT_CONTENT):
            raise APIError("Send the complete public content settings and default recipient selection.")
        cleaned = {}
        for field, maximum, required in [("school_label",80,True),("about",5000,False),("lunch_intro",600,True),("privacy_notice",1500,True)]:
            cleaned[field] = text(p[field], field, maximum, required)
        if type(p["lunch_enabled"]) is not bool:
            raise APIError("lunch_enabled must be true or false.")
        cleaned["lunch_enabled"] = p["lunch_enabled"]
        ids = p["default_contact_ids"]
        if not isinstance(ids, list) or len(ids)>10 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise APIError("Choose up to ten distinct approved contacts.")
        cleaned["default_contact_ids"] = ids
        def update(db):
            self.check_contacts(db,ids)
            if cleaned["lunch_enabled"] and not ids:
                raise APIError("Select an approved coordinator before opening requests.")
            db.execute("UPDATE portal_content SET payload=? WHERE id=1", (json.dumps(cleaned),))
            self.auth.audit(db,user["id"],"website.updated")
            return {"saved":True}
        return self.store.mutate(key,"website",p,update)

    @staticmethod
    def check_contacts(db, ids):
        for cid in ids:
            if not db.execute("SELECT 1 FROM lunch_contacts WHERE id=? AND active=1", (cid,)).fetchone():
                raise APIError("A selected contact is no longer active. Refresh the recipient selection.",409)

    def save_contact(self, payload, key, user, cid=None):
        require_admin(user)
        p = object_payload(payload)
        if set(p)-{"label","email","active"}: raise APIError("Unknown contact field.")
        label = text(p.get("label",""),"contact label",80,True)
        email = email_address(p.get("email",""))
        active = p.get("active",True)
        if type(active) is not bool: raise APIError("active must be true or false.")
        identity=cid or str(uuid.uuid4())
        def operation(db):
            if cid and not db.execute("SELECT 1 FROM lunch_contacts WHERE id=?",(cid,)).fetchone():
                raise APIError("Contact not found.",404)
            if db.execute("SELECT 1 FROM lunch_contacts WHERE lower(email)=lower(?) AND id!=?",(email,identity)).fetchone():
                raise APIError("This contact email is already saved.",409)
            config=json.loads(db.execute("SELECT payload FROM portal_content WHERE id=1").fetchone()[0])
            if not active and identity in config["default_contact_ids"]:
                config["default_contact_ids"].remove(identity)
                if not config["default_contact_ids"]: config["lunch_enabled"]=False
                db.execute("UPDATE portal_content SET payload=? WHERE id=1",(json.dumps(config),))
            db.execute("""INSERT INTO lunch_contacts VALUES(?,?,?,?,?) ON CONFLICT(id)
                DO UPDATE SET label=excluded.label,email=excluded.email,active=excluded.active""",
                (identity,label,email,int(active),now_iso()))
            self.auth.audit(db,user["id"],"contact.saved",identity)
            return {"id":identity}
        return self.store.mutate(key,"contact:"+str(cid),p,operation)

    def validate_request(self, payload):
        p=object_payload(payload)
        allowed={"preferred_name","email","grade","preferred_date","lunch_period","support","details","preferred_buddy","consent","website"}
        if set(p)-allowed: raise APIError("Unknown form field. Do not submit recipient email lists.")
        if p.get("website"): raise APIError("Please leave the website field empty.")
        if p.get("consent") is not True:
            raise APIError("Confirm that this is your own request and that the PEAC team may use these details to respond.")
        grade=p.get("grade","unassigned")
        if not isinstance(grade,str) or grade not in {"6","7","8","unassigned"}: raise APIError("Select a listed grade or Prefer not to say.")
        day=p.get("preferred_date", "")
        if not isinstance(day,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day): raise APIError("Choose a preferred lunch date.")
        try: parsed=date.fromisoformat(day)
        except ValueError: raise APIError("Choose a valid lunch date.")
        if not self.today_fn()<=parsed<=self.today_fn()+timedelta(days=90): raise APIError("Choose today or a date in the next 90 days.")
        if not isinstance(p.get("support"),str) or p.get("support") not in SUPPORTS: raise APIError("Choose one of the listed Lunch Buddies options.")
        return {"preferred_name":text(p.get("preferred_name",""),"preferred name",60,True),
                "email":email_address(p.get("email","")),"grade":grade,"preferred_date":day,
                "lunch_period":text(p.get("lunch_period",""),"lunch period",60),
                "support":p["support"],"details":text(p.get("details",""),"details",500),
                "preferred_buddy":text(p.get("preferred_buddy",""),"preferred lunch buddy",80)}

    def submit_lunch(self, payload, key, peer):
        cleaned=self.validate_request(payload)
        if not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}",key):
            raise APIError("Missing request key. Reload the form.")
        digest=hashlib.sha256(key.encode()).hexdigest()
        fingerprint=hashlib.sha256(json.dumps(cleaned,sort_keys=True).encode()).hexdigest()
        with self.store.connection() as db:
            old=db.execute("SELECT * FROM lunch_receipts WHERE key_hash=?",(digest,)).fetchone()
        if old:
            if old["fingerprint"]!=fingerprint: raise APIError("This request key belongs to a different submission. Do not submit again until its outcome is checked.",409)
            return {"ok":True,"reference":old["reference"],"replayed":True,"message":"Your request was already received. No second request was created."}
        self.auth.rate_limit("lunch-ip:"+peer,10,900)
        self.auth.rate_limit("lunch-email:"+cleaned["email"].lower(),3,3600)
        self.auth.rate_limit("lunch-global",200,3600)
        identity,ref,stamp=str(uuid.uuid4()),"LB-"+secrets.token_hex(6).upper(),now_iso()
        with self.store.transaction() as db:
            old=db.execute("SELECT * FROM lunch_receipts WHERE key_hash=?",(digest,)).fetchone()
            if old:
                if old["fingerprint"]!=fingerprint: raise APIError("Request key conflict.",409)
                return {"ok":True,"reference":old["reference"],"replayed":True,"message":"Already received. No duplicate was created."}
            config=json.loads(db.execute("SELECT payload FROM portal_content WHERE id=1").fetchone()[0])
            if not config["lunch_enabled"]: raise APIError("Lunch Buddies requests are currently paused. Please contact your school PEAC coordinator.",503)
            ids=config["default_contact_ids"]
            if not ids: raise APIError("No coordinator is configured. Requests are paused.",503)
            self.check_contacts(db,ids)
            db.execute("""INSERT INTO lunch_requests
                (id,reference,preferred_name,email,grade,preferred_date,lunch_period,support,details,status,staff_note,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,'new','',?,?)""",
                (identity,ref,*[cleaned[k] for k in ("preferred_name","email","grade","preferred_date","lunch_period","support","details")],stamp,stamp))
            requested_buddy=cleaned.get("preferred_buddy","")
            if requested_buddy:
                matched_user_id=self._match_buddy_account(db,requested_buddy)
                db.execute("INSERT INTO lunch_buddy_preferences(request_id,requested_name,matched_user_id) VALUES(?,?,?)",
                           (identity,requested_buddy,matched_user_id))
                if matched_user_id:
                    db.execute("""INSERT INTO portal_notifications
                        (id,user_id,kind,title,body,href,created_at,read_at) VALUES(?,?,?,?,?,?,?,'')""",
                        (str(uuid.uuid4()),matched_user_id,"lunch_buddy","Lunch Buddy request",
                         "A Lunch Buddies request named you as a preferred buddy. Open Lunch Buddies to review the request.",
                         "/console#lunch",stamp))
            self.queue_contacts(db,identity,ids)
            db.execute("INSERT INTO lunch_receipts VALUES(?,?,?,?)",(digest,fingerprint,ref,stamp))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            self.auth.audit(db,"public","lunch.received",identity)
        return {"ok":True,"reference":ref,"replayed":False,"message":"Saved to the PEAC request queue. This is not an appointment or email-delivery confirmation."}

    @staticmethod
    def queue_contacts(db,rid,ids):
        for cid in ids:
            contact=db.execute("SELECT email FROM lunch_contacts WHERE id=? AND active=1",(cid,)).fetchone()
            if not contact: raise APIError("A selected contact is unavailable.",409)
            stamp=now_iso()
            db.execute("""INSERT OR IGNORE INTO lunch_outbox
                (id,request_id,contact_id,recipient,status,created_at,updated_at) VALUES(?,?,?,?,'queued',?,?)""",
                (str(uuid.uuid4()),rid,cid,contact[0],stamp,stamp))

    def lunch_queue(self,full=False):
        with self.store.connection() as db:
            db.execute("BEGIN")
            requests=[dict(r) for r in db.execute("SELECT * FROM lunch_requests ORDER BY created_at DESC"+("" if full else " LIMIT 2000"))]
            preferences={r["request_id"]:dict(r) for r in db.execute("SELECT request_id,requested_name,matched_user_id FROM lunch_buddy_preferences")}
            for request in requests:
                pref=preferences.get(request["id"],{})
                request["preferred_buddy"]=pref.get("requested_name","")
                request["matched_buddy_user_id"]=pref.get("matched_user_id","")
            outbox=[dict(r) for r in db.execute("""SELECT o.*,r.reference,c.label FROM lunch_outbox o
                JOIN lunch_requests r ON r.id=o.request_id JOIN lunch_contacts c ON c.id=o.contact_id ORDER BY o.created_at DESC"""+("" if full else " LIMIT 4000"))]
            total=db.execute("SELECT COUNT(*) FROM lunch_requests").fetchone()[0]
            outbox_total=db.execute("SELECT COUNT(*) FROM lunch_outbox").fetchone()[0]
        counts={s:0 for s in STATES}
        with self.store.connection() as db:
            for row in db.execute("SELECT status,COUNT(*) n FROM lunch_requests GROUP BY status"): counts[row["status"]]=row["n"]
        return {"requests":requests,"outbox":outbox,"counts":counts,"total":total,"truncated":total>len(requests) or outbox_total>len(outbox),"outbox_total":outbox_total,"contacts":self.contacts()}

    def update_lunch(self,rid,payload,key,user):
        p=object_payload(payload)
        if set(p)-{"status","staff_note","version"}: raise APIError("Unknown request field.")
        if not isinstance(p.get("status"),str) or p.get("status") not in STATES: raise APIError("Choose a valid request status.")
        if type(p.get("version")) is not int: raise APIError("Current version is required.")
        note=text(p.get("staff_note",""),"staff note",1000)
        def update(db):
            row=db.execute("SELECT version FROM lunch_requests WHERE id=?",(rid,)).fetchone()
            if not row: raise APIError("Request not found.",404)
            if row[0]!=p["version"]: raise APIError("Another coordinator changed this request. Reload before saving.",409)
            db.execute("UPDATE lunch_requests SET status=?,staff_note=?,updated_at=?,version=version+1 WHERE id=?",
                       (p["status"],note,now_iso(),rid))
            self.auth.audit(db,user["id"],"lunch.updated",rid)
            return {"id":rid,"version":row[0]+1}
        return self.store.mutate(key,"lunch:"+rid,p,update)

    def route_lunch(self,rid,payload,key,user):
        p=object_payload(payload); ids=p.get("contact_ids")
        if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not isinstance(i,str) for i in ids):
            raise APIError("Choose 1 to 10 saved contacts.")
        def route(db):
            if not db.execute("SELECT 1 FROM lunch_requests WHERE id=?",(rid,)).fetchone(): raise APIError("Request not found.",404)
            self.check_contacts(db,ids); self.queue_contacts(db,rid,ids)
            self.auth.audit(db,user["id"],"lunch.routed",rid)
            return {"id":rid,"queued":True}
        return self.store.mutate(key,"route:"+rid,p,route)

    def purge(self,payload,user):
        require_admin(user); p=object_payload(payload)
        days=p.get("days",90)
        if type(days) is not int or not 30<=days<=3650: raise APIError("Retention days must be between 30 and 3650.")
        cutoff=(self.today_fn()-timedelta(days=days)).isoformat()
        where="status IN ('completed','cancelled') AND substr(updated_at,1,10) < ?"
        if p.get("confirm")!="PURGE CLOSED REQUESTS":
            with self.store.connection() as db: n=db.execute("SELECT COUNT(*) FROM lunch_requests WHERE "+where,(cutoff,)).fetchone()[0]
            return {"eligible":n,"before":cutoff,"deleted":False}
        with self.store.transaction() as db:
            n=db.execute("DELETE FROM lunch_requests WHERE "+where,(cutoff,)).rowcount
            db.execute("DELETE FROM lunch_receipts WHERE substr(created_at,1,10) < ?",(cutoff,))
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            self.auth.audit(db,user["id"],"lunch.purged",str(n))
        return {"deleted":n,"backup_notice":"Existing backups are not deleted. Apply your school retention policy to backups too."}

    def private_dispatch(self,method,path,payload,key,user):
        # Authentication is mandatory in both HTTP transports before this entry.
        if not user: raise APIError("Sign in to the PEAC console.",401)
        if path in {"/api/export","/api/backup.sqlite3","/api/portal/export"} or (method=="DELETE" and path=="/api/compliments") or (path=="/api/compliments/bulk" and isinstance(payload,dict) and payload.get("replace")):
            require_admin(user)
        if path=="/api/portal/notifications" and method=="GET":
            return self.notifications(user),200
        if path=="/api/portal/notifications/read" and method=="POST":
            return self.mark_notifications_read(user),200
        if path=="/api/portal/summary" and method=="GET":
            with self.store.connection() as db:
                total=db.execute("SELECT COUNT(*) FROM lunch_requests").fetchone()[0]
                new=db.execute("SELECT COUNT(*) FROM lunch_requests WHERE status='new'").fetchone()[0]
            return {"lunch_total":total,"lunch_new":new},200
        if path=="/api/portal/content":
            if method=="GET": require_admin(user); return self.content(),200
            if method=="PUT": return self.save_content(payload,key,user),200
        if path=="/api/portal/contacts":
            if method=="GET": return self.contacts(),200
            if method=="POST": return self.save_contact(payload,key,user),201
        match=re.fullmatch(r"/api/portal/contacts/([a-f0-9-]{36})",path)
        if match and method=="PUT": return self.save_contact(payload,key,user,match[1]),200
        if path=="/api/portal/compliment-people":
            from peac_people import list_people, save_person
            if method=="GET": return list_people(self),200
            if method=="POST": return save_person(self,payload,key,user),201
        if path=="/api/portal/compliment-people/batch" and method=="POST":
            from peac_people import save_people_batch
            return save_people_batch(self,payload,key,user),200
        match=re.fullmatch(r"/api/portal/compliment-people/([a-f0-9-]{36})",path)
        if match and method=="DELETE":
            from peac_people import delete_person
            return delete_person(self,match[1],payload,key,user),200
        if path=="/api/portal/lunch" and method=="GET": return self.lunch_queue(),200
        match=re.fullmatch(r"/api/portal/lunch/([a-f0-9-]{36})(/route)?",path)
        if match:
            if match[2] and method=="POST": return self.route_lunch(match[1],payload,key,user),200
            if not match[2] and method=="PUT": return self.update_lunch(match[1],payload,key,user),200
        if path=="/api/portal/purge" and method=="POST": return self.purge(payload,user),200
        if path=="/api/portal/users":
            require_admin(user)
            if method=="GET": return self.auth.users(),200
            if method=="POST": return self.auth.create_user(payload,user["id"]),201
        if path=="/api/portal/signup-requests":
            require_admin(user)
            if method=="GET": return self.auth.signup_requests(),200
        signup_match=re.fullmatch(r"/api/portal/signup-requests/([a-f0-9]{32})/(approve|reject)",path)
        if signup_match and method=="POST":
            require_admin(user)
            if signup_match[2]=="approve": return self.auth.approve_signup(signup_match[1],user["id"]),200
            return self.auth.reject_signup(signup_match[1],user["id"]),200
        match=re.fullmatch(r"/api/portal/users/([a-f0-9]{32})",path)
        if match and method=="DELETE": require_admin(user); return self.auth.disable(match[1],user["id"]),200
        if path=="/api/portal/password" and method=="POST":
            self.auth.rate_limit("password:"+user["id"],6,900)
            return self.auth.change_password(user,payload),200
        if path=="/api/portal/audit" and method=="GET":
            require_admin(user)
            with self.store.connection() as db: return [dict(r) for r in db.execute("SELECT * FROM portal_audit ORDER BY created_at DESC LIMIT 200")],200
        if path.startswith("/api/portal/assistant") or path.startswith("/api/portal/knowledge"):
            from peac_assistant import assistant_dispatch
            return assistant_dispatch(self,method,path,payload,key,user)
        if path.startswith("/api/portal/mail"):
            from peac_mail import mail_dispatch
            return mail_dispatch(self,method,path,payload,key,user)
        if path=="/api/portal/export" and method=="GET":
            data={"format":"peac-community-v3","exported_at":now_iso(),"analytics":self.store.snapshot(),"content":self.content(),"lunch":self.lunch_queue(full=True)}
            with self.store.connection() as db:
                data["knowledge"]=[dict(r) for r in db.execute("SELECT * FROM assistant_knowledge")]
                data["feedback"]=[dict(r) for r in db.execute("SELECT * FROM assistant_feedback")]
                data["named_compliments"]=[dict(r) for r in db.execute(
                    """SELECT p.entry_id AS id,p.person_name AS name,e.date AS week_start,e.grade,e.count,e.trash_count,
                              COALESCE(n.note,'') AS note,p.created_at,p.created_by
                       FROM compliment_people p JOIN entries e ON e.id=p.entry_id
                       LEFT JOIN notes n ON n.entry_id=e.id ORDER BY e.date,p.person_name"""
                )]
            return data,200
        return super().dispatch(method,path,payload,key)
