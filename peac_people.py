"""Private named weekly compliment logging for PEAC staff.

Names are never exposed by public endpoints or PEAC Assistant. Each named row also
creates an ordinary aggregate entry so existing dashboards/charts keep working.
"""
from __future__ import annotations

from datetime import date
import re

from peac_core import APIError, count, monday, now_iso, object_payload, recorded_date, text

ALLOWED_GRADES = {"6", "7", "8", "unassigned"}


def _week_start(value, today: date) -> str:
    day = recorded_date(value, today)
    parsed = date.fromisoformat(day)
    if monday(parsed) != parsed:
        raise APIError("Week start must be a Monday.")
    return day


def validate_person_record(payload, today: date) -> dict:
    p = object_payload(payload)
    allowed = {"name", "date", "week", "week_start", "grade", "count", "trash_count", "note"}
    if set(p) - allowed:
        raise APIError("Unknown named-log field.")
    supplied = [p.get(k) for k in ("date", "week", "week_start") if p.get(k) not in (None, "")]
    if not supplied:
        raise APIError("Week start is required.")
    if len({str(v) for v in supplied}) != 1:
        raise APIError("date, week, and week_start disagree.")
    grade = str(p.get("grade", "unassigned")).strip().lower().replace("th grade", "").replace("grade ", "")
    if grade not in ALLOWED_GRADES:
        raise APIError("Choose grade 6, 7, 8, or unassigned.")
    return {
        "name": text(p.get("name", ""), "student name", 120, True),
        "date": _week_start(str(supplied[0]), today),
        "grade": grade,
        "count": count(p.get("count"), "compliments"),
        "trash_count": count(p.get("trash_count", 0), "trash_count"),
        "note": text(p.get("note", ""), "note", 1000),
    }


def _key_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def list_people(service, limit: int = 5000) -> dict:
    if type(limit) is not int or not 1 <= limit <= 5000:
        raise APIError("Limit must be 1 to 5000.")
    with service.store.connection() as db:
        rows = [dict(r) for r in db.execute(
            """SELECT p.entry_id AS id,p.person_name AS name,e.date AS week_start,e.grade,
                      e.count,e.trash_count,COALESCE(n.note,'') AS note,p.created_at,p.created_by
               FROM compliment_people p
               JOIN entries e ON e.id=p.entry_id
               LEFT JOIN notes n ON n.entry_id=e.id
               ORDER BY e.date DESC, lower(p.person_name), p.entry_id
               LIMIT ?""", (limit,)
        )]
        total = db.execute("SELECT COUNT(*) FROM compliment_people").fetchone()[0]
        sums = db.execute(
            """SELECT COALESCE(SUM(e.count),0),COALESCE(SUM(e.trash_count),0),COUNT(DISTINCT lower(p.person_name))
               FROM compliment_people p JOIN entries e ON e.id=p.entry_id"""
        ).fetchone()
    return {
        "records": rows,
        "total_records": total,
        "total_compliments": int(sums[0]),
        "trash_total": int(sums[1]),
        "distinct_names": int(sums[2]),
        "truncated": total > len(rows),
        "privacy": "Private staff-only named records. Public pages and PEAC Assistant do not expose names.",
    }


def current_people_rows(service) -> list[dict]:
    with service.store.connection() as db:
        return [dict(r) for r in db.execute(
            """SELECT p.entry_id AS id,p.person_name AS name,e.date,e.grade,e.count,e.trash_count,
                      COALESCE(n.note,'') AS note
               FROM compliment_people p JOIN entries e ON e.id=p.entry_id
               LEFT JOIN notes n ON n.entry_id=e.id"""
        )]


def insert_person_entry(service, db, value: dict, actor: str) -> str:
    # One named total per person/week/grade. Import preview prevents duplicates;
    # single-entry save below updates the existing weekly row instead.
    entry = {k: value[k] for k in ("date", "grade", "count", "trash_count", "note")}
    identity = service.store.insert_entry(db, entry)
    db.execute(
        "INSERT INTO compliment_people(entry_id,person_name,created_at,created_by) VALUES(?,?,?,?)",
        (identity, value["name"], now_iso(), actor),
    )
    return identity


