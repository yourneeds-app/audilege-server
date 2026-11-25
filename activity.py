"""One per-account view of native sessions and imported Audiobookshelf activity."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import unicodedata


def title_key(title):
    return " ".join(unicodedata.normalize("NFKC", title or "").casefold().split())


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def day_parts(start, end, millis):
    """Allocate a recorded duration across calendar days without counting pauses."""
    if start.date() == end.date() or end <= start:
        return [(start.date().isoformat(), millis)]
    span = (end-start).total_seconds()
    cursor = start
    allocated = 0
    parts = []
    while cursor < end:
        until = min(end, datetime.combine(cursor.date()+timedelta(days=1), time.min, timezone.utc))
        cumulative = round(millis * ((until-start).total_seconds()/span))
        if cumulative > allocated:
            parts.append((cursor.date().isoformat(), cumulative-allocated))
        allocated = cumulative
        cursor = until
    return parts


def streak(days, today):
    active = sorted(date.fromisoformat(d) for d,n in days.items() if n>0 and d<=today.isoformat())
    previous = None
    run = best = 0
    for day in active:
        run = run + 1 if previous and day-previous == timedelta(days=1) else 1
        best = max(best,run)
        previous = day
    return {"current":run if previous and today-previous<=timedelta(days=1) else 0,"best":best}


def merged(db, owner, today=None):
    catalog = defaultdict(set)
    labels = {}
    for row in db.execute("SELECT id,title,author FROM books WHERE merged_into IS NULL"):
        key = "orbit:"+str(row["id"])
        catalog[title_key(row["title"])].add(key)
        labels[key] = (row["title"],row["author"])
    imports = list(db.execute("""SELECT * FROM abs_sessions WHERE owner=? AND seconds>0 ORDER BY source,sid""",(owner,)))
    imported_titles = defaultdict(set)
    for row in imports:
        imported_titles[title_key(row["title"])].add((row["source"],row["book"],row["episode"]))
    activities = {}
    events = []
    all_days = Counter()
    local_ids = set()
    fingerprints = Counter()

    def record(key,kind,day,started,millis,parts):
        group = activities.setdefault(kind,{"days":{},"books":{}})
        title,author = labels[key]
        item = group["books"].setdefault(key,{"title":title,"author":author,"millis":0,"days":{}})
        item["millis"] += millis
        for d,n in parts:
            all_days[d] += n
            for totals in (item["days"],group["days"]):
                totals[d] = totals.get(d,0)+n
        events.append(dict(title=title,kind=kind,day=day,started=started,seconds=millis/1000))

    native = db.execute("""SELECT s.*,coalesce(b.merged_into,b.id) AS book_id FROM sessions s
        LEFT JOIN editions e ON e.id=s.edition LEFT JOIN books b ON b.id=e.book
        WHERE s.owner=? AND s.seconds>0""",(owner,))
    for row in native:
        key = "orbit:"+str(row["book_id"]) if row["book_id"] else "archived:"+str(row["edition"])
        labels.setdefault(key,(row["archived_title"] or "Unbekannter Titel",""))
        start,end = utc(row["start"]),utc(row["end"])
        millis = round(row["seconds"]*1000)
        record(key,row["kind"],start.date().isoformat(),start.isoformat(),millis,day_parts(start,end,millis))
        if row["kind"]=="listen":
            local_ids.add((key,row["sid"]))
            fingerprints[key,start,millis] += 1
    # Consume an identified replica once before matching by timestamp. A date alone is not identity.
    candidates = []
    for row in imports:
        identity = row["source"],row["book"],row["episode"]
        title = title_key(row["title"])
        possible = catalog.get(title,set())
        if title and len(possible)==1 and len(imported_titles[title])==1 and not row["episode"]:
            key = next(iter(possible))
        else:
            key = "abs:"+hashlib.sha256("\0".join(identity).encode()).hexdigest()
        labels.setdefault(key,(row["title"],""))
        millis = round(row["seconds"]*1000)
        start = utc(row["started"]) if row["started"] else None
        fingerprint = key,start,millis
        if (key,row["sid"]) in local_ids:
            if fingerprints[fingerprint]:
                fingerprints[fingerprint]-=1
            continue
        candidates.append((row,key,millis,start,fingerprint))
    for row,key,millis,start,fingerprint in candidates:
        if start and fingerprints[fingerprint]:
            fingerprints[fingerprint]-=1
            continue
        record(key,"listen",row["day"],start.isoformat() if start else None,millis,[(row["day"],millis)])
    listening = activities.get("listen",{"books":{},"days":{}})
    events.sort(key=lambda e:(e["day"],e["started"] or "",e["title"]),reverse=True)
    return dict(activities=activities,heardMedia=len(listening["books"]),events=events[:100],
                days={d:n/1000 for d,n in all_days.items()},
                listeningDays={d:n/1000 for d,n in listening["days"].items()},
                streak=streak(all_days,today or datetime.now(timezone.utc).date()))

