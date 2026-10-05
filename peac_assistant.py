"""PEAC Assistant: free, grounded retrieval over approved PEAC records.
Deterministic retrieval, not model training.
No prompts or student payloads are sent to a remote AI service. User questions
are not saved: only intent, source IDs, and explicit feedback are retained.
"""
from __future__ import annotations
import json
import re
import uuid
from datetime import date,timedelta,datetime,time as dt_time,timezone
from peac_core import APIError, object_payload, text, now_iso, monday, TZ
from portal_auth import require_admin


def tokens(s):
    stop={"the","a","an","what","which","how","is","are","our","peac","in","of","to","and","can","you","me","tell","about","please","do","does"}
    return {w for w in re.findall(r"[a-z0-9]+",s.lower()) if w not in stop and len(w)>1}


def answer_question(service,question,user):
    q=text(question,"question",800,True); lower=q.lower(); now=service.today_fn(); start=None; end=now
    requested_range=False
    dates=re.findall(r"\b\d{4}-\d{2}-\d{2}\b",lower)
    if dates:
        try: start=date.fromisoformat(dates[0]);end=date.fromisoformat(dates[-1])
        except ValueError: raise APIError("Use valid dates in YYYY-MM-DD format.")
        if start>end: raise APIError("Start date must be before end date.")
        if not date(2000,1,1)<=start<=end<=now: raise APIError("Choose recorded dates from 2000-01-01 through today.")
        requested_range=True
    elif "last month" in lower:
        end=now.replace(day=1)-timedelta(days=1);start=end.replace(day=1);requested_range=True
    elif "this month" in lower: start=now.replace(day=1);requested_range=True
    elif "last week" in lower: start=monday(now)-timedelta(days=7);end=start+timedelta(days=6);requested_range=True
    elif "this week" in lower: start=monday(now);requested_range=True
    elif "today" in lower: start=now;requested_range=True
    else:
        m=re.search(r"last\s+(\d+)\s+days",lower)
        if m:
            days=int(m[1])
            if not 1<=days<=3650: raise APIError("Choose a range of 1 to 3650 days.")
            start=now-timedelta(days=days-1);requested_range=True
    period=f"{start.isoformat()} through {end.isoformat()}" if start else "all saved history"
    snap=service.store.snapshot();rows=[r for r in snap["entries"] if (not start or r["date"]>=start.isoformat()) and (not requested_range or r["date"]<=end.isoformat())]
    n=sum(r["count"] for r in rows);trash=sum(r["trash_count"] for r in rows)
    sources=[];intent="help";lines=[]
    if any(t in lower for t in ["password","secret","token","smtp credential"]):
        lines=["I do not reveal passwords, session tokens, SMTP credentials, or contact directories. Use Settings for approved account and routing changes."]
        intent="restricted"
    elif "lunch" in lower or "buddies" in lower or re.search(r"lb-[a-f0-9]{12}",lower):
        intent="lunch";reference=re.search(r"lb-[a-f0-9]{12}",lower)
        with service.store.connection() as db:
            if reference:
                row=db.execute("SELECT reference,status,preferred_date FROM lunch_requests WHERE reference=?",(reference[0].upper(),)).fetchone()
                lines=[f"{row['reference']} is {row['status']}, with a preferred lunch date of {row['preferred_date']}." if row else "That request reference was not found."]
            else:
                sql="SELECT status,COUNT(*) n FROM lunch_requests";args=[]
                if start:
                    lower_utc=datetime.combine(start,dt_time.min,tzinfo=TZ).astimezone(timezone.utc).isoformat()
                    upper_utc=datetime.combine(end+timedelta(days=1),dt_time.min,tzinfo=TZ).astimezone(timezone.utc).isoformat()
                    sql+=" WHERE created_at>=? AND created_at<?";args=[lower_utc,upper_utc]
                result=list(db.execute(sql+" GROUP BY status",args));total=sum(r["n"] for r in result)
                lines=[f"There are {total:,} Lunch Buddies requests in {period}."]
                lines += [", ".join(f"{r['n']} {r['status']}" for r in result)+"." ] if result else []
            sources=[{"label":"Lunch Buddies queue","href":"/console#lunch","id":"lunch_requests"}]
        lines.append("A preferred date is not an appointment confirmation. Review individual details only in the restricted queue.")
    elif any(t in lower for t in ["forecast","predict","wave","model"]):
        intent="forecast";f=service.dashboard()["forecast"]
        lines=[f"The planning estimate for the week of {f['target_week']} is {f['prediction_rounded']:,} verified compliments using {f['model']}." if f.get("ready") else f["reason"]]
        if f.get("ready"):
            lines.append(f"Validation uses {f['evaluation_points']} held-out observations. This is not a calibrated probability or accuracy percentage.")
            if f.get("stale"): lines.append("This forecast is stale. Update and review completed weeks first.")
        if requested_range: lines.append("Forecasts use complete calendar-week history, not the requested chart date filter.")
        sources=[{"label":"Forecast and completed weeks","href":"/console#reports","id":"forecast"}]
    elif "note" in lower:
        intent="notes";terms=tokens(q)-{"note","notes","find","search","show","recent","saved"}
        matching=[r for r in snap["notes"] if not terms or terms & tokens(r["note"])]
        if start: matching=[r for r in matching if start.isoformat()<=r["date"]<=end.isoformat()]
        lines=[f"Found {len(matching)} matching program notes in {period}. Recorded notes are user-entered text, not independently verified facts."]
        lines += [f"{r['date']}: {r['note'][:400]}" for r in matching[:4]]
        sources=[{"label":"Saved activity notes","href":"/console#reports","id":"notes"}]
    elif "campaign" in lower or "poster" in lower:
        intent="campaigns";items=snap["campaigns"]
        if start: items=[r for r in items if start.isoformat()<=r["date"]<=end.isoformat()]
        lines=[f"{len(items)} campaigns are recorded in {period}, with {sum(r['engagements'] for r in items):,} entered engagements."]
        if items:
            best=max(items,key=lambda r:r["compliments_attributed"])
            if best["compliments_attributed"]>0: lines.append(f"'{best['name']}' has the highest team-entered attribution: {best['compliments_attributed']:,} compliments.")
            else: lines.append("No positive compliment attribution is recorded, so I cannot name an effectiveness winner.")
        lines.append("Attribution does not establish causation and does not add to verified totals.")
        sources=[{"label":"Campaign tracker","href":"/console#reports","id":"campaigns"}]
    elif any(t in lower for t in ["compliment","count","grade","trash","verified","trend","growth"]):
        intent="counts"
        if not rows: lines=[f"No counts are recorded for {period}. That is missing data, not proof that no compliments happened."]
        else:
            lines=[f"{n:,} verified compliments and {trash:,} trash compliments are recorded in {period}, across {len(set(r['date'] for r in rows))} recorded dates."]
            grade=re.search(r"\b([678])(?:th)?\s+grade\b|\bgrade\s+([678])\b",lower)
            if grade:
                g=grade[1] or grade[2];filtered=[r for r in rows if r["grade"]==g]
                lines.append(f"Grade {g}: {sum(r['count'] for r in filtered):,} recorded verified compliments. Unassigned counts are not assigned to a grade.")
            elif "grade" in lower:
                lines.append("Grade totals: "+", ".join(f"{g}: {sum(r['count'] for r in rows if r['grade']==g):,}" for g in ("6","7","8","unassigned"))+".")
            if "growth" in lower or "trend" in lower:
                w=service.dashboard()["compliments"]
                if requested_range: lines.append("The completed-week comparison below uses the latest adjacent completed weeks, independently of your requested date range.")
                lines.append(f"Completed-week change: {w['change']:+,} compliments." if w["change"] is not None else "Two adjacent completed weeks are needed for a completed-week change.")
            lines.append("Unrecorded dates remain unknown. These are recorded totals, not a count of unique students.")
        sources=[{"label":"Verified count records","href":"/console#reports","id":"entries"}]
    else:
        candidates=[];terms=tokens(q)
        with service.store.connection() as db:
            for row in db.execute("SELECT * FROM assistant_knowledge WHERE approved=1"):
                match=len(terms & tokens(row["question"]))
                if match: candidates.append((match/max(1,len(terms)),dict(row)))
        if candidates and max(c[0] for c in candidates)>=.35:
            row=max(candidates,key=lambda c:c[0])[1];lines=[row["answer"]];intent="approved_faq"
            sources=[{"label":"Admin-approved FAQ","href":"/console#assistant","id":row["id"]}]
        elif any(t in lower for t in ["assistant", "who are you", "what can you do"]):
            lines=["I am PEAC Assistant. I can summarize saved counts, program notes, campaigns, forecasts, Lunch Buddies status, and administrator-approved FAQs. I do not train automatically on student submissions or invent missing data."];intent="about"
        elif "about" in lower or "peac" in lower:
            lines=[service.content()["about"] or "The PEAC team has not added its About text yet. An administrator can write it in Website settings."];intent="about"
            sources=[{"label":"Published About text","href":"/console#website","id":"public_about"}]
        else:
            lines=["I do not have a grounded answer to that yet. Ask about compliment totals, grades, campaigns, notes, the forecast, Lunch Buddies, or an approved FAQ. Try: 'How many verified compliments this month?' or 'Find notes about posters'."]
    turn=str(uuid.uuid4())
    with service.store.transaction() as db:
        db.execute("INSERT INTO assistant_turns VALUES(?,?,?,?,?)",(turn,user["id"],intent,json.dumps([s["id"] for s in sources]),now_iso()))
    return {"id":turn,"answer":"\n\n".join(lines),"sources":sources,"mode":"grounded_local_retrieval",
            "intent":intent,"period":period,"as_of":now_iso(),"notice":"Computed facts and approved knowledge. No paid AI, no automatic model training. Questions are not saved."}


