"""PEAC domain logic. Aggregate counts only. No student names or rosters.

Storage is deliberately separate from HTTP so the same logic can be tested
without a running Flask server. All mutating operations are SQLite transactions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import uuid
import warnings
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

TZ = ZoneInfo("America/Los_Angeles")
MAX_COUNT = 1_000_000
MAX_TOTAL = 1_000_000_000


class APIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_today() -> date:
    return datetime.now(TZ).date()


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def text(value: Any, field: str, limit: int = 1000, required: bool = False) -> str:
    if not isinstance(value, str):
        raise APIError(f"{field} must be text.")
    result = value.strip()
    if len(result) > limit or (required and not result):
        raise APIError(f"{field} must contain {'1' if required else '0'} to {limit} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in result):
        raise APIError(f"{field} contains unsupported control characters.")
    return result


def count(value: Any, field: str = "count") -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise APIError(f"{field} must be a whole number from 0 to {MAX_COUNT:,}.")
    return value


def recorded_date(value: Any, today: date) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise APIError("Use a real date in YYYY-MM-DD format.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise APIError("The selected date is not valid.") from exc
    if not date(2000, 1, 1) <= parsed <= today:
        raise APIError("Count dates must be between 2000-01-01 and today.")
    return parsed.isoformat()


def object_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise APIError("Send a JSON object, not a list or a scalar.")
    return payload


def validate_count_entry(payload: dict, today: date, require_note: bool = False) -> dict:
    object_payload(payload)
    allowed = {"date", "week", "count", "trash_count", "grade", "note"}
    if set(payload) - allowed:
        raise APIError("Unknown fields. Do not submit names, emails, or student records.")
    if "date" in payload and "week" in payload and payload["date"] != payload["week"]:
        raise APIError("date and week disagree.")
    day = recorded_date(payload.get("date", payload.get("week")), today)
    grade = payload.get("grade", "unassigned")
    if grade not in {"6", "7", "8", "unassigned"}:
        raise APIError("Choose grade 6, 7, 8, or unassigned.")
    return {
        "date": day, "count": count(payload.get("count")),
        "trash_count": count(payload.get("trash_count", 0), "trash_count"),
        "grade": grade,
        "note": text(payload.get("note", ""), "note", 2000, require_note),
    }


class Store:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, date TEXT NOT NULL,
                    count INTEGER NOT NULL CHECK(count >= 0),
                    trash_count INTEGER NOT NULL CHECK(trash_count >= 0),
                    grade TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entries_date ON entries(date);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, entry_id TEXT NOT NULL,
                    date TEXT NOT NULL, note TEXT NOT NULL,
                    count INTEGER NOT NULL, trash_count INTEGER NOT NULL,
                    grade TEXT NOT NULL, counts_reset INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS closed_weeks (
                    week TEXT PRIMARY KEY, closed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS import_batches (
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, dataset TEXT NOT NULL,
                    source TEXT NOT NULL, imported INTEGER NOT NULL, skipped INTEGER NOT NULL,
                    record_ids TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('revision', '0');
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def snapshot(self) -> dict:
        with self.connection() as db:
            db.execute("BEGIN")
            return {
                "entries": [dict(r) for r in db.execute("SELECT * FROM entries ORDER BY date, id")],
                "imports": [dict(r) for r in db.execute("SELECT id,fingerprint,dataset,source,imported,skipped,created_at FROM import_batches ORDER BY created_at DESC")],
                "notes": [dict(r) for r in db.execute("SELECT * FROM notes ORDER BY date DESC, created_at DESC")],
                "closed_weeks": [r[0] for r in db.execute("SELECT week FROM closed_weeks ORDER BY week")],
                "campaigns": [json.loads(r[0]) for r in db.execute("SELECT payload FROM campaigns ORDER BY id")],
                "revision": int(db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]),
            }

    def mutate(self, key: str, kind: str, payload: dict, operation) -> dict:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
            raise APIError("A unique Idempotency-Key header is required (16 to 100 letters/digits/hyphens).")
        fingerprint = hashlib.sha256(json.dumps([kind, payload], sort_keys=True, allow_nan=False).encode()).hexdigest()
        with self.transaction() as db:
            old = db.execute("SELECT * FROM receipts WHERE key=?", (key,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise APIError("This request key was already used for different data.", 409)
                return {**json.loads(old["result"]), "replayed": True}
            result = operation(db)
            db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
            revision = int(db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            result.update(ok=True, revision=revision, replayed=False)
            db.execute("INSERT INTO receipts VALUES(?,?,?,?)", (key, fingerprint, json.dumps(result), now_iso()))
            return result

    @staticmethod
    def insert_entry(db, value: dict) -> str:
        totals = db.execute("SELECT COALESCE(SUM(count),0),COALESCE(SUM(trash_count),0) FROM entries").fetchone()
        if totals[0] + value["count"] > MAX_TOTAL or totals[1] + value["trash_count"] > MAX_TOTAL:
            raise APIError("This dataset exceeds the supported aggregate-count limit.")
        identity, stamp = str(uuid.uuid4()), now_iso()
        db.execute("INSERT INTO entries VALUES(?,?,?,?,?,?)", (identity, value["date"], value["count"], value["trash_count"], value["grade"], stamp))
        if value["note"]:
            db.execute("INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?)", (
                str(uuid.uuid4()), identity, value["date"], value["note"], value["count"],
                value["trash_count"], value["grade"], 0, stamp,
            ))
        # Any correction/addition reopens the week for explicit review.
        db.execute("DELETE FROM closed_weeks WHERE week=?", (monday(date.fromisoformat(value["date"])).isoformat(),))
        return identity


def daily_rows(entries: list[dict]) -> list[dict]:
    result = {}
    for row in entries:
        target = result.setdefault(row["date"], {"week": row["date"], "count": 0, "trash_count": 0})
        target["count"] += row["count"]
        target["trash_count"] += row["trash_count"]
    return sorted(result.values(), key=lambda r: r["week"])


def weekly_rows(snapshot: dict, today: date) -> list[dict]:
    result = {}
    for entry in snapshot["entries"]:
        start = monday(date.fromisoformat(entry["date"])).isoformat()
        row = result.setdefault(start, {"week": start, "count": 0, "trash_count": 0})
        row["count"] += entry["count"]
        row["trash_count"] += entry["trash_count"]
    for start, row in result.items():
        end = date.fromisoformat(start) + timedelta(days=6)
        row.update(end=end.isoformat(), ended=end < today,
                   complete=start in snapshot["closed_weeks"] and end < today)
    return sorted(result.values(), key=lambda r: r["week"])


def baseline(values: list[int], method: str) -> float:
    a, b, c = map(float, values[-3:])
    if method == "last_week":
        return c
    if method == "weighted_recent":
        return .15*a + .30*b + .55*c
    if method == "mean3":
        return (a+b+c)/3
    if method == "linear_trend":
        return max(0., (a+b+c)/3 + (c-a))
    raise ValueError(method)


def feature_vector(values) -> np.ndarray:
    arr = np.asarray(list(values), dtype=float)
    if arr.shape != (3,) or not np.all(np.isfinite(arr)):
        raise ValueError("Expected exactly three finite counts.")
    a, b, c = arr
    return np.array([a,b,c,np.mean(arr),np.std(arr),b-a,c-b,(c-a)/2,c-2*b+a])


def learned_prediction(counts: list[int], method: str) -> float:
    from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    builders = {
        "ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "neural_net": lambda: make_pipeline(StandardScaler(), MLPRegressor(
            hidden_layer_sizes=(8,), solver="lbfgs", alpha=.2, max_iter=800, random_state=42)),
        "random_forest": lambda: RandomForestRegressor(n_estimators=60, max_depth=4, min_samples_leaf=2, random_state=42),
        "extra_trees": lambda: ExtraTreesRegressor(n_estimators=60, max_depth=4, min_samples_leaf=2, random_state=42),
    }
    X = np.vstack([feature_vector(counts[i-3:i]) for i in range(3,len(counts))])
    y = np.asarray(counts[3:], dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model = builders[method]()
        model.fit(X, y)
        result = float(model.predict(feature_vector(counts[-3:]).reshape(1,-1))[0])
    if not math.isfinite(result):
        raise ValueError("Model returned a non-finite prediction.")
    return max(0., result)


@lru_cache(maxsize=32)
def model_forecast(points: tuple, use_ml: bool) -> dict:
    labels, values = zip(*points)
    counts = list(values)
    n = len(counts)
    methods = ["last_week", "weighted_recent", "linear_trend", "mean3"]
    excluded = []
    # Each candidate sees identical chronological folds. Hold out the final two
    # points from model selection. No trained model sees its target or future rows.
    origins = list(range(max(3, n-8), n))
    eligible_ml = use_ml and n >= 16
    if eligible_ml:
        methods += ["ridge", "neural_net", "random_forest", "extra_trees"]
    predict = lambda xs, name: baseline(xs, name) if name in methods[:4] else learned_prediction(xs, name)
    scores = {}
    if len(origins) >= 6:
        selection_indices = origins[:-2]
        for method in methods:
            try:
                errors = [counts[i]-predict(counts[:i], method) for i in selection_indices]
                scores[method] = float(np.mean(np.abs(errors)))
            except (ImportError, ValueError, RuntimeError, Warning, ArithmeticError) as exc:
                excluded.append(f"{method}: {type(exc).__name__}")
        chosen = min(scores, key=scores.get)
        validation_indices = origins[-2:]
        selection_n = len(selection_indices)
    else:
        chosen = "weighted_recent"
        validation_indices = origins
        selection_n = 0
    try:
        prediction = predict(counts, chosen)
        backtest = [{"week":labels[i], "actual":counts[i], "predicted":round(predict(counts[:i], chosen),2)} for i in validation_indices]
    except (ImportError, ValueError, RuntimeError, Warning, ArithmeticError) as exc:
        excluded.append(f"Final {chosen}: {type(exc).__name__}; reverted to fixed weighted baseline")
        chosen = "weighted_recent"
        prediction = baseline(counts, chosen)
        backtest = [{"week":labels[i], "actual":counts[i], "predicted":round(baseline(counts[:i],chosen),2)} for i in origins]
        selection_n = 0
    for row in backtest:
        row["error"] = round(row["actual"]-row["predicted"],2)
    errors = np.array([r["error"] for r in backtest])
    mae = float(np.mean(np.abs(errors))) if len(errors) else None
    rmse = float(np.sqrt(np.mean(errors**2))) if len(errors) else None
    mean, std = float(np.mean(counts)), float(np.std(counts))
    high = max(float(np.quantile(counts,.75)), mean+.35*std, 1.)
    wave = max(float(np.quantile(counts,.90)), mean+std, high+max(3.,.25*std))
    status = "WAVE" if prediction >= wave else "HIGH" if prediction > high else "NORMAL"
    return {
        "ready": True, "model":chosen, "prediction":round(prediction,1),
        "prediction_rounded":round(prediction), "status":status,
        "high_threshold":round(high,1), "wave_threshold":round(wave,1),
        "test_mae":round(mae,2) if mae is not None else None,
        "test_rmse":round(rmse,2) if rmse is not None else None,
        "confidence_score":None, "wave_probability":None, "prediction_interval_80":None,
        "evaluation_points":len(backtest), "selection_points":selection_n,
        "selection_mae":scores, "excluded_models":excluded,
        "sklearn_enabled":eligible_ml, "adaptive_model_selection":bool(selection_n),
        "last_3_weeks":counts[-3:], "last_3_labels":list(labels[-3:]),
        "training_points":n-3, "weeks_available":n, "backtest":backtest,
        "notice":"Planning estimate, not a calibrated probability. Few test points mean high uncertainty.",
    }


def forecast(weeks: list[dict], today: date, use_ml: bool = False) -> dict:
    completed = [w for w in weeks if w["complete"]]
    suffix = []
    for row in reversed(completed):
        if suffix and date.fromisoformat(suffix[-1]["week"])-date.fromisoformat(row["week"]) != timedelta(days=7):
            break
        suffix.append(row)
    suffix.reverse()
    if len(suffix) < 3:
        return {"ready":False, "status":"INSUFFICIENT_DATA", "weeks_available":len(suffix),
                "reason":"Need 3 consecutive, ended weeks marked complete. Missing weeks are not zero.",
                "test_mae":None,"test_rmse":None,"confidence_score":None,"backtest":[]}
    result = dict(model_forecast(tuple((r["week"],r["count"]) for r in suffix),use_ml))
    target = date.fromisoformat(suffix[-1]["week"])+timedelta(days=7)
    result.update(target_week=target.isoformat(), stale=target < monday(today), generated_at=now_iso())
    result["recommendations"] = ["Review ended weeks and complete missing records before trusting the forecast."] if result["stale"] else [
        "Use the estimate for planning, not as a guaranteed outcome.",
        "Keep logging verified and trash counts separately; compare campaign results without assuming causation."]
    return result


def normalize_campaign(payload: dict, today: date, existing: dict | None = None) -> dict:
    object_payload(payload)
    allowed = {"name","date","type","platform","description","impressions","engagements","compliments_attributed","notes"}
    if set(payload)-allowed:
        raise APIError("Campaign contains unknown or read-only fields.")
    result = dict(existing or {})
    result.update(payload)
    for field, default, limit in [("name","",120),("type","Other",50),("platform","Other",50),("description","",1000),("notes","",1000)]:
        result[field] = text(result.get(field,default),field,limit,field=="name")
    if result.get("date"):
        result["date"] = recorded_date(result["date"],today)
    else:
        result["date"] = today.isoformat()
    for field in ("impressions","engagements","compliments_attributed"):
        result[field] = count(result.get(field,0),field)
    result.update(id=existing["id"] if existing else str(uuid.uuid4()),
                  created_at=existing["created_at"] if existing else now_iso(), updated_at=now_iso())
    return result


def campaign_analytics(campaigns: list[dict]) -> dict:
    by_type, by_platform = {}, {}
    for row in campaigns:
        by_type[row["type"]] = by_type.get(row["type"],0)+1
        by_platform[row["platform"]] = by_platform.get(row["platform"],0)+1
    impressions = sum(r["impressions"] for r in campaigns)
    engagements = sum(r["engagements"] for r in campaigns)
    best = max(campaigns,key=lambda r:(r["compliments_attributed"],r["engagements"]),default=None)
    return {"campaign_count":len(campaigns),"total_impressions":impressions,"total_engagements":engagements,
            "total_compliments_attributed":sum(r["compliments_attributed"] for r in campaigns),
            "engagement_rate":round(100*engagements/impressions,2) if impressions else None,
            "best_campaign":best,"by_type":by_type,"by_platform":by_platform}


class Service:
    def __init__(self, db_path: Path, today_fn=local_today, use_ml: bool = False):
        self.store, self.today_fn, self.use_ml = Store(db_path), today_fn, use_ml

    def dashboard(self) -> dict:
        snapshot, today = self.store.snapshot(), self.today_fn()
        daily = daily_rows(snapshot["entries"])
        weeks = weekly_rows(snapshot,today)
        complete = [r for r in weeks if r["complete"]]
        latest = complete[-1] if complete else None
        prev = next((r for r in complete if latest and date.fromisoformat(r["week"])==date.fromisoformat(latest["week"])-timedelta(days=7)),None)
        delta = latest["count"]-prev["count"] if latest and prev else None
        prediction = forecast(weeks,today,self.use_ml)
        campaigns = campaign_analytics(snapshot["campaigns"])
        grades = {"6":0,"7":0,"8":0,"unassigned":0}
        for entry in snapshot["entries"]:
            grades[entry["grade"]] += entry["count"]
        total = sum(r["count"] for r in daily)
        facts = []
        if not daily:
            facts.append("No compliment counts have been recorded. Add a note and the verified totals to begin.")
        else:
            facts.append(f"{total:,} verified compliments are recorded across {len(daily)} dates.")
            facts.append(f"{sum(r['trash_count'] for r in daily):,} trash compliments are stored separately.")
        if latest:
            facts.append(f"The latest completed week starts {latest['week']} and contains {latest['count']:,} verified compliments.")
        campaign_n = len(snapshot["campaigns"])
        facts.append(f"{campaign_n} campaign{' has' if campaign_n == 1 else 's have'} been recorded. Attribution is entered by the team, not proof of causation.")
        if prediction["ready"]:
            facts.append(f"The estimate for the week of {prediction['target_week']} is {prediction['prediction_rounded']:,}; uncertainty remains high.")
        else:
            facts.append(prediction["reason"])
        return {
            "project":"PEAC Intelligence", "revision":snapshot["revision"],"today":today.isoformat(),
            "mode":"local", "entries":snapshot["entries"], "imports":snapshot["imports"],
            "workspace":{"storage":"SQLite", "database":str(self.store.path), "shared_online":os.getenv("PEAC_DEPLOY_MODE","").lower()=="hosted",
                         "message":"One shared database on the hosted PEAC service." if os.getenv("PEAC_DEPLOY_MODE","").lower()=="hosted" else "One database on this local PEAC server."},
            "compliments":{
                "all_time_total":total,"trash_total":sum(r["trash_count"] for r in daily),
                "this_week":latest["count"] if latest else None,
                "latest_completed_week":latest["week"] if latest else None,
                "previous_week":prev["count"] if prev else None,"change":delta,
                "change_percent":round(100*delta/prev["count"],1) if prev and prev["count"] else None,
                "weeks_tracked":len(weeks),"completed_weeks":len(complete),"days_recorded":len(daily),
            },"daily":daily,"weeks":weeks,"grades":grades,"forecast":prediction,
            "campaigns":campaigns,"campaign_list":snapshot["campaigns"],"notes":snapshot["notes"],
            "ai":{"summary":" ".join(facts),"source":"local_analytics","generated_at":now_iso(),
                  "notice":"Computed from saved records. No language model was used.", "facts":facts},
            "generated_at":now_iso(),
        }

    def dispatch(self, method: str, path: str, payload: Any = None, key: str = "") -> tuple[Any,int]:
        today = self.today_fn()
        if method == "GET" and path == "/api/revision":
            with self.store.connection() as db:
                revision=int(db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
            return {"revision":revision},200
        if method == "POST" and path == "/api/import/sheets":
            from peac_import import list_sheets
            return list_sheets(payload),200
        if method == "POST" and path == "/api/import/preview":
            from peac_import import preview
            return preview(self,payload),200
        if method == "POST" and path == "/api/import/commit":
            from peac_import import commit
            return commit(self,payload,key),200
        if method == "GET":
            if path == "/api/health":
                return {"ok":True,"service":"PEAC Intelligence","time":now_iso(),"mode":"local","ml_enabled":self.use_ml},200
            if path == "/api/export":
                return {"format":"peac-snapshot-v1","exported_at":now_iso(),**self.store.snapshot()},200
            if path == "/api/compliments":
                return daily_rows(self.store.snapshot()["entries"]),200
            if path == "/api/campaigns":
                return self.store.snapshot()["campaigns"],200
            if path == "/api/notes":
                return self.store.snapshot()["notes"],200
            if path == "/api/weeks":
                return weekly_rows(self.store.snapshot(),today),200
            if path == "/api/grade_data":
                dash = self.dashboard()
                return {"totalCompliments":dash["compliments"]["all_time_total"],"gradeData":[
                    {"grade":f"{g}th Grade" if g != "unassigned" else "Unassigned", "count":v}
                    for g,v in dash["grades"].items()]},200
            if path in {"/api/dashboard","/api/forecast","/api/model-report","/api/insights","/api/charts"}:
                dash = self.dashboard()
                if path == "/api/dashboard": return dash,200
                if path in {"/api/forecast","/api/model-report"}: return dash["forecast"],200
                if path == "/api/insights":
                    from peac_ai import select_summary
                    return select_summary(dash["ai"]),200
                def chart(labels,values,label): return {"labels":labels,"datasets":[{"label":label,"data":values}]}
                return {
                    "compliment_trend":chart([r["week"] for r in dash["weeks"]],[r["count"] for r in dash["weeks"]],"Recorded weekly counts (partial until complete)"),
                    "campaign_types":chart(list(dash["campaigns"]["by_type"]),list(dash["campaigns"]["by_type"].values()),"Campaigns"),
                    "campaign_platforms":chart(list(dash["campaigns"]["by_platform"]),list(dash["campaigns"]["by_platform"].values()),"Campaigns"),
                    "campaign_results":chart([c["name"] for c in dash["campaign_list"]],[c["compliments_attributed"] for c in dash["campaign_list"]],"Team-attributed compliments"),
                },200
        if path == "/api/anonymize":
            raise APIError("Name collection is disabled. Use aggregate counts; do not upload student names.",410)
        if method in {"POST","PUT","DELETE"}:
            payload = object_payload(payload)
            if method == "POST" and path in {"/api/compliments","/api/notes"}:
                entry = validate_count_entry(payload,today,path=="/api/notes")
                return self.store.mutate(key,path,payload,lambda db:{"id":self.store.insert_entry(db,entry)}),201
            if method == "POST" and path == "/api/compliments/bulk":
                if set(payload)-{"weeks","replace","confirm"}: raise APIError("Unknown import fields.")
                incoming = payload.get("weeks")
                if not isinstance(incoming,list) or not 1 <= len(incoming) <= 5000:
                    raise APIError("Send between 1 and 5000 date/count records under weeks.")
                entries = [validate_count_entry(r,today) for r in incoming]
                dates = [r["date"] for r in entries]
                if len(dates)!=len(set(dates)): raise APIError("Duplicate dates in bulk import. Combine them first.")
                replace = payload.get("replace",False)
                if type(replace) is not bool: raise APIError("replace must be a boolean.")
                if replace and payload.get("confirm")!="REPLACE COUNTS": raise APIError("Replacement requires confirm='REPLACE COUNTS'.")
                def bulk(db):
                    if replace:
                        db.execute("DELETE FROM entries")
                        db.execute("DELETE FROM closed_weeks")
                        db.execute("UPDATE notes SET counts_reset=1")
                    elif any(db.execute("SELECT 1 FROM entries WHERE date=?",(r["date"],)).fetchone() for r in entries):
                        raise APIError("An imported date already exists. Nothing was changed.",409)
                    for entry in entries: self.store.insert_entry(db,entry)
                    return {"imported":len(entries)}
                return self.store.mutate(key,path,payload,bulk),200
            if method == "DELETE" and path == "/api/compliments":
                if payload.get("confirm")!="RESET COUNTS": raise APIError("Type RESET COUNTS to confirm.")
                revision = payload.get("revision")
                if type(revision) is not int: raise APIError("A current revision is required.")
                def reset(db):
                    current = int(db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
                    if current != revision: raise APIError("Records changed. Refresh and confirm again.",409)
                    db.execute("DELETE FROM entries")
                    db.execute("DELETE FROM closed_weeks")
                    db.execute("UPDATE notes SET counts_reset=1")
                    return {"notes_kept":True}
                return self.store.mutate(key,path,payload,reset),200
            match = re.fullmatch(r"/api/weeks/(\d{4}-\d{2}-\d{2})",path)
            if match and method == "PUT":
                start = recorded_date(match.group(1),today)
                if monday(date.fromisoformat(start)).isoformat()!=start: raise APIError("Week must start on Monday.")
                if type(payload.get("complete")) is not bool: raise APIError("complete must be true or false.")
                if payload["complete"] and date.fromisoformat(start)+timedelta(days=6)>=today:
                    raise APIError("The week has not ended yet.")
                def close(db):
                    end = (date.fromisoformat(start)+timedelta(days=6)).isoformat()
                    if not db.execute("SELECT 1 FROM entries WHERE date BETWEEN ? AND ?",(start,end)).fetchone():
                        raise APIError("Record the week first, including an explicit zero if measured.")
                    if payload["complete"]: db.execute("INSERT OR REPLACE INTO closed_weeks VALUES(?,?)",(start,now_iso()))
                    else: db.execute("DELETE FROM closed_weeks WHERE week=?",(start,))
                    return {"week":start,"complete":payload["complete"]}
                return self.store.mutate(key,path,payload,close),200
            if path == "/api/campaigns" and method == "POST":
                campaign = normalize_campaign(payload,today)
                def add(db):
                    db.execute("INSERT INTO campaigns VALUES(?,?)",(campaign["id"],json.dumps(campaign)))
                    return {"campaign":campaign}
                return self.store.mutate(key,path,payload,add),201
            match = re.fullmatch(r"/api/campaigns/([a-f0-9-]{36})",path)
            if match and method in {"PUT","DELETE"}:
                identity = match.group(1)
                def change(db):
                    row = db.execute("SELECT payload FROM campaigns WHERE id=?",(identity,)).fetchone()
                    if not row: raise APIError("Campaign not found.",404)
                    if method=="DELETE":
                        db.execute("DELETE FROM campaigns WHERE id=?",(identity,))
                        return {"deleted":identity}
                    campaign = normalize_campaign(payload,today,json.loads(row[0]))
                    db.execute("UPDATE campaigns SET payload=? WHERE id=?",(json.dumps(campaign),identity))
                    return {"campaign":campaign}
                return self.store.mutate(key,method+path,payload,change),200
        raise APIError("Endpoint or method not found.",404)


def export_csv(snapshot: dict) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream,fieldnames=["week","count","trash_count"])
    writer.writeheader()
    writer.writerows(daily_rows(snapshot["entries"]))
    return stream.getvalue()
