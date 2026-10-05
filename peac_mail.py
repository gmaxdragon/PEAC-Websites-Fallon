"""Opt-in SMTP notifications. No background sends, student details, or blind retries."""
from __future__ import annotations
import json
import os
import re
import smtplib
import ssl
from datetime import datetime,timezone
from email.message import EmailMessage
from email.policy import SMTP
from peac_core import APIError, now_iso, object_payload
from portal_auth import require_admin
from peac_community import email_address


def mail_config():
    return {"enabled":os.getenv("PEAC_SMTP_ENABLED","0")=="1", "host":os.getenv("PEAC_SMTP_HOST",""),
            "port":os.getenv("PEAC_SMTP_PORT","465"), "mode":os.getenv("PEAC_SMTP_MODE","ssl"),
            "username":os.getenv("PEAC_SMTP_USERNAME",""),"password":os.getenv("PEAC_SMTP_PASSWORD",""),
            "sender":os.getenv("PEAC_SMTP_FROM","")}


def safe_message(job,sender=""):
    msg=EmailMessage(policy=SMTP)
    if sender: msg["From"]=email_address(sender)
    msg["To"]=email_address(job["recipient"])
    msg["Subject"]="PEAC Lunch Buddies: a request needs review"
    # Stable ID identifies retry ambiguity. It is not a delivery guarantee.
    msg["Message-ID"]=f"<peac-{job['id']}@notifications.invalid>"
    msg["X-Unsent"]="1"
    msg.set_content(f"A Lunch Buddies request is ready for the PEAC team.\n\nReference: {job['reference']}\n\nOpen your PEAC console and review Lunch Buddies. This notification deliberately contains no student name, email, or request details.\n\nA request is not a confirmed lunch appointment.\n")
    return msg


def get_job(service,identity):
    with service.store.connection() as db:
        row=db.execute("""SELECT o.*,r.reference FROM lunch_outbox o
            JOIN lunch_requests r ON r.id=o.request_id WHERE o.id=?""",(identity,)).fetchone()
    if not row: raise APIError("Notification not found.",404)
    return dict(row)


def send_notification(service,identity,user):
    require_admin(user)
    cfg=mail_config()
    if not cfg["enabled"]: raise APIError("Email sending is off. Use Download email draft, or configure an approved SMTP account.",503)
    if not cfg["host"] or not cfg["username"] or not cfg["password"] or not cfg["sender"] or cfg["mode"] not in {"ssl","starttls"}:
        raise APIError("SMTP configuration is incomplete. Nothing was sent.",503)
    try: port=int(cfg["port"])
    except ValueError: raise APIError("Invalid SMTP port.",503)
    if not 1<=port<=65535: raise APIError("Invalid SMTP port.",503)
    sender=email_address(cfg["sender"])
    job=get_job(service,identity)
    with service.store.transaction() as db:
        row=db.execute("SELECT status,contact_id,recipient FROM lunch_outbox WHERE id=?",(identity,)).fetchone()
        if row["status"]!="queued":
            return {"ok":True,"status":row["status"],"message":"No new send attempted. Reconcile any uncertain prior attempt before retrying."}
        contact=db.execute("SELECT * FROM lunch_contacts WHERE id=? AND active=1",(row["contact_id"],)).fetchone()
        if not contact or contact["email"]!=row["recipient"]:
            raise APIError("Recipient changed or was disabled. Review this notification; it was not sent.",409)
        db.execute("UPDATE lunch_outbox SET status='sending',updated_at=? WHERE id=?",(now_iso(),identity))
        service.auth.audit(db,user["id"],"mail.attempted",identity)
    message=safe_message(job,sender)
    del message["X-Unsent"]
    try:
        context=ssl.create_default_context()
        if cfg["mode"]=="ssl":
            connection=smtplib.SMTP_SSL(cfg["host"],port,timeout=15,context=context)
        else:
            connection=smtplib.SMTP(cfg["host"],port,timeout=15)
            connection.ehlo(); connection.starttls(context=context); connection.ehlo()
        try:
            connection.login(cfg["username"],cfg["password"])
            refused=connection.send_message(message,from_addr=sender,to_addrs=[job["recipient"]])
            if refused: raise RuntimeError("Recipient was refused")
        finally:
            # QUIT failure after message acceptance should not cause a second email.
            try: connection.quit()
            except Exception: connection.close()
    except Exception as exc:
        with service.store.transaction() as db:
            db.execute("UPDATE lunch_outbox SET status='uncertain',error=?,updated_at=? WHERE id=?",
                (type(exc).__name__+": check provider logs before retrying",now_iso(),identity))
        return {"ok":False,"status":"uncertain","message":"Delivery outcome is unconfirmed. Check the SMTP provider logs before any retry."}
    with service.store.transaction() as db:
        db.execute("UPDATE lunch_outbox SET status='accepted',error='',updated_at=? WHERE id=?",(now_iso(),identity))
        service.auth.audit(db,user["id"],"mail.smtp_accepted",identity)
    return {"ok":True,"status":"accepted","message":"SMTP server accepted the notification. Inbox delivery or reading is not confirmed."}


def mail_dispatch(service,method,path,payload,key,user):
    if path=="/api/portal/mail/status" and method=="GET":
        c=mail_config()
        return {"enabled":c["enabled"],"mode":"smtp" if c["enabled"] else "draft_only",
                "notice":"No automatic sends. A coordinator can download a draft; an admin can send explicitly after SMTP setup."},200
    match=re.fullmatch(r"/api/portal/mail/([a-f0-9-]{36})/(preview|send|resolve)",path)
    if not match: raise APIError("Mail endpoint not found.",404)
    identity,action=match.groups()
    if action=="preview" and method=="GET":
        job=get_job(service,identity);msg=safe_message(job)
        return {"to":job["recipient"],"subject":str(msg["Subject"]),"body":msg.get_content(),"status":job["status"]},200
    if method=="POST" and action=="send":
        require_admin(user);p=object_payload(payload)
        if p.get("confirm")!="SEND NOTIFICATION": raise APIError("Explicit notification confirmation is required.")
        return send_notification(service,identity,user),200
    if method=="POST" and action=="resolve":
        require_admin(user);p=object_payload(payload)
        mapping={"CONFIRMED NOT SENT":"queued","CONFIRMED SENT":"accepted","CANCEL NOTIFICATION":"cancelled"}
        new=mapping.get(p.get("confirm")) if isinstance(p.get("confirm"),str) else None
        if not new: raise APIError("Choose an explicit reconciliation outcome.")
        with service.store.transaction() as db:
            row=db.execute("SELECT status,updated_at FROM lunch_outbox WHERE id=?",(identity,)).fetchone()
            if not row: raise APIError("Notification not found.",404)
            if row[0]=="sending" and (datetime.now(timezone.utc)-datetime.fromisoformat(row[1])).total_seconds()<600:
                raise APIError("A send may still be running. Wait ten minutes and check provider logs before reconciling.",409)
            if row[0] not in {"sending","uncertain","queued"}: raise APIError("This notification has already been finalized.",409)
            db.execute("UPDATE lunch_outbox SET status=?,error='',updated_at=? WHERE id=?",(new,now_iso(),identity))
            service.auth.audit(db,user["id"],"mail.manually_reconciled."+new,identity)
        return {"ok":True,"status":new},200
    raise APIError("Mail method not supported.",404)