def _upsert_person_row(service, db, cleaned: dict, actor: str) -> dict:
    """Create or replace one person's weekly total inside an existing transaction."""
    row = db.execute(
        """SELECT p.entry_id FROM compliment_people p
           JOIN entries e ON e.id=p.entry_id
           WHERE lower(trim(p.person_name))=lower(trim(?)) AND e.date=? AND e.grade=?""",
        (cleaned["name"], cleaned["date"], cleaned["grade"]),
    ).fetchone()
    if row:
        entry_id = row[0]
        db.execute(
            "UPDATE entries SET count=?,trash_count=? WHERE id=?",
            (cleaned["count"], cleaned["trash_count"], entry_id),
        )
        db.execute("UPDATE compliment_people SET person_name=? WHERE entry_id=?", (cleaned["name"], entry_id))
        note_row = db.execute("SELECT id FROM notes WHERE entry_id=?", (entry_id,)).fetchone()
        if cleaned["note"]:
            if note_row:
                db.execute(
                    "UPDATE notes SET date=?,note=?,count=?,trash_count=?,grade=?,counts_reset=0 WHERE entry_id=?",
                    (cleaned["date"], cleaned["note"], cleaned["count"], cleaned["trash_count"], cleaned["grade"], entry_id),
                )
            else:
                import uuid
                db.execute(
                    "INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), entry_id, cleaned["date"], cleaned["note"], cleaned["count"], cleaned["trash_count"], cleaned["grade"], 0, now_iso()),
                )
        elif note_row:
            db.execute("DELETE FROM notes WHERE entry_id=?", (entry_id,))
        db.execute("DELETE FROM closed_weeks WHERE week=?", (cleaned["date"],))
        return {"id": entry_id, "updated": True}
    entry_id = insert_person_entry(service, db, cleaned, actor)
    db.execute("DELETE FROM closed_weeks WHERE week=?", (cleaned["date"],))
    return {"id": entry_id, "updated": False}


def save_person(service, payload, key: str, user: dict) -> dict:
    cleaned = validate_person_record(payload, service.today_fn())

    def operation(db):
        result = _upsert_person_row(service, db, cleaned, user["id"])
        service.auth.audit(db, user["id"], "compliment_person.updated" if result["updated"] else "compliment_person.created", result["id"])
        return result

    return service.store.mutate(key, "compliment-person", cleaned, operation)


def save_people_batch(service, payload, key: str, user: dict) -> dict:
    """Upsert up to 5,000 private student-week totals atomically.

    This powers Rapid List and Roster Week. It is intentionally *not* an increment
    endpoint: retrying the same student/week/grade replaces that weekly total.
    """
    p = object_payload(payload)
    if set(p) - {"records"}:
        raise APIError("Unknown bulk-log field.")
    records = p.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 5000:
        raise APIError("Send between 1 and 5,000 student-week rows.")
    cleaned = [validate_person_record(row, service.today_fn()) for row in records]
    seen = set()
    for row in cleaned:
        identity = (_key_name(row["name"]), row["date"], row["grade"])
        if identity in seen:
            raise APIError("The batch contains the same student, week, and grade more than once. Combine it before saving.")
        seen.add(identity)

    def operation(db):
        created = updated = 0
        ids = []
        for row in cleaned:
            result = _upsert_person_row(service, db, row, user["id"])
            ids.append(result["id"])
            if result["updated"]:
                updated += 1
            else:
                created += 1
        service.auth.audit(db, user["id"], "compliment_people.batch", f"created={created};updated={updated};rows={len(cleaned)}")
        return {"saved": len(cleaned), "created": created, "updated": updated, "ids": ids}

    return service.store.mutate(key, "compliment-people-batch", {"records": cleaned}, operation)

def delete_person(service, entry_id: str, payload, key: str, user: dict) -> dict:
    p = object_payload(payload)
    if set(p) - {"confirm"} or p.get("confirm") != "DELETE NAMED COMPLIMENT ROW":
        raise APIError("Deletion requires confirm='DELETE NAMED COMPLIMENT ROW'.")

    def operation(db):
        row = db.execute(
            "SELECT e.date FROM compliment_people p JOIN entries e ON e.id=p.entry_id WHERE p.entry_id=?",
            (entry_id,),
        ).fetchone()
        if not row:
            raise APIError("Named compliment row not found.", 404)
        # FK cascade removes compliment_people and note row remains explicitly removed.
        db.execute("DELETE FROM notes WHERE entry_id=?", (entry_id,))
        db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        db.execute("DELETE FROM closed_weeks WHERE week=?", (row[0],))
        service.auth.audit(db, user["id"], "compliment_person.deleted", entry_id)
        return {"deleted": entry_id}

    return service.store.mutate(key, "compliment-person-delete:" + entry_id, p, operation)