def assistant_dispatch(service,method,path,payload,key,user):
    if path=="/api/portal/assistant/ask" and method=="POST":
        service.auth.rate_limit("assistant:"+user["id"],40,60)
        return answer_question(service,object_payload(payload).get("question"),user),200
    if path=="/api/portal/assistant/feedback" and method=="POST":
        p=object_payload(payload);rating=p.get("rating");tid=p.get("turn_id")
        if not isinstance(rating,str) or rating not in {"helpful","needs_work"}: raise APIError("Choose helpful or needs_work.")
        suggestion=text(p.get("suggestion",""),"suggestion",600)
        with service.store.transaction() as db:
            if not db.execute("SELECT 1 FROM assistant_turns WHERE id=? AND user_id=?",(tid,user["id"])).fetchone(): raise APIError("Your answer was not found.",404)
            db.execute("""INSERT INTO assistant_feedback VALUES(?,?,?,?,?,?) ON CONFLICT(turn_id,user_id)
                DO UPDATE SET rating=excluded.rating,suggestion=excluded.suggestion""",
                (str(uuid.uuid4()),tid,user["id"],rating,suggestion,now_iso()))
        return {"ok":True,"notice":"Feedback saved for administrator review, not automatically used as knowledge."},200
    if path=="/api/portal/assistant/usage" and method=="GET":
        require_admin(user)
        with service.store.connection() as db:
            return {"intents":[dict(r) for r in db.execute("SELECT intent,COUNT(*) uses FROM assistant_turns GROUP BY intent ORDER BY uses DESC")],
                    "feedback":[dict(r) for r in db.execute("SELECT rating,suggestion,created_at FROM assistant_feedback ORDER BY created_at DESC LIMIT 100")]},200
    if path=="/api/portal/knowledge":
        if method=="GET":
            require_admin(user)
            with service.store.connection() as db: return [dict(r) for r in db.execute("SELECT * FROM assistant_knowledge ORDER BY created_at DESC")],200
        if method=="POST":
            require_admin(user);p=object_payload(payload)
            question=text(p.get("question",""),"FAQ question",300,True);answer=text(p.get("answer",""),"FAQ answer",2000,True)
            if type(p.get("approved",False)) is not bool: raise APIError("approved must be true or false.")
            identity=str(uuid.uuid4())
            def add(db):
                db.execute("INSERT INTO assistant_knowledge VALUES(?,?,?,?,?,?)",(identity,question,answer,int(p.get("approved",False)),now_iso(),now_iso()))
                service.auth.audit(db,user["id"],"knowledge.created",identity)
                return {"id":identity}
            return service.store.mutate(key,"knowledge",p,add),201
    match=re.fullmatch(r"/api/portal/knowledge/([a-f0-9-]{36})",path)
    if match and method=="DELETE":
        require_admin(user)
        def delete(db):
            db.execute("DELETE FROM assistant_knowledge WHERE id=?",(match[1],))
            service.auth.audit(db,user["id"],"knowledge.deleted",match[1]);return {"deleted":True}
        return service.store.mutate(key,path,object_payload(payload),delete),200
    raise APIError("Assistant endpoint not found.",404)
