"""Read the signed-in user's Audiobookshelf history. No credentials enter the export."""
import argparse
from datetime import date, datetime, timezone
from getpass import getpass
import json
import ipaddress
import math
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def instance(url):
    url = str(url).strip().rstrip("/")
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Bitte die Serveradresse ohne Anmeldedaten angeben.")
    return p._replace(netloc=p.netloc.lower()).geturl()


def fetch_history(base, get):
    rows = {}
    expected = None
    page = 0
    while True:
        data = get(f"/api/me/listening-sessions?itemsPerPage=100&page={page}")
        batch = data["sessions"]
        total = int(data["total"])
        if data["page"] != page or total < 0 or (expected is not None and total != expected):
            raise ValueError("Die Hörhistorie hat sich beim Export verändert. Bitte erneut exportieren.")
        expected = total
        for entry in batch:
            if entry["id"] in rows:
                raise ValueError("Überlappende Seiten in der Hörhistorie. Bitte erneut exportieren.")
            rows[entry["id"]] = entry
        if len(rows) == total:
            break
        if not batch or len(rows) > total:
            raise ValueError("Der Server hat eine unvollständige Historie geliefert.")
        page += 1
    payload = {"format": "audilege-abs-1", "server": instance(base), "sessions": list(rows.values()),
               "mediaProgress": get("/api/me/progress")["mediaProgress"]}
    titles = {s.get("libraryItemId"):s["displayTitle"] for s in rows.values() if s.get("displayTitle") and not s.get("episodeId")}
    for record in payload["mediaProgress"]:
        item_id = record.get("libraryItemId")
        if item_id and item_id not in titles:
            try:
                item = get("/api/items/" + quote(str(item_id),safe="") + "?minified=1")
                titles[item_id] = (item.get("media") or {}).get("metadata",{}).get("title")
            except HTTPError as error:
                if error.code not in (403,404):
                    raise
                titles[item_id] = None
        record["title"] = titles.get(item_id)
    # Export only statistical fields. ABS responses can contain device details and local paths.
    return {**payload, "sessions": [
        {k: row[k] for k in ("id", "libraryItemId", "episodeId", "displayTitle", "displayAuthor",
                              "timeListening", "startedAt", "updatedAt", "date", "dayOfWeek") if k in row}
        for row in payload["sessions"]], "mediaProgress": [
        {k: row[k] for k in ("libraryItemId", "episodeId", "title", "isFinished", "progress", "ebookProgress",
                              "lastUpdate", "finishedAt") if k in row} for row in payload["mediaProgress"]]}


def number(value, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Die Statistik enthält einen ungültigen Zahlenwert.")
    if value < 0 or (upper is not None and value > upper):
        raise ValueError("Wert außerhalb des gültigen Bereichs.")
    return value


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("In der Statistik fehlt eine Kennung.")
    return value


def prepare(payload):
    if payload.get("format") != "audilege-abs-1":
        raise ValueError("Bitte eine Audilege-Exportdatei aus Audiobookshelf wählen.")
    source = instance(payload["server"])
    sessions, progress = {}, {}
    for r in payload["sessions"]:
        sid, book = identifier(r["id"]), identifier(r["libraryItemId"])
        seconds = number(r["timeListening"])
        day = r.get("date")
        if day:
            day = date.fromisoformat(day).isoformat()
        else:
            day = datetime.fromtimestamp(number(r["startedAt"]) / 1000, timezone.utc).date().isoformat()
        sessions[sid] = (sid, book, r.get("episodeId") or "", str(r.get("displayTitle") or book),
                         day, seconds, datetime.fromtimestamp(number(r["startedAt"]) / 1000, timezone.utc).isoformat()
                         if r.get("startedAt") is not None else None)
    for r in payload["mediaProgress"]:
        key = (identifier(r["libraryItemId"]), r.get("episodeId") or "")
        pct = r.get("ebookProgress")
        audio = r.get("progress")
        finished = r.get("isFinished", False)
        if not isinstance(finished, bool):
            raise ValueError("Ungültiger Abschlussstatus.")
        progress[key] = (*key, number(pct, 1) if pct is not None else None,
                         number(audio, 1) if audio is not None else None, int(finished),
                         int(number(r.get("lastUpdate") or 0)),str(r.get("title") or ""))
    return source, list(sessions.values()), list(progress.values())


def apply_import(db, user, payload, commit):
    source, sessions, positions = prepare(payload)
    def counts(table):
        return db.execute(f"SELECT count(*) FROM {table} WHERE owner=? AND source=?", (user, source)).fetchone()[0]
    before = counts("abs_sessions")
    old_seconds = db.execute("SELECT coalesce(sum(seconds),0) FROM abs_sessions WHERE owner=? AND source=?",
                             (user, source)).fetchone()[0]
    db.executemany("""INSERT INTO abs_sessions(owner,source,sid,book,episode,title,day,seconds,started) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner,source,sid) DO UPDATE SET seconds=max(seconds,excluded.seconds),
        title=excluded.title, day=excluded.day, started=coalesce(excluded.started,abs_sessions.started)""", [(user, source, *s) for s in sessions])
    db.executemany("""INSERT INTO abs_progress(owner,source,book,episode,ebook,audio,finished,updated,label) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner,source,book,episode) DO UPDATE SET ebook=excluded.ebook,
        audio=excluded.audio, finished=excluded.finished, updated=excluded.updated,
        label=CASE WHEN excluded.label='' THEN label ELSE excluded.label END
        WHERE excluded.updated >= updated""", [(user, source, *p) for p in positions])
    seconds = db.execute("SELECT coalesce(sum(seconds),0) FROM abs_sessions WHERE owner=? AND source=?",
                         (user, source)).fetchone()[0]
    result = {"source": source, "sessions": len(sessions), "newSessions": counts("abs_sessions") - before,
              "addedSeconds": seconds - old_seconds, "progressRecords": len(positions)}
    if not commit:
        db.rollback()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Eigene Audiobookshelf-Statistik für Audilege exportieren")
    parser.add_argument("server")
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    base = instance(args.server)
    host=urlsplit(base).hostname
    if base.startswith("http://"):
        try:
            addr=ipaddress.ip_address(host)
            local=addr.is_loopback or addr.is_private
        except ValueError:
            local=host=="localhost" or host.endswith(".local")
        if not local:
            parser.error("Für diese Adresse bitte HTTPS verwenden.")
    token = getpass("Audiobookshelf-Token (nur für diesen Export): ").strip()
    opener = build_opener(NoRedirect())
    def get(path):
        req = Request(base + path, headers={"Authorization": "Bearer " + token})
        with opener.open(req, timeout=45) as response:
            return json.load(response)
    data = fetch_history(base, get)
    prepare(data)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False)
    print(f'{len(data["sessions"])} Hörsitzungen und {len(data["mediaProgress"])} Fortschrittseinträge exportiert.')


if __name__ == "__main__":
    main()
