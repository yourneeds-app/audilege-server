import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
import curation
import linked_media
import maintenance
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

from books import audio_epub, index_epub, track_picture
from abs_history import number

ROOT = Path(sys.executable if getattr(sys,"frozen",False) else __file__).resolve().parent
TYPES = {"ebook":"E-Books", "audio":"Hörbücher", "audilege":"Audilege", "podcast":"Podcasts"}
AUDIO = {".mp3",".m4b",".m4a",".wav",".ogg",".flac"}
WORKER_STEPS = ("Arbeitskopie vorbereiten", "Ton vorbereiten", "Sprachmodell auf der CPU ausführen",
                "Wörter markieren", "Text und Ton zusammenführen", "Fertige Ausgabe übernehmen")


def worker_failure(log, code):
    with log.open("rb") as stream:
        stream.seek(max(0,log.stat().st_size-32768))
        tail=stream.read().lower()
    if b"no space left" in tail or b"enospc" in tail:
        return "Der Speicherplatz für die Arbeitskopien reicht nicht. Auf dem Worker-Laufwerk Platz freigeben."
    if b"bus error" in tail or code in (-7,135):
        return "Der Abgleichprozess ist mit einem Busfehler (SIGBUS) abgebrochen. Speicherplatz und Zustand der Worker-Umgebung prüfen."
    if b"out of memory" in tail or code in (-9,137):
        return "Der Worker wurde beendet. Freien Arbeitsspeicher und das Worker-Protokoll prüfen."
    if b"permission denied" in tail:
        return "Der Worker konnte seine Arbeitsdateien nicht lesen oder schreiben. Die Ordnerberechtigungen prüfen."
    return f"Der Abgleichprozess wurde mit Status {code} beendet. Einzelheiten stehen in worker.log."


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,salt BLOB NOT NULL,digest BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS tokens(hash BLOB PRIMARY KEY,owner INTEGER NOT NULL,kind TEXT NOT NULL,expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS podcast_items(feed TEXT,guid TEXT,book INTEGER NOT NULL,show_title TEXT NOT NULL,PRIMARY KEY(feed,guid));
CREATE UNIQUE INDEX IF NOT EXISTS podcast_book ON podcast_items(book);
CREATE TABLE IF NOT EXISTS podcast_feeds(id INTEGER PRIMARY KEY AUTOINCREMENT,url TEXT NOT NULL UNIQUE,title TEXT NOT NULL,creator TEXT NOT NULL,owner INTEGER NOT NULL,due INTEGER NOT NULL DEFAULT 0,checked INTEGER,error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS podcast_art(feed INTEGER PRIMARY KEY,source TEXT NOT NULL,mime TEXT NOT NULL,image BLOB NOT NULL);
CREATE TRIGGER IF NOT EXISTS delete_podcast_art AFTER DELETE ON podcast_feeds BEGIN DELETE FROM podcast_art WHERE feed=OLD.id; END;
CREATE TABLE IF NOT EXISTS podcast_cleanup(folder TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS podcast_building(folder TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS book_covers(book INTEGER PRIMARY KEY,mime TEXT NOT NULL,image BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS server_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scanned_media(source TEXT PRIMARY KEY,signature TEXT NOT NULL,book INTEGER NOT NULL,source_tags TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS scanned_media_book_source ON scanned_media(book,source);
CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY,title TEXT NOT NULL,author TEXT NOT NULL,category TEXT NOT NULL,edition INTEGER);
CREATE TABLE IF NOT EXISTS editions(id INTEGER PRIMARY KEY,book INTEGER NOT NULL,folder TEXT NOT NULL UNIQUE,cover TEXT);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,book INTEGER NOT NULL,owner INTEGER NOT NULL,folder TEXT NOT NULL,language TEXT NOT NULL,state TEXT NOT NULL,note TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(book) WHERE state in ('running','waiting');
CREATE TABLE IF NOT EXISTS progress(owner INTEGER,edition INTEGER,data TEXT NOT NULL,PRIMARY KEY(owner,edition));
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY,owner INTEGER,edition INTEGER,sid TEXT,start TEXT,end TEXT,seconds INTEGER,kind TEXT,UNIQUE(owner,sid));
CREATE TABLE IF NOT EXISTS abs_sessions(owner INTEGER,source TEXT,sid TEXT,book TEXT,episode TEXT,title TEXT,day TEXT,seconds REAL,PRIMARY KEY(owner,source,sid));
CREATE TABLE IF NOT EXISTS abs_progress(owner INTEGER,source TEXT,book TEXT,episode TEXT,ebook REAL,audio REAL,finished INTEGER,updated INTEGER,PRIMARY KEY(owner,source,book,episode));
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")


def default_progress(file):
    return {"fileId":file,"percentage":0,"updatedAt":None,"koreader":None,"resumeMode":None,
            "text":dict.fromkeys(("cfi","page","webOffset","updatedAt")),
            "narration":dict.fromkeys(("seconds","fragment","sectionIndex","percentage","updatedAt")),
            "kobo":dict.fromkeys(("source","type","value","contentPercent"))}


def get_progress(db, owner, file):
    row = db.execute("SELECT data FROM progress WHERE owner=? AND edition=?", (owner,file)).fetchone()
    if not row:return default_progress(file)
    data=json.loads(row[0])
    data.setdefault("resumeMode",None)
    return data


def save_progress(db, owner, entry):
    file = int(entry["fileId"])
    if not db.execute("SELECT 1 FROM editions WHERE id=?", (file,)).fetchone():
        raise KeyError("Ausgabe unbekannt.")
    row = get_progress(db,owner,file)
    saved = row["updatedAt"]
    status = "superseded"
    if entry["editedAt"] == (saved or "1970-01-01T00:00:00.000Z"):
        kind = entry["kind"]
        if kind not in ("narration","text"):
            raise ValueError("Unbekannte Leseart.")
        percent = number(entry["percentage"],100)
        stamp = now()
        if kind=="text":
            offset=entry.get("text",{}).get("webOffset")
            if offset is not None and (type(offset) is not int or not 0<=offset<=50_000_000):
                raise ValueError("Ungültige Textposition.")
            row["text"]["webOffset"]=offset
        for group in ("narration","text","kobo"):
            for key in row[group]:
                if key not in ("updatedAt","percentage") and key in entry.get(group,{}):
                    row[group][key] = entry[group][key]
        row.update(percentage=percent,updatedAt=stamp)
        mode=entry.get("resumeMode")
        row["resumeMode"]=mode if mode in ("read","listen","along") else ("read" if kind=="text" else None)
        row[kind]["updatedAt"] = stamp
        if kind == "narration":
            row[kind]["percentage"] = percent
        db.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?)",(owner,file,json.dumps(row)))
        status = "saved"
    return dict(fileId=file,status=status,progress=row)


def migrate_positions(lib,db,previous,file,book,info,disc_prefix=None):
    """Keep the latest per-profile position when the source editions become one."""
    sections=info["sections"]
    timeline=[];total=0
    for index,section in enumerate(sections):
        for cue in section["cues"]:
            total+=max(0,cue["end"]-cue["begin"])
            timeline.append((total,index,cue["anchor"]))
    def audio_at(seconds):
        import bisect
        return timeline[min(len(timeline)-1,bisect.bisect_right(timeline,(seconds,float("inf"),"")))]
    for edition in tuple(previous)[:2]:
        if not edition:continue
        e=db.execute("SELECT book,folder FROM editions WHERE id=?",(edition,)).fetchone()
        old=json.loads((lib.data/"editions"/e["folder"]/"index.json").read_text(encoding="utf8"))["sections"]
        paths={s["path"]:i for i,s in enumerate(sections)}
        if disc_prefix is not None:
            labels={s["name"]:i for i,s in enumerate(sections)}
            prefix=disc_prefix+"/" if disc_prefix else ""
            targets=[labels.get(prefix+s["name"]) for s in old]
            old_starts=[0.0]
            new_starts=[0.0]
            for items,starts in ((old,old_starts),(sections,new_starts)):
                for s in items:
                    starts.append(starts[-1]+sum(c["end"]-c["begin"] for c in s["cues"]))
        def chapter_for(index):
            i=max(0,min(int(index),len(old)-1))
            if disc_prefix is not None and targets[i] is not None:
                return targets[i]
            return paths.get(old[i]["path"],min(i,len(sections)-1))
        for owner,data in db.execute("SELECT owner,data FROM progress WHERE edition=?",(edition,)).fetchall():
            row=json.loads(data)
            if (get_progress(db,owner,file)["updatedAt"] or "")>=(row["updatedAt"] or ""):continue
            row["fileId"]=file
            narration=row["narration"];txt=row["text"]
            if timeline and narration.get("updatedAt"):
                seconds=narration.get("seconds")
                if disc_prefix is not None:
                    import bisect
                    if not isinstance(seconds,(int,float)):
                        seconds=old_starts[-1]*(narration.get("percentage") or row["percentage"])/100
                    old_i=max(0,min(len(old)-1,bisect.bisect_right(old_starts,seconds)-1))
                    new_i=chapter_for(old_i)
                    seconds=new_starts[new_i]+max(0,min(seconds-old_starts[old_i],new_starts[new_i+1]-new_starts[new_i]))
                    narration["percentage"]=seconds*100/total
                    if narration["updatedAt"]>=(txt.get("updatedAt") or ""):row["percentage"]=narration["percentage"]
                seconds=max(0,min(total,float(seconds))) if isinstance(seconds,(int,float)) else total*row["percentage"]/100
                _,i,anchor=audio_at(seconds)
                narration.update(seconds=seconds,fragment=anchor,sectionIndex=i)
            if txt.get("page"):
                txt["page"]=chapter_for(txt["page"]-1)+1
                if disc_prefix is not None:
                    txt["cfi"]=None
                    if (txt.get("updatedAt") or "")>(narration.get("updatedAt") or ""):
                        row["percentage"]=100*(txt["page"]-1)/len(sections)
            db.execute("INSERT OR REPLACE INTO progress VALUES(?,?,?)",(owner,file,json.dumps(row)))
        for mark in db.execute("SELECT * FROM bookmarks WHERE edition=?",(edition,)).fetchall():
            index=chapter_for(mark["chapter"]);cue=-1;offset=mark["offset"]
            if disc_prefix is not None:
                cue=mark["cue"]
            elif timeline and mark["cue"]>=0 and 0<=mark["chapter"]<len(old):
                seconds=sum(c["end"]-c["begin"] for s in old[:mark["chapter"]] for c in s["cues"])
                seconds+=sum(c["end"]-c["begin"] for c in old[mark["chapter"]]["cues"][:mark["cue"]])
                _,index,anchor=audio_at(seconds)
                cue=next(i for i,c in enumerate(sections[index]["cues"]) if c["anchor"]==anchor)
            db.execute("UPDATE bookmarks SET book=?,edition=?,chapter=?,offset=?,cue=? WHERE id=?",(book,file,index,offset,cue,mark["id"]))
        if e["book"]!=book:
            db.execute("INSERT OR IGNORE INTO player_items SELECT owner,?,kind,value FROM player_items WHERE book=?",(book,e["book"]))
            db.execute("DELETE FROM player_items WHERE book=?",(e["book"],))


def inherit_companion_cover(db,book,companion):
    # The companion keeps its original category even after its shelf entry is merged.
    row=db.execute("""SELECT CASE category WHEN 'ebook' THEN 'book' ELSE 'audio' END
                      FROM books WHERE id=? AND category IN ('ebook','audio')""",(companion,)).fetchone()
    if row:
        role=row[0]
        db.execute("""INSERT OR IGNORE INTO role_covers(book,role,mime,image)
                      SELECT ?,?,mime,image FROM role_covers WHERE book=? AND role=?""",(book,role,companion,role))
        db.execute("""INSERT OR IGNORE INTO role_covers(book,role,mime,image)
                      SELECT ?,?,mime,image FROM book_covers WHERE book=?""",(book,role,companion))


class Library:
    def __init__(self, data):
        self.data = Path(data).resolve()
        self.data.mkdir(parents=True,exist_ok=True)
        for d in ("editions","uploads","jobs"):
            (self.data/d).mkdir(exist_ok=True)
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA + curation.SCHEMA + maintenance.SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            db.execute("""INSERT OR IGNORE INTO device_tokens SELECT hash,lower(hex(randomblob(16))),kind
                FROM tokens WHERE expires>? AND hash NOT IN (SELECT hash FROM device_tokens)""",(time.time(),))
            if "started" not in [r[1] for r in db.execute("PRAGMA table_info(abs_sessions)")]:
                db.execute("ALTER TABLE abs_sessions ADD COLUMN started TEXT")
            if "added_at" not in [r[1] for r in db.execute("PRAGMA table_info(books)")]:
                db.execute("ALTER TABLE books ADD COLUMN added_at TEXT")
            db.execute("""CREATE TRIGGER IF NOT EXISTS book_added_at AFTER INSERT ON books WHEN NEW.added_at IS NULL
                       BEGIN UPDATE books SET added_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id; END""")
            job_columns={r[1] for r in db.execute("PRAGMA table_info(jobs)")}
            for column in ("started_at","phase_at","phase_progress"):
                if column not in job_columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {column} INTEGER")
            if "cover_revision" not in [r[1] for r in db.execute("PRAGMA table_info(books)")]:
                db.execute("ALTER TABLE books ADD COLUMN cover_revision TEXT NOT NULL DEFAULT ''")
            for table in ("book_covers", "role_covers"):
                for event, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
                    db.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_revision_{event} AFTER {event} ON {table}
                        BEGIN UPDATE books SET cover_revision=lower(hex(randomblob(16))) WHERE id={row}.book; END""")
            if "published" not in [r[1] for r in db.execute("PRAGMA table_info(podcast_items)")]:
                db.execute("ALTER TABLE podcast_items ADD COLUMN published INTEGER")
            if "creator" not in [r[1] for r in db.execute("PRAGMA table_info(podcast_items)")]:
                db.execute("ALTER TABLE podcast_items ADD COLUMN creator TEXT")
            if "archived_title" not in [r[1] for r in db.execute("PRAGMA table_info(sessions)")]:
                db.execute("ALTER TABLE sessions ADD COLUMN archived_title TEXT")
            if "is_admin" not in [r[1] for r in db.execute("PRAGMA table_info(users)")]:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
                db.execute("ALTER TABLE users ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
                db.execute("UPDATE users SET is_admin=1 WHERE id=(SELECT min(id) FROM users)")
            if "metadata" not in [r[1] for r in db.execute("PRAGMA table_info(books)")]:
                db.execute("ALTER TABLE books ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            if "source_tags" not in [r[1] for r in db.execute("PRAGMA table_info(scanned_media)")]:
                db.execute("ALTER TABLE scanned_media ADD COLUMN source_tags TEXT NOT NULL DEFAULT '{}'")
            if "display_source" not in [r[1] for r in db.execute("PRAGMA table_info(scanned_media)")]:
                db.execute("ALTER TABLE scanned_media ADD COLUMN display_source TEXT")
            for table, field in (("books","merged_into"), ("jobs","companion"), ("jobs","source_edition"), ("jobs","companion_edition")):
                if field not in [r[1] for r in db.execute(f"PRAGMA table_info({table})")]:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {field} INTEGER")
            if "label" not in [r[1] for r in db.execute("PRAGMA table_info(abs_progress)")]:
                db.execute("ALTER TABLE abs_progress ADD COLUMN label TEXT")
            if not maintenance.get_setting(db,"companion_cover_roles",False):
                for row in db.execute("""SELECT j.book,j.companion FROM jobs j JOIN books b ON b.id=j.companion
                                         WHERE j.state='done' AND b.merged_into=j.book ORDER BY j.id DESC"""):
                    inherit_companion_cover(db,*row)
                maintenance.setting(db,"companion_cover_roles",True)
        self.wakeup = Event()

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.data/"audilege.sqlite3",timeout=30)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def user(self, name, password):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            self.create_user(db,name,password,not db.execute("SELECT 1 FROM users LIMIT 1").fetchone())

    @staticmethod
    def password_hash(password):
        if not isinstance(password,str) or not 10 <= len(password) <= 1024:
            raise ValueError("Ein Passwort mit 10 bis 1024 Zeichen angeben.")
        salt = secrets.token_bytes(16)
        return salt,hashlib.pbkdf2_hmac("sha256",password.encode(),salt,420000)

    def create_user(self,db,name,password,admin=False):
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 120:
            raise ValueError("Bitte einen Benutzernamen mit höchstens 120 Zeichen angeben.")
        if db.execute("SELECT 1 FROM users WHERE name=?",(name.strip(),)).fetchone():
            raise ValueError("Dieser Benutzername ist bereits vergeben.")
        return db.execute("INSERT INTO users(name,salt,digest,is_admin) VALUES(?,?,?,?)",
                          (name.strip(),*self.password_hash(password),admin)).lastrowid

    def login(self,db,name,password):
        row = db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()
        digest = hashlib.pbkdf2_hmac("sha256",password.encode(),row["salt"] if row else bytes(16),420000)
        if not row or not row["enabled"] or not hmac.compare_digest(digest,row["digest"]):
            raise PermissionError("Anmeldung fehlgeschlagen.")
        return row["id"]

    def token(self,db,owner,kind,lifetime,device=None,agent="Audilege"):
        value = secrets.token_urlsafe(40)
        db.execute("DELETE FROM tokens WHERE expires<?",(time.time(),))
        db.execute("INSERT INTO tokens VALUES(?,?,?,?)",(hashlib.sha256(value.encode()).digest(),owner,kind,int(time.time())+lifetime))
        db.execute("DELETE FROM device_tokens WHERE hash NOT IN (SELECT hash FROM tokens)")
        db.execute("INSERT INTO device_tokens VALUES(?,?,?)",(hashlib.sha256(value.encode()).digest(),device or uuid.uuid4().hex,agent[:160]))
        return value

    def identity(self,db,token,kind):
        key = hashlib.sha256(token.encode()).digest()
        row = db.execute("SELECT owner FROM tokens JOIN users ON users.id=tokens.owner WHERE hash=? AND kind=? AND expires>? AND enabled=1",(key,kind,time.time())).fetchone()
        if not row:
            raise PermissionError("Bitte anmelden.")
        return row[0]

    def draft(self,owner,key):
        if not isinstance(key,str) or len(key)!=32 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Upload unbekannt.")
        return self.data/"uploads"/str(owner)/key

    def files(self,owner,ids):
        if not isinstance(ids,list) or not 1 <= len(ids) <= 999 or len(set(ids))!=len(ids):
            raise ValueError("Bitte passende Dateien auswählen.")
        tracks = []
        for key in ids:
            folder = self.draft(owner,key)
            meta = json.loads((folder/"ready.json").read_text(encoding="utf8"))
            tracks.append((folder/("content"+meta["ext"]),meta["name"]))
        return tracks

    def edition(self,db,book,file=None):
        row = db.execute("""SELECT e.* FROM editions e JOIN books b ON e.book=b.id
            WHERE b.id=? AND e.id=coalesce(?,b.edition)""",(book,file)).fetchone()
        if not row:
            raise KeyError("Ausgabe unbekannt.")
        return row, self.data/"editions"/row["folder"]

    def publish(self,folder,book,category,info,job=None,podcast=None,scan=None,originals=None,discs=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            last_edition=None
            if scan:
                incoming=info.get("metadata",{})|{"title":info["title"],"author":info["author"]}
                previous=db.execute("SELECT book,signature,source_tags FROM scanned_media WHERE source=?",(scan[0],)).fetchone()
                if previous:
                    if previous["signature"]==scan[1]:
                        raise ValueError("Dateien wurden bereits eingelesen.")
                    book=previous["book"]
                    active=db.execute("SELECT title,author,metadata,category,merged_into,edition FROM books WHERE id=?",(book,)).fetchone()
                    if active["category"]!=category or active["merged_into"]:
                        raise ValueError("Die Bibliotheksfassung wurde inzwischen umgewandelt. Geänderte Quelle separat importieren.")
                    last_edition=active["edition"]
                    old=json.loads(previous["source_tags"])
                    merged=json.loads(active["metadata"])|{"title":active["title"],"author":active["author"]}
                    for key in old.keys() | incoming.keys():
                        if merged.get(key)==old.get(key):
                            if key in incoming:merged[key]=incoming[key]
                            else:merged.pop(key,None)
                    db.execute("UPDATE books SET title=?,author=?,metadata=? WHERE id=?",
                               (merged.pop("title"),merged.pop("author"),json.dumps(merged),book))
            if book is None:
                book = db.execute("""INSERT INTO books(id,title,author,category,metadata)
                    VALUES((SELECT max(coalesce(max(id),0),coalesce((SELECT CAST(value AS INTEGER) FROM server_settings WHERE key='retired_book'),0))+1 FROM books),?,?,?,?)""",
                    (info["title"],info["author"],category,json.dumps(info.get("metadata",{}),ensure_ascii=False))).lastrowid
                if podcast:
                    subscription=db.execute("SELECT id FROM podcast_feeds WHERE url=?",(podcast["feed"],)).fetchone()
                    if (subscription[0] if subscription else None)!=podcast.get("subscription"):
                        raise ValueError("Der Abostatus hat sich geändert. Bitte die Feedansicht aktualisieren.")
                    db.execute("INSERT INTO podcast_items(feed,guid,book,show_title,published,creator) VALUES(?,?,?,?,?,?)",
                               (podcast["feed"],podcast["guid"],book,podcast["show"],podcast.get("published"),podcast.get("creator")))
                    if podcast.get("art"):
                        mime,image=podcast["art"]
                        db.execute("INSERT INTO book_covers VALUES(?,?,?)",(book,mime,image))
            file = db.execute("""INSERT INTO editions(id,book,folder,cover)
                VALUES((SELECT max(coalesce(max(id),0),coalesce((SELECT CAST(value AS INTEGER) FROM server_settings WHERE key='retired_edition'),0))+1 FROM editions),?,?,?)""",
                (book,folder.name,info["cover"])).lastrowid
            db.execute("UPDATE books SET edition=?,category=? WHERE id=?",(file,category,book))
            if category!="podcast" and curation.config(db).get("autoImports"):
                db.execute("INSERT OR IGNORE INTO auto_review_queue(edition,book) VALUES(?,?)",(file,book))
            if podcast and podcast.get("subscription"):
                from podcasts import prune
                prune(db,podcast["feed"],podcast["order"])
            if podcast:
                db.execute("DELETE FROM podcast_building WHERE folder=?",(folder.name,))
            if last_edition:
                migrate_positions(self,db,(last_edition,),file,book,info,disc_prefix="" if discs else None)
            for source,name in (discs or {}).items():
                old=db.execute("""SELECT b.* FROM scanned_media s JOIN books b ON b.id=s.book
                    WHERE s.source=? AND b.category='audio' AND b.merged_into IS NULL""",(source,)).fetchone()
                if old and old["id"]!=book:
                    if db.execute("""SELECT 1 FROM jobs WHERE (book=? OR companion=?) AND state IN ('running','waiting')""",
                                  (old["id"],old["id"])).fetchone():
                        raise InterruptedError("Ein Auftrag verwendet diese CD.")
                    migrate_positions(self,db,(old["edition"],),file,book,info,disc_prefix=name)
                    db.execute("UPDATE books SET merged_into=? WHERE id=?",(book,old["id"]))
            if scan:
                db.execute("INSERT OR REPLACE INTO scanned_media(source,signature,book,source_tags) VALUES(?,?,?,?)",(*scan,book,json.dumps(incoming)))
            if job:
                if originals:db.execute("INSERT INTO uploaded_originals VALUES(?,?)",(job,originals.name))
                previous=db.execute("SELECT source_edition,companion_edition,companion FROM jobs WHERE id=?",(job,)).fetchone()
                if previous["companion"]:inherit_companion_cover(db,book,previous["companion"])
                migrate_positions(self,db,previous,file,book,info)
                import re
                filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',info["title"])[:85].rstrip(". ") or "Audilege"
                db.execute("INSERT INTO readalong_exports VALUES(?,?,NULL)",(file,f"{filename} - Audilege {book}-{file}.epub"))
                db.execute("INSERT OR IGNORE INTO retention(job) VALUES(?)",(job,))
                db.execute("UPDATE books SET merged_into=? WHERE id=(SELECT companion FROM jobs WHERE id=?)",(book,job))
                db.execute("UPDATE jobs SET state='done',note='' WHERE id=?",(job,))
        return book

    def import_book(self,owner,body,podcast=None):
        tracks = self.files(owner,body["files"])
        return self.import_tracks(tracks, body, podcast=podcast)

    def import_tracks(self,tracks,body,podcast=None,scan=None,verify=None,link_root=None):
        kind = body["category"]
        folder = self.data/"editions"/uuid.uuid4().hex
        if podcast:
            with self.db() as db:db.execute("INSERT INTO podcast_building VALUES(?)",(folder.name,))
        folder.mkdir()
        epub = folder/"book.epub"
        fields={}
        try:
            linked_epub=False
            links={}
            if kind=="ebook" and len(tracks)==1 and tracks[0][0].suffix.lower()==".epub":
                if link_root:
                    linked_epub=True
                    epub=tracks[0][0]
                    links["epub"]=linked_media.describe(link_root,epub)
                else:
                    shutil.copyfile(tracks[0][0],epub)
            elif kind in ("audio","podcast") and all(p.suffix.lower() in AUDIO for p,_ in tracks):
                if link_root:
                    links["tracks"]={f"track{i}{p.suffix.lower()}":linked_media.describe(link_root,p) for i,(p,_) in enumerate(tracks)}
                fields=audio_epub(epub,tracks,str(body.get("title") or ""),str(body.get("author") or ""),linked=bool(link_root),
                                  title_folder=str(body.get("title_folder") or "") if scan and kind=="audio" else "")
            else:
                raise ValueError("Diese Dateien passen nicht zur Rubrik.")
            if links:
                (folder/'linked.json').write_text(json.dumps(links|{'root':str(link_root)}),encoding='utf8')
            info = index_epub(epub,folder,linked=linked_epub)
            if kind=="ebook" and any(s["cues"] for s in info["sections"]):
                kind="audilege"
            info["metadata"].update(fields)
            if verify:verify()
            discs={os.path.normcase(str(p.parent)):p.parent.name for p,label in tracks if "/" in label} if scan and kind=="audio" else {}
            return self.publish(folder,None,kind,info,podcast=podcast,scan=scan,discs=discs)
        except Exception:
            shutil.rmtree(folder)
            if podcast:
                with self.db() as db:db.execute("DELETE FROM podcast_building WHERE folder=?",(folder.name,))
            raise

    def enqueue(self,owner,book,ids,language,companion=None):
        import re
        if not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?",language):
            raise ValueError("Ungültige Sprache.")
        with self.db() as db:
            edition, source = self.edition(db,book)
            kind = db.execute("SELECT category FROM books WHERE id=? AND merged_into IS NULL",(book,)).fetchone()
            if not kind:
                raise ValueError("Dieser Titel wurde bereits zusammengeführt.")
            kind=kind[0]
            second=None
            if companion is not None:
                if ids or companion==book:
                    raise ValueError("Genau eine passende zweite Ausgabe wählen.")
                second,other=self.edition(db,companion)
                target=db.execute("SELECT category FROM books WHERE id=? AND merged_into IS NULL",(companion,)).fetchone()
                if not target or {kind,target[0]}!={"ebook","audio"}:
                    raise ValueError("Ein E-Book und ein reines Hörbuch wählen.")
        tracks = self.files(owner,ids) if second is None else []
        if kind not in ("ebook","audio"):
            raise ValueError("Dieses Buch ist bereits zugeordnet.")
        job = self.data/"jobs"/uuid.uuid4().hex
        job.mkdir()
        try:
            (job/"audio").mkdir()
            copy_library_audio = None
            if second is not None:
                ebook,copy_library_audio=(source,other) if kind=="ebook" else (other,source)
                shutil.copyfile(linked_media.original_epub(ebook),job/"source.epub")
            elif kind=="ebook" and all(p.suffix in AUDIO for p,_ in tracks):
                shutil.copyfile(linked_media.original_epub(source),job/"source.epub")
                for i,(p,_) in enumerate(tracks):
                    shutil.copyfile(p,job/"audio"/f"{i:04}{p.suffix}")
            elif kind=="audio" and len(tracks)==1 and tracks[0][0].suffix==".epub":
                index_epub(tracks[0][0],job/"validation")
                shutil.copyfile(tracks[0][0],job/"source.epub")
                shutil.rmtree(job/"validation")
                copy_library_audio=source
            else:
                raise ValueError("Bitte EPUB und passende Hörfassung wählen.")
            if copy_library_audio is not None:
                from books import resource
                info = json.loads((copy_library_audio/"index.json").read_text(encoding="utf8"))
                names=dict.fromkeys(section["cues"][0]["path"] for section in info["sections"] if section["cues"])
                for i,name in enumerate(names):
                    shutil.copyfile(linked_media.track_path(copy_library_audio,name,resource(copy_library_audio,name)),job/"audio"/f"{i:04}{Path(name).suffix}")
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                for bid,e in [(book,edition)]+([(companion,second)] if second else []):
                    if not db.execute("SELECT 1 FROM books WHERE id=? AND edition=? AND merged_into IS NULL",(bid,e["id"])).fetchone():
                        raise ValueError("Die Ausgabe wurde inzwischen geändert.")
                    if db.execute("SELECT 1 FROM jobs WHERE state IN ('waiting','running') AND (book=? OR companion=?)",(bid,bid)).fetchone():
                        raise sqlite3.IntegrityError("Titel wird verarbeitet")
                db.execute("""INSERT INTO jobs(book,owner,folder,language,state,note,companion,source_edition,companion_edition)
                            VALUES(?,?,?,?,'waiting','',?,?,?)""",(book,owner,job.name,language,companion,edition["id"],second["id"] if second else None))
        except Exception:
            shutil.rmtree(job)
            raise
        self.wakeup.set()

    def retry_job(self,owner,job_id):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM jobs WHERE id=? AND owner=?",(job_id,owner)).fetchone()
            if not row:raise KeyError("Auftrag nicht gefunden.")
            if row["state"]!="failed":raise ValueError("Nur einen fehlgeschlagenen Auftrag erneut starten.")
            job=self.data/"jobs"/row["folder"]
            if (not re.fullmatch(r"[0-9a-f]{32}",row["folder"]) or job.resolve()!=job or
                not (job/"source.epub").is_file() or not any(p.is_file() and p.suffix.lower() in AUDIO for p in (job/"audio").glob("*"))):
                raise ValueError("Die Arbeitsdateien fehlen. Den Abgleich beim Titel neu anlegen.")
            for bid,snapshot in ((row["book"],row["source_edition"]),(row["companion"],row["companion_edition"])):
                if bid is None:continue
                active=db.execute("""SELECT edition FROM books WHERE id=? AND merged_into IS NULL AND category IN ('ebook','audio')""",(bid,)).fetchone()
                if not active or (snapshot is not None and active[0]!=snapshot) or (snapshot is None and
                    db.execute("SELECT count(*) FROM editions WHERE book=?",(bid,)).fetchone()[0]!=1):
                    raise ValueError("Die Ausgabe hat sich geändert. Beim aktuellen Titel einen neuen Abgleich anlegen.")
                if db.execute("""SELECT 1 FROM jobs WHERE (id>? OR state IN ('waiting','running'))
                                 AND (book=? OR companion=?)""",(job_id,bid,bid)).fetchone():
                    raise ValueError("Für diesen Titel existiert ein neuerer oder aktiver Auftrag.")
            db.execute("UPDATE jobs SET state='waiting',note='' WHERE id=?",(job_id,))
        self.wakeup.set()

    def aligned_epub(self,job,job_id,language):
        ready=job/"aligned.epub"
        if ready.is_file():
            return ready
        shim = ROOT/"worker"/"run.sh"
        args = ["sh",str(shim),str(job),language]
        if sys.platform=="win32":
            from windows_worker import worker_command
            args = worker_command(shim, job, language)
        elif os.environ.get("AUDILEGE_WORKER_DIR"):
            args.append(os.environ["AUDILEGE_WORKER_DIR"])
        log_path=job/"worker.log"
        if log_path.exists():log_path.replace(job/"worker.previous.log")
        with log_path.open("wb") as log, subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT) as process:
            for line in process.stdout:
                log.write(line)
                step=line.decode("utf-8",errors="replace").strip()
                if step in WORKER_STEPS:
                    log.flush()
                    with self.db() as db:
                        db.execute("UPDATE jobs SET note=?,phase_at=?,phase_progress=NULL WHERE id=?",(step,int(time.time()),job_id))
                elif step.startswith("AUDILEGE_PROGRESS "):
                    percent=step.removeprefix("AUDILEGE_PROGRESS ")
                    if percent.isascii() and percent.isdigit() and len(percent)<=3 and int(percent)<=100:
                        log.flush()
                        with self.db() as db:
                            db.execute("UPDATE jobs SET phase_progress=? WHERE id=?",(int(percent),job_id))
            process.stdout.close()
            code=process.wait()
        if code:
            raise ValueError(worker_failure(log_path,code))
        (job/"result.epub").replace(ready)
        return ready

    def worker(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET state='failed',note='Server unterbrochen. Auftrag erneut starten.' WHERE state='running'")
        while True:
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM jobs WHERE state='waiting' ORDER BY id LIMIT 1").fetchone()
                if row:
                    stamp=int(time.time())
                    db.execute("UPDATE jobs SET state='running',started_at=?,phase_at=?,phase_progress=NULL WHERE id=?",(stamp,stamp,row["id"]))
            if not row:
                self.wakeup.wait(5)
                self.wakeup.clear()
                continue
            job = self.data/"jobs"/row["folder"]
            dest = self.data/"editions"/uuid.uuid4().hex
            originals=None
            try:
                ready=self.aligned_epub(job,row["id"],row["language"])
                with self.db() as db:db.execute("UPDATE jobs SET note='EPUB und Zeitmarken prüfen',phase_at=?,phase_progress=NULL WHERE id=?",(int(time.time()),row["id"]))
                dest.mkdir()
                try:os.link(ready,dest/"book.epub")
                except OSError:shutil.copyfile(ready,dest/"book.epub")
                info = index_epub(dest/"book.epub",dest)
                if not any(s["cues"] for s in info["sections"]):
                    raise ValueError("Keine geprüften Zeitmarken erzeugt.")
                from media_tools import probe
                first=next(iter(sorted((job/"audio").glob("*"))),None)
                if first:
                    try:
                        art=track_picture(first,probe(first))
                        if art:(dest/("audio-"+art[0])).write_bytes(art[2])
                    except (OSError,ValueError,subprocess.SubprocessError):pass
                if not row["companion"]:
                    with self.db() as db:
                        source_kind=db.execute("SELECT category FROM books WHERE id=?",(row["book"],)).fetchone()[0]
                    originals=self.data/"editions"/uuid.uuid4().hex
                    originals.mkdir()
                    inputs=sorted((job/"audio").glob("*")) if source_kind=="ebook" else [job/"source.epub"]
                    for src in inputs:
                        try:os.link(src,originals/src.name)
                        except OSError:shutil.copyfile(src,originals/src.name)
                self.publish(dest,row["book"],"audilege",info,row["id"],originals=originals)
                shutil.rmtree(job,ignore_errors=True)
            except Exception as e:
                if originals:shutil.rmtree(originals,ignore_errors=True)
                shutil.rmtree(dest,ignore_errors=True)
                with self.db() as db:
                    db.execute("UPDATE jobs SET state='failed',note=? WHERE id=?",(str(e)[:300],row["id"]))

    def start_worker(self):
        Thread(target=self.worker,daemon=True,name="audilege-alignment").start()
