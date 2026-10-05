"""Create a synthetic PEAC demo database without touching real data."""
from __future__ import annotations
import argparse
from datetime import date, timedelta
from pathlib import Path

from peac_community import CommunityService
from peac_core import monday, now_iso, normalize_campaign
from peac_people import insert_person_entry


def seed(path: Path):
    service = CommunityService(path, use_ml=False)
    with service.store.transaction() as db:
        if db.execute("SELECT 1 FROM entries LIMIT 1").fetchone():
            return False
        today = service.today_fn()
        latest = monday(today - timedelta(days=7))
        names = ["Student A", "Student B", "Student C", "Student D", "Student E", "Student F"]
        grades = ["8", "8", "7", "7", "6", "6"]
        for offset in range(7, -1, -1):
            start = latest - timedelta(days=7*offset)
            for i, (name, grade) in enumerate(zip(names, grades)):
                value = {
                    "name": name,
                    "date": start.isoformat(),
                    "grade": grade,
                    "count": max(0, 1 + ((offset + i*2) % 5)),
                    "trash_count": 0,
                    "note": "Synthetic demo record" if i == 0 else "",
                }
                insert_person_entry(service, db, value, "demo-seed")
            db.execute("INSERT OR REPLACE INTO closed_weeks VALUES(?,?)", (start.isoformat(), now_iso()))
        for idx, payload in enumerate([
            {"name":"Hallway kindness reminder","date":(latest-timedelta(days=18)).isoformat(),"type":"Poster","platform":"School","description":"Synthetic demo campaign","impressions":120,"engagements":18,"compliments_attributed":4},
            {"name":"Lunch kindness week","date":(latest-timedelta(days=4)).isoformat(),"type":"Activity","platform":"Lunch","description":"Synthetic demo campaign","impressions":80,"engagements":22,"compliments_attributed":6},
        ]):
            c=normalize_campaign(payload,today)
            db.execute("INSERT INTO campaigns VALUES(?,?)",(c["id"],__import__('json').dumps(c)))
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    return True


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='data/demo.sqlite3')
    args=p.parse_args()
    created=seed(Path(args.db))
    print('Synthetic demo data created.' if created else 'Demo database already contains records; keeping them unchanged.')

if __name__=='__main__': main()
