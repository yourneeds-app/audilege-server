import argparse
import base64
from contextlib import contextmanager
from datetime import date, datetime
from getpass import getpass
from functools import lru_cache
import hashlib
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from urllib.parse import parse_qs, unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from abs_history import apply_import, number
from books import audio_art_path, epub_fields,resource,source_audio_art,xml
from library import AUDIO, Library, ROOT, TYPES, get_progress, save_progress
from metadata import SOURCES, fetch_cover, image_type, search
from podcasts import Subscriptions, import_episode, preview
from scanner import Inbox, folder_series, shelf_location
from media_tools import audiobook_title
import curation
import linked_media
from activity import merged
import maintenance


def catalog(db,owner,book_id=None,start=False,storage_roots=None,show_editions=False):
    out = []
    locations = {}
    where="";args=[owner,owner,book_id,book_id]
    if start:
        where=""" AND b.id IN (SELECT id FROM (SELECT id,row_number() OVER
            (PARTITION BY category ORDER BY id DESC) n FROM books WHERE merged_into IS NULL AND category<>'podcast') WHERE n<=6
            UNION SELECT id FROM (SELECT b.id FROM books b JOIN progress p ON b.edition=p.edition
            WHERE b.merged_into IS NULL AND p.owner=? AND json_extract(p.data,'$.percentage')<100
            ORDER BY json_extract(p.data,'$.updatedAt') DESC LIMIT 3))"""
        args.append(owner)
    storage_column = """(SELECT coalesce(s.display_source,s.source) FROM scanned_media s WHERE s.book=b.id
        AND NOT EXISTS (SELECT 1 FROM readalong_exports x WHERE x.edition=b.edition AND lower(x.path)=lower(s.source))
        ORDER BY s.source LIMIT 1) AS storage_source,"""
    if storage_roots is not None:
        storage_column += "(SELECT x.path FROM readalong_exports x WHERE x.edition=b.edition) AS export_path,"
    for b in db.execute("SELECT "+storage_column+""" b.*,e.cover,p.data,pi.feed,pi.show_title,pi.published,coalesce(nullif(pf.creator,''),pi.creator) AS creator,
        EXISTS(SELECT 1 FROM player_items i WHERE i.book=b.id AND i.owner=? AND i.kind='played') AS played,
        (EXISTS(SELECT 1 FROM book_covers c WHERE c.book=b.id) OR EXISTS(SELECT 1 FROM role_covers c WHERE c.book=b.id)) AS custom_cover FROM books b JOIN editions e ON e.id=b.edition
        LEFT JOIN podcast_items pi ON pi.book=b.id LEFT JOIN podcast_feeds pf ON pf.url=pi.feed
        LEFT JOIN progress p ON p.edition=b.edition AND p.owner=? WHERE
        ((? IS NULL AND b.merged_into IS NULL) OR b.id=?)"""+where+" ORDER BY b.title COLLATE NOCASE,b.id",args):
        prog = json.loads(b["data"]) if b["data"] else {}
        pct = prog.get("percentage",0)
        narrated = b["category"] != "ebook"
        txt=prog.get("text") or {}
        voice=prog.get("narration") or {}
        latest_text=(txt.get("updatedAt") or "")>(voice.get("updatedAt") or "")
        resume_mode=("read" if b["category"]=="ebook" else "listen" if b["category"] in ("audio","podcast")
                     else prog.get("resumeMode") or ("read" if latest_text else "along"))
        chapter=txt.get("page") if latest_text else voice.get("sectionIndex")
        if latest_text and not chapter:
            match=re.match(r"epubcfi\(/\d+/(\d+)",txt["cfi"] if isinstance(txt.get("cfi"),str) else "")
            if match:chapter=int(match[1])//2
        out.append({"id":b["id"],"title":b["title"],"authors":[{"name":b["author"]}] if b["author"] else [],
            "category":b["category"],"metadata":json.loads(b["metadata"]),"played":bool(b["played"]),"status":"present","libraryId":1,"readingProgress":pct,
            "readStatus":"finished" if pct>=100 else "reading" if pct else "unread",
            "addedAt":b["added_at"],"updatedAt":prog.get("updatedAt") or "", "cover":bool(b["cover"] or b["custom_cover"]),
            "coverRevision":f'{b["edition"]}-{b["cover_revision"]}',
            "resumeMode":resume_mode,"resumeChapter":chapter+(0 if latest_text else 1) if type(chapter) is int else None,
            "files":[{"id":b["edition"],"role":"primary","format":"epub","filename":"book.epub","mediaOverlay":{"available":narrated}}]})
        if show_editions and b["storage_source"] and b["category"] in ("ebook","audio"):
            source=Path(b["storage_source"])
            if b["category"]=="ebook":
                locations[b["id"]]=source.parent
            elif source.suffix.lower() not in AUDIO:
                locations[b["id"]]=source
        if b["category"] == "audio" and b["storage_source"]:
            folder = Path(b["storage_source"]).name
            if b["title"].casefold() == folder.casefold():
                out[-1]["title"] = audiobook_title(out[-1]["metadata"].get("title"), b["title"])
        if storage_roots is not None:
            origin = shelf_location(b["storage_source"], storage_roots)
            out[-1]["storage"] = shelf_location(b["export_path"], storage_roots) if b["export_path"] else origin
            if b["category"] != "podcast":
                folder_series(origin, out[-1]["metadata"])
        if b["feed"]:
            out[-1]["podcast"]={"show":b["show_title"],"creator":b["creator"],"published":b["published"],
                                "key":hashlib.sha256(b["feed"].encode()).hexdigest()}
    if show_editions:
        pair_editions(db,out,locations)
    return out


def pair_editions(db,books,locations):
    eligible={b["id"]:b for b in books if b["category"] in ("ebook","audio")}
    blocked=set()

    def pair(left,right):
        eligible[left]["companionId"]=right
        eligible[right]["companionId"]=left
        blocked.update((left,right))

    explicit={}
    for left,target in db.execute("SELECT book,target FROM library_links WHERE kind='companion'"):
        if not str(target).isdigit():continue
        right=int(target)
        if left in eligible and right in eligible and eligible[left]["category"]!=eligible[right]["category"]:
            explicit.setdefault(left,set()).add(right)
            explicit.setdefault(right,set()).add(left)
    for left,targets in explicit.items():
        if len(targets)==1:
            right=next(iter(targets))
            if explicit[right]=={left}:
                pair(left,right)
    blocked.update(explicit)

    def match(values):
        groups={}
        for bid,value in values:
            if bid in blocked or not value:continue
            groups.setdefault(value,{}).setdefault(eligible[bid]["category"],[]).append(bid)
        for group in groups.values():
            ebooks=group.get("ebook",[])
            audio=group.get("audio",[])
            if len(ebooks)==len(audio)==1:
                pair(ebooks[0],audio[0])

    match(locations.items())
    match((bid,(title,author) if title and author else None)
          for bid,b in eligible.items()
          for title,author in [(curation.normalized(b["title"]),curation.normalized(
              " ".join(a["name"] for a in b["authors"])))])


def companion_choices(db, book):
    row = db.execute("SELECT category FROM books WHERE id=? AND merged_into IS NULL", (book,)).fetchone()
    if not row or row[0] not in ("audio", "ebook"):
        raise ValueError("Ein E-Book oder Hörbuch auswählen.")
    other_kind = "ebook" if row[0] == "audio" else "audio"
    folders = {}
    for source, bid, kind in db.execute("""SELECT s.source,b.id,b.category FROM scanned_media s
            JOIN books b ON b.id=s.book WHERE b.merged_into IS NULL AND b.category IN ('ebook','audio')"""):
        path = Path(source)
        if kind == "audio" and path.suffix.lower() in AUDIO:
            continue  # Loose audio files at the collection root do not identify a title folder.
        folder = path.parent if kind == "ebook" else path
        folders.setdefault(folder, {}).setdefault(kind, set()).add(bid)
    nearby = set()
    unambiguous = set()
    for members in folders.values():
        if book in members.get(row[0], ()):
            candidates = members.get(other_kind, set())
            nearby.update(candidates)
            if len(candidates) == 1 and len(members[row[0]]) == 1:
                unambiguous.update(candidates)
    choices = [dict(r) for r in db.execute("""SELECT id,title,author FROM books
        WHERE merged_into IS NULL AND category=? ORDER BY title COLLATE NOCASE,id""", (other_kind,))]
    for choice in choices:
        choice["sameFolder"] = choice["id"] in nearby
    return {"choices": choices, "suggested": next(iter(nearby)) if nearby == unambiguous and len(nearby)==1 else None}


def revision(db):
    return tuple(db.execute("""SELECT coalesce(max(id),0),count(*),
        (SELECT coalesce(max(id),0) FROM podcast_feeds),(SELECT count(*) FROM podcast_feeds),
        (SELECT coalesce(max(checked),0) FROM podcast_feeds),
        (SELECT coalesce(max(value),'') FROM server_settings WHERE key='catalog_revision') FROM editions""").fetchone())


def podcast_subscriptions(db):
    return [dict(id=row["id"],key=hashlib.sha256(row["url"].encode()).hexdigest(),show=row["title"],
                 creator=row["creator"],cover=bool(row["art"]))
            for row in db.execute("""SELECT f.id,f.url,f.title,f.creator,a.feed AS art FROM podcast_feeds f
                                     LEFT JOIN podcast_art a ON a.feed=f.id ORDER BY f.title COLLATE NOCASE,f.id""")]


def stats(db,owner):
    imported = [dict(r) for r in db.execute("""SELECT source,book,episode,max(title) AS title,sum(seconds) AS seconds
        FROM abs_sessions WHERE owner=? GROUP BY source,book,episode ORDER BY seconds DESC""",(owner,))]
    positions = [dict(r) for r in db.execute("""SELECT p.*, coalesce((SELECT max(s.title) FROM abs_sessions s
        WHERE s.owner=p.owner AND s.source=p.source AND s.book=p.book AND s.episode=p.episode),nullif(p.label,''),p.book) AS title
        FROM abs_progress p WHERE p.owner=? ORDER BY title""",(owner,))]
    native = [dict(r) for r in db.execute("""SELECT coalesce(b.title,s.archived_title) AS title,s.kind,sum(s.seconds) AS seconds FROM sessions s
        LEFT JOIN editions e ON s.edition=e.id LEFT JOIN books b ON e.book=b.id WHERE s.owner=?
        GROUP BY b.id,s.archived_title,s.kind ORDER BY seconds DESC""",(owner,))]
    return dict(imported=imported,positions=positions,native=native,**merged(db,owner))


@lru_cache(maxsize=1)
def browser_bundle():
    scripts = ('locale.js', 'app.js', 'reading.js', 'workspace.js', 'passage.js', 'dashboard.js', 'preferences.js', 'collection.js', 'controls.js', 'studio.js')
    return b"\n;\n".join((ROOT/"web"/name).read_bytes() for name in scripts)


class Handler(BaseHTTPRequestHandler):
    def web_cookie(self,value,path="/",expired=False):
        # The proxy may remove the public mount point on the way to this server.
        if not isinstance(path,str) or not re.fullmatch(r"/(?:[A-Za-z0-9._~%+@-]+/)*",path) or any(p in (".","..") for p in path.split("/")):
            raise ValueError("Ungültiger Anwendungspfad.")
        secure="; Secure" if urlsplit(self.headers.get("Origin","")).scheme=="https" else ""
        age="; Max-Age=0" if expired else ""
        return f"audilege={value}; Path={path}; HttpOnly; SameSite=Strict{secure}{age}"

    server_version = "Audilege/"+maintenance.VERSION
    timeout = 120
    def log_message(self,fmt,*args):
        pass

    @property
    def lib(self):
        return self.server.library

    def catalog_roots(self):
        inbox = getattr(self.server,"inbox",None)
        return (("collection",inbox.linked),("inbox",inbox.root)) if inbox else ()

    def respond(self,status,mime,size,extra=()):
        self.send_response(status)
        for k,v in dict([("Content-Type",mime),("Content-Length",str(size)),("Cache-Control","no-store"),
                    ("X-Content-Type-Options","nosniff"),("Referrer-Policy","no-referrer"),*extra]).items():
            self.send_header(k,v)
        self.end_headers()

    def output(self,data,status=200,extra=()):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.respond(status,"application/json; charset=utf-8",len(raw),extra)
        if self.command!="HEAD":
            self.wfile.write(raw)

    def stream(self,file,mime,sandbox=True,download=False):
        size=file.stat().st_size
        with file.open("rb") as stream:
            return self.stream_open(stream,size,mime,sandbox,download)

    def stream_open(self,f,size,mime,sandbox=True,download=False):
        start,end=0,size-1
        headers=[("Accept-Ranges","bytes")]
        if sandbox:
            headers += [("Content-Security-Policy","sandbox; default-src 'none'")]
        if download:
            headers += [("Content-Disposition",'attachment; filename="audilege.epub"')]
        ranges=self.headers.get("Range")
        if ranges:
            m=re.fullmatch(r"bytes=(\d*)-(\d*)",ranges)
            if m and any(m.groups()):
                a,b=m.groups()
                start=int(a) if a else max(0,size-int(b))
                end=min(size-1,int(b)) if a and b else size-1
            if not m or not any(m.groups()) or not 0<=start<=end<size:
                return self.output({},416,[("Content-Range",f"bytes */{size}")])
            headers += [("Content-Range",f"bytes {start}-{end}/{size}")]
        self.respond(206 if ranges else 200,mime,end-start+1,headers)
        if self.command!="HEAD":
            if end>=start:
                f.seek(start)
                remaining=end-start+1
                while remaining:
                    chunk=f.read(min(remaining,256*1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining-=len(chunk)

    def artwork(self,source,mime,small,versioned=False):
        import io
        isfile=isinstance(source,Path)
        if isfile:
            stat=source.stat()
            key=hashlib.sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}:{small}".encode()).hexdigest()
        else:key=hashlib.sha256(source+str(small).encode()).hexdigest()
        tag='"'+key+'"'
        policy="private, max-age=3600" if versioned else "private, no-cache"
        headers=[("ETag",tag),("Cache-Control",policy),("Content-Security-Policy","sandbox; default-src 'none'")]
        if self.headers.get("If-None-Match")==tag:
            self.send_response(304)
            for name,value in headers:self.send_header(name,value)
            self.end_headers();return
        cache=self.lib.data/"thumbnails"/(key+".jpg")
        if small and cache.is_file():source=cache;mime="image/jpeg";isfile=True
        elif small:
            try:
                from PIL import Image
                with Image.open(source if isfile else io.BytesIO(source)) as picture:
                    if max(picture.size)>360 and picture.width*picture.height<=40_000_000:
                        picture.thumbnail((360,360))
                        image=io.BytesIO();picture.convert("RGB").save(image,"JPEG",quality=84)
                        source=image.getvalue();isfile=False;mime="image/jpeg"
                        cache.parent.mkdir(exist_ok=True)
                        tmp=cache.with_suffix("."+uuid.uuid4().hex)
                        try:tmp.write_bytes(source);tmp.replace(cache)
                        finally:tmp.unlink(missing_ok=True)
            except (ImportError,OSError,ValueError):pass
        size=source.stat().st_size if isfile else len(source)
        self.respond(200,mime,size,headers)
        if self.command!="HEAD":
            if isfile:
                with source.open("rb") as f:shutil.copyfileobj(f,self.wfile)
            else:self.wfile.write(source)

    def length(self,limit):
        n=int(self.headers.get("Content-Length",-1))
        if not 0<=n<=limit:
            raise ValueError("Ungültige Dateigröße.")
        return n

    def body(self):
        if self.headers.get_content_type()!="application/json":
            raise ValueError("JSON erwartet.")
        return json.loads(self.rfile.read(self.length(32*1024**2)))

    def cookies(self):
        cookie=SimpleCookie()
        cookie.load(self.headers.get("Cookie",""))
        return cookie["audilege"].value if "audilege" in cookie else ""

    def route(self):
        method="GET" if self.command=="HEAD" else self.command
        parts=urlsplit(self.path)
        path=parts.path
        qs=parse_qs(parts.query)
        def param(key,default=None):
            return qs.get(key,[default])[0]
        if method!="GET" and self.headers.get("Origin") and urlsplit(self.headers["Origin"]).netloc!=self.headers.get("Host"):
            return self.output({"error":"Fremder Ursprung."},403)
        assets={"/":"index.html","/style.css":"style.css","/interface.css":"interface.css","/app.js":"app.js","/workspace.js":"workspace.js","/reading.js":"reading.js","/audilege.webp":"audilege.webp","/icon.webp":"icon.webp"}
        for name in ("shell.css","passage.js","dashboard.js","preferences.js","collection.js","studio.js","controls.js","locale.js","collection.css"):
            assets["/"+name]=name
        if method=="GET" and path=="/audilege-ui.js":
            payload=browser_bundle()
            self.respond(200,"application/javascript; charset=utf-8",len(payload))
            if self.command!="HEAD":self.wfile.write(payload)
            return
        if method=="GET" and path in assets:
            f=ROOT/"web"/assets[path]
            return self.stream(f,mimetypes.guess_type(f.name)[0] or "application/octet-stream",False)
        with self.lib.db() as db:
            if path.startswith("/web/recovery/") and method=="POST":
                return self.output(maintenance.public_account(self.lib,db,path.rsplit("/",1)[1],self.body(),self.client_address[0]))
            if path in ("/api/v1/auth/login","/web/login","/api/v1/auth/refresh") and method=="POST":
                data=self.body()
                device=uuid.uuid4().hex
                if path.endswith("refresh"):
                    db.execute("BEGIN IMMEDIATE")
                    value=data["refreshToken"]
                    owner=self.lib.identity(db,value,"refresh")
                    prev=db.execute("SELECT device FROM device_tokens WHERE hash=?",(hashlib.sha256(value.encode()).digest(),)).fetchone()
                    if prev:device=prev[0]
                    db.execute("DELETE FROM tokens WHERE hash=?",(hashlib.sha256(value.encode()).digest(),))
                else:
                    owner=self.lib.login(db,data["username"],data["password"])
                if path=="/web/login":
                    cookie=self.lib.token(db,owner,"web",7*86400,device,self.headers.get("User-Agent","Browser"))
                    db.commit()
                    return self.output({"ok":True},extra=[("Set-Cookie",self.web_cookie(cookie,data.get("cookiePath","/")))])
                agent=self.headers.get("User-Agent","Audilege")
                result={"accessToken":self.lib.token(db,owner,"access",3600,device,agent),"refreshToken":self.lib.token(db,owner,"refresh",90*86400,device,agent)}
                db.commit()
                return self.output(result)
            bearer=self.headers.get("Authorization","")
            owner=self.lib.identity(db,bearer[7:],"access") if bearer.startswith("Bearer ") else self.lib.identity(db,self.cookies(),"web")
            if path.startswith("/web/admin/"):
                if method == "POST":
                    db.execute("BEGIN IMMEDIATE")
                if not db.execute("SELECT is_admin FROM users WHERE id=? AND enabled=1",(owner,)).fetchone()[0]:
                    return self.output({"error":"Hierfür sind Administratorrechte erforderlich."},403)
                if path.startswith("/web/admin/ai/"):
                    return self.output(curation.route(self,db,owner,path.rsplit("/",1)[1],method))
                if path=="/web/admin/directories" and method=="GET":
                    return self.output(maintenance.directory(param("path","")))
                if path=="/web/admin/system" and method=="GET":
                    return self.output({"smtp":maintenance.smtp_config(db),"version":maintenance.VERSION,"release":maintenance.REPO,
                        "daily":maintenance.get_setting(db,"daily_updates",False),"checked":maintenance.get_setting(db,"update_result",{}),
                        "retention":[dict(r) for r in db.execute("SELECT r.*,b.title FROM retention r JOIN jobs j ON j.id=r.job JOIN books b ON b.id=j.book ORDER BY job DESC")]})
                if path=="/web/admin/updates" and method=="GET":
                    return self.output(maintenance.update_info())
                if path=="/web/admin/updates" and method=="POST":
                    maintenance.setting(db,"daily_updates",self.body().get("enabled") is True)
                    db.commit();return self.output({})
                if path=="/web/admin/retention" and method=="POST":
                    result=maintenance.retention(self.lib,db,self.body());db.commit();return self.output(result)
                if path=="/web/admin/smtp" and method=="POST":
                    d=self.body()
                    if "test" in d:
                        maintenance.mail(maintenance.smtp_config(db),maintenance.address(d["test"]),"Audilege","SMTP-Verbindung erfolgreich.")
                    else:
                        cfg={k:str(d.get(k,"")).strip() for k in ("host","user","sender","url")}
                        cfg.update(port=int(d.get("port",587)),enabled=d.get("enabled") is True)
                        if cfg["enabled"]:
                            maintenance.address(cfg["sender"])
                            parsed=urlsplit(cfg["url"])
                            if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query or not cfg["host"] or not 1<=cfg["port"]<=65535:raise ValueError("Für die Wiederherstellung SMTP und eine öffentliche HTTPS-Adresse angeben.")
                        cfg["url"]=cfg["url"].rstrip("/")
                        maintenance.setting(db,"smtp",cfg)
                    db.commit();return self.output({})
                if path=="/web/admin/users" and method=="GET":
                    return self.output({"users":[dict(r) for r in db.execute("SELECT u.id,u.name,u.is_admin,u.enabled,r.email FROM users u LEFT JOIN recovery r ON u.id=r.owner ORDER BY u.name COLLATE NOCASE")],"self":owner})
                devices=re.fullmatch(r"/web/admin/users/(\d+)/devices",path)
                if devices and method in ("GET","POST"):
                    return self.output(maintenance.devices(db,int(devices[1]),self.body()["device"] if method=="POST" else None))
                if path=="/web/admin/jobs" and method=="GET":
                    return self.output({"jobs":[dict(r) for r in db.execute("SELECT j.id,b.title,j.state,j.note,j.started_at,j.phase_at,j.phase_progress FROM jobs j JOIN books b ON b.id=j.book ORDER BY j.id DESC LIMIT 100")]})
                retry_admin=re.fullmatch(r"/web/admin/jobs/(\d+)/retry",path)
                if retry_admin and method=="POST":
                    self.body()
                    jid=int(retry_admin[1]);job=db.execute("SELECT owner FROM jobs WHERE id=?",(jid,)).fetchone()
                    if not job:raise KeyError(jid)
                    db.commit();self.lib.retry_job(job[0],jid);return self.output({},202)
                if path=="/web/admin/inbox" and method in ("GET","POST"):
                    if method=="POST":
                        d=self.body()
                        db.commit()
                        if "linkedFolder" in d:self.server.inbox.change_linked(d["linkedFolder"])
                        elif "folder" in d:self.server.inbox.change_folder(d["folder"])
                        else:self.server.inbox.request()
                    return self.output(self.server.inbox.status())
                if path=="/web/admin/users" and method=="POST":
                    d=self.body()
                    self.lib.create_user(db,d["name"],d["password"],d.get("admin") is True)
                    db.commit()
                    return self.output({},201)
                account=re.fullmatch(r"/web/admin/users/(\d+)",path)
                if account and method=="POST":
                    uid=int(account[1]);d=self.body()
                    row=db.execute("SELECT enabled,is_admin FROM users WHERE id=?",(uid,)).fetchone()
                    if not row:
                        raise KeyError("Konto unbekannt.")
                    enabled=d.get("enabled",bool(row["enabled"]));admin=d.get("admin",bool(row["is_admin"]))
                    if not isinstance(enabled,bool) or not isinstance(admin,bool):
                        raise ValueError("Ungültige Kontoeinstellung.")
                    if uid==owner and (not admin or not enabled):
                        raise ValueError("Das eigene Administratorkonto muss aktiv bleiben.")
                    if d.get("password"):
                        db.execute("UPDATE users SET salt=?,digest=? WHERE id=?",(*self.lib.password_hash(d["password"]),uid))
                    if d.get("password") or not enabled or admin != bool(row["is_admin"]):
                        db.execute("DELETE FROM tokens WHERE owner=?",(uid,))
                    db.execute("UPDATE users SET enabled=?,is_admin=? WHERE id=?",(enabled,admin,uid))
                    db.commit()
                    return self.output({})
                if path in ("/web/admin/rss/preview","/web/admin/rss/import") and method=="POST":
                    d=self.body()
                    db.commit()
                    result=preview(self.lib,d["url"]) if path.endswith("preview") else import_episode(self.lib,owner,d["url"],d["guid"])
                    return self.output(result)
                if path=="/web/admin/rss/subscribe" and method=="POST":
                    url=self.body()["url"].strip()
                    db.commit()
                    return self.output(self.server.subscriptions.subscribe(url,owner),202)
                if path=="/web/admin/rss/unsubscribe" and method=="POST":
                    db.execute("DELETE FROM podcast_feeds WHERE id=?",(int(self.body()["id"]),))
                    db.commit()
                    return self.output({})
                if path=="/web/admin/rss/feeds" and method=="GET":
                    return self.output([dict(r) for r in db.execute("""SELECT url AS feed,title,id,checked,error FROM podcast_feeds
                        UNION ALL SELECT feed,max(show_title),NULL,NULL,'' FROM podcast_items WHERE feed NOT IN
                        (SELECT url FROM podcast_feeds) GROUP BY feed ORDER BY title""")])
                if path=="/web/admin/metadata/search" and method=="POST":
                    d=self.body()
                    db.commit()
                    return self.output(search(d["term"],d["sources"]))
                meta=re.fullmatch(r"/web/admin/metadata/(\d+)",path)
                if meta and method=="GET":
                    _,folder=self.lib.edition(db,int(meta[1]))
                    container=xml(folder,"META-INF/container.xml")
                    opf=container.find(".//{*}rootfile").attrib["full-path"]
                    tags=xml(folder,opf).find("{*}metadata")
                    result=epub_fields(tags)|{"title":tags.findtext("{*}title") or "","author":", ".join(t.text for t in tags.findall("{*}creator") if t.text)}
                    mime=json.loads((folder/"resources.json").read_text(encoding="utf8"))
                    if db.execute("SELECT category FROM books WHERE id=?",(int(meta[1]),)).fetchone()[0] in ("audio","podcast"):
                        from media_tools import audio_metadata,probe
                        first=next((name for name,typ in mime.items() if typ.startswith("audio/")),None)
                        if first:result.update(audio_metadata(probe(linked_media.track_path(folder,first,resource(folder,first)))))
                    return self.output(result)
                if meta and method=="POST":
                    data=self.body();book=int(meta[1])
                    image=None
                    if data.get("coverUrl") or data.get("coverData"):
                        db.commit()
                        image=fetch_cover(data["coverUrl"]) if data.get("coverUrl") else base64.b64decode(data["coverData"],validate=True)
                        mime=image_type(image)
                        db.execute("BEGIN IMMEDIATE")
                        if not db.execute("SELECT is_admin AND enabled FROM users WHERE id=?",(owner,)).fetchone()[0]:
                            return self.output({"error":"Administratorrechte erforderlich."},403)
                    row=db.execute("SELECT title,author,metadata FROM books WHERE id=? AND merged_into IS NULL",(book,)).fetchone()
                    if not row:
                        raise KeyError("Buch unbekannt.")
                    fields=json.loads(row["metadata"])
                    for k in ("title","author","publisher","year","series","volume","narrator","description","isbn","tags","source"):
                        if k in data and isinstance(data[k],str):
                            fields[k]=data[k].strip()[:2000]
                    title=fields.pop("title",row["title"]);author=fields.pop("author",row["author"])
                    if not title:
                        raise ValueError("Bitte einen Titel angeben.")
                    db.execute("UPDATE books SET title=?,author=?,metadata=? WHERE id=?",(title,author,json.dumps(fields,ensure_ascii=False),book))
                    if image is not None:
                        if data.get("coverRole") in ("book","audio"):
                            db.execute("INSERT OR REPLACE INTO role_covers VALUES(?,?,?,?)",(book,data["coverRole"],mime,image))
                        else:db.execute("INSERT OR REPLACE INTO book_covers VALUES(?,?,?)",(book,mime,image))
                    elif data.get("resetRole") in ("book","audio"):
                        db.execute("DELETE FROM role_covers WHERE book=? AND role=?",(book,data["resetRole"]))
                    maintenance.setting(db,"catalog_revision",uuid.uuid4().hex)
                    updated=catalog(db,owner,book)[0]
                    db.commit()
                    return self.output({"cover":updated["cover"],"coverRevision":updated["coverRevision"]})
            if path=="/web/logout" and method=="POST":
                db.execute("DELETE FROM tokens WHERE hash=?",(hashlib.sha256(self.cookies().encode()).digest(),))
                db.commit()
                return self.output({},extra=[("Set-Cookie",self.web_cookie("",self.body().get("cookiePath","/"),expired=True))])
            if path=="/api/v1/auth/me" and method=="GET":
                return self.output({"username":db.execute("SELECT name FROM users WHERE id=?",(owner,)).fetchone()[0],"settings":{"timezone":"UTC"}})
            if path=="/web/library/revision" and method=="GET":
                return self.output(revision(db))
            if path=="/web/profile/devices" and method in ("GET","POST"):
                return self.output(maintenance.devices(db,owner,self.body()["device"] if method=="POST" else None))
            if path=="/web/player" and method in ("GET","POST"):
                result=maintenance.player(db,owner,self.body() if method=="POST" else None)
                db.commit();return self.output(result)
            if path=="/web/profile/email" and method=="POST":
                cfg=maintenance.smtp_config(db)
                if not cfg.get("enabled"):raise ValueError("E-Mail-Wiederherstellung ist deaktiviert.")
                addr=maintenance.address(self.body()["email"])
                db.execute("BEGIN IMMEDIATE")
                if not maintenance.rate(db,["verify:"+str(owner)]):raise ValueError("Bitte kurz warten.")
                db.execute("INSERT INTO recovery(owner,pending) VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET pending=excluded.pending",(owner,addr))
                maintenance.mail_link(db,owner,"verify",addr,cfg);db.commit();return self.output({})
            podcast_art=re.fullmatch(r"/web/podcasts/(\d+)/cover",path)
            if podcast_art and method=="GET":
                art=db.execute("SELECT mime,image FROM podcast_art WHERE feed=?",(int(podcast_art[1]),)).fetchone()
                if not art:raise KeyError("Kein Sendungscover vorhanden.")
                self.respond(200,art["mime"],len(art["image"]))
                if self.command!="HEAD":self.wfile.write(art["image"])
                return
            retry=re.fullmatch(r"/web/jobs/(\d+)/retry",path)
            if retry and method=="POST":
                self.body()
                self.lib.retry_job(owner,int(retry[1]))
                return self.output({},202)
            companion_route=re.fullmatch(r"/web/books/(\d+)/companions",path)
            if companion_route and method=="GET":
                return self.output(companion_choices(db,int(companion_route[1])))
            if path=="/web/library" and method=="GET":
                db.execute("BEGIN")
                jobs=[dict(r) for r in db.execute("SELECT j.id,j.book,b.title,j.state,j.note,j.started_at,j.phase_at,j.phase_progress FROM jobs j JOIN books b ON j.book=b.id WHERE owner=? ORDER BY j.id DESC LIMIT 12",(owner,))]
                account=db.execute("SELECT name,is_admin FROM users WHERE id=?",(owner,)).fetchone()
                return self.output({"books":catalog(db,owner,start=param("view")=="start",storage_roots=self.catalog_roots(),show_editions=True),"subscriptions":podcast_subscriptions(db),"jobs":jobs,"account":dict(account),"sources":SOURCES,"revision":revision(db),"version":maintenance.VERSION,
                    "links":[dict(r) for r in db.execute("SELECT * FROM library_links")]})
            if path=="/web/uploads" and method=="POST":
                name=str(param("name",""))[:200]
                ext=Path(name).suffix.lower()
                if ext not in AUDIO|{".epub"}:
                    raise ValueError("Dieses Dateiformat wird nicht unterstützt.")
                remaining=self.length(6*1024**3)
                key=uuid.uuid4().hex
                folder=self.lib.draft(owner,key)
                folder.mkdir(parents=True)
                try:
                    with (folder/("content"+ext)).open("wb") as f:
                        while remaining:
                            chunk=self.rfile.read(min(remaining,256*1024))
                            if not chunk:
                                raise ValueError("Upload unterbrochen.")
                            f.write(chunk)
                            remaining-=len(chunk)
                    (folder/"ready.json").write_text(json.dumps(dict(name=name,ext=ext)),encoding="utf8")
                except Exception:
                    shutil.rmtree(folder,ignore_errors=True)
                    raise
                return self.output({"upload":key})
            if path in ("/web/books","/web/align") and method=="POST":
                data=self.body()
                if path.endswith("align"):
                    self.lib.enqueue(owner,int(data["book"]),data["files"],data["language"],data.get("companion"))
                    result={"queued":True}
                else:
                    result={"id":self.lib.import_book(owner,data)}
                for key in data["files"]:
                    shutil.rmtree(self.lib.draft(owner,key),ignore_errors=True)
                return self.output(result,201)
            if path in ("/web/abs/preview","/web/abs/import") and method=="POST":
                payload=self.body()
                db.execute("BEGIN IMMEDIATE")
                result=apply_import(db,owner,payload,path.endswith("/import"))
                db.commit()
                return self.output(result)
            if path=="/web/statistics" and method=="GET":
                return self.output(stats(db,owner))
            if path=="/api/v1/books/query" and method=="POST":
                data=self.body()
                page,size=max(0,int(data["pagination"]["page"])),max(1,min(1000,int(data["pagination"]["size"])))
                rows=catalog(db,owner,storage_roots=self.catalog_roots(),show_editions=True)
                if data.get("filter"):
                    rows=sorted((b for b in rows if 0<b["readingProgress"]<100),key=lambda b:b["updatedAt"],reverse=True)
                return self.output(dict(items=rows[page*size:(page+1)*size],total=len(rows),sharedQueue=True))
            if path=="/api/v1/dashboard/scrollers/continue-reading" and method=="GET":
                rows=sorted((b for b in catalog(db,owner) if 0<b["readingProgress"]<100),key=lambda b:b["updatedAt"],reverse=True)
                return self.output({"books":rows[:50],"total":len(rows)})
            if path=="/api/v1/reading-progress":
                if method=="GET":
                    return self.output({"items":[get_progress(db,owner,int(param("fileId")))]})
                if method=="PUT":
                    entries=self.body()["writes"]
                    db.execute("BEGIN IMMEDIATE")
                    out=[save_progress(db,owner,r) for r in entries]
                    db.commit()
                    return self.output({"results":out})
            match=re.fullmatch(r"/api/v1/books/(\d+)(/thumbnail|/cover|/sessions)?",path)
            if match and method=="GET":
                book=int(match[1])
                suffix=match[2]
                edition,folder=self.lib.edition(db,book)
                if suffix=="/sessions":
                    page=max(1,int(param("page",1)))
                    args=(owner,book)
                    query=" FROM sessions s JOIN editions e ON e.id=s.edition WHERE s.owner=? AND e.book=?"
                    total=db.execute("SELECT count(*)"+query,args).fetchone()[0]
                    rows=db.execute("SELECT s.id,s.edition AS bookFileId,start AS startedAt,end AS endedAt,seconds AS durationSeconds,kind AS sessionType"+query+" ORDER BY start,s.id LIMIT 100 OFFSET ?",(*args,(page-1)*100))
                    return self.output(dict(page=page,total=total,items=[dict(r) for r in rows]))
                if suffix:
                    small=suffix=="/thumbnail" and param("size")=="360"
                    cover_book=db.execute("SELECT category,cover_revision FROM books WHERE id=?",(book,)).fetchone()
                    variant=param("art") or ("audio" if cover_book["category"] in ("audio","podcast") else "book")
                    versioned=param("rev")==f'{edition["id"]}-{cover_book["cover_revision"]}'
                    override=db.execute("SELECT mime,image FROM role_covers WHERE book=? AND role=?",(book,variant)).fetchone()
                    if override:
                        return self.artwork(override["image"],override["mime"],small,versioned)
                    if variant=="book" and edition["cover"]:
                        return self.artwork(resource(folder,edition["cover"]),mimetypes.guess_type(edition["cover"])[0] or "application/octet-stream",small,versioned)
                    if variant=="audio":
                        art=audio_art_path(folder)
                        if art:return self.artwork(art,mimetypes.guess_type(art.name)[0],small,versioned)
                        # Earlier merged editions retain the embedded artwork of the audio source.
                        for prev in db.execute("""SELECT e.folder FROM editions e JOIN books b ON e.book=b.id
                            WHERE (b.id=? OR b.merged_into=?) AND e.cover IN ('cover.jpg','cover.png','cover.webp') ORDER BY e.id DESC""",(book,book)):
                            source=source_audio_art(self.lib.data/"editions"/prev[0])
                            if source:return self.artwork(source[1],mimetypes.guess_type(source[0])[0],small,versioned)
                    custom=db.execute("SELECT mime,image FROM book_covers WHERE book=?",(book,)).fetchone()
                    if custom:
                        return self.artwork(custom["image"],custom["mime"],small,versioned)
                    if not edition["cover"]:
                        raise KeyError("Kein Cover vorhanden.")
                    return self.artwork(resource(folder,edition["cover"]),mimetypes.guess_type(edition["cover"])[0] or "application/octet-stream",small,versioned)
                detail=catalog(db,owner,book,storage_roots=self.catalog_roots())[0]
                if detail["category"] in ("audio","ebook"):
                    paired=next((item for item in catalog(db,owner,show_editions=True) if item["id"]==book),None)
                    if paired and paired.get("companionId"):
                        detail["companionId"]=paired["companionId"]
                for old in db.execute("SELECT id FROM editions WHERE book=? AND id<>? AND folder NOT IN (SELECT folder FROM trash WHERE target<>'library') ORDER BY id DESC",(book,edition["id"])):
                    detail["files"].append({"id":old[0],"role":"previous","format":"epub","filename":"previous.epub"})
                return self.output(detail)
            match=re.fullmatch(r"/api/v1/books/files/(\d+)/(sessions|download)",path)
            if match:
                edition=int(match[1])
                r=db.execute("SELECT folder FROM editions WHERE id=?",(edition,)).fetchone()
                if not r:
                    raise KeyError("Ausgabe unbekannt.")
                if match[2]=="download" and method=="GET":
                    with linked_media.downloadable(self.lib.data/"editions"/r[0]) as file:
                        return self.stream(file,"application/epub+zip",download=True)
                if match[2]=="sessions" and method=="POST":
                    d=self.body()
                    start,end=[datetime.fromisoformat(d[k].replace("Z","+00:00")) for k in ("startedAt","endedAt")]
                    duration=int(number(d["durationSeconds"],(end-start).total_seconds()+1))
                    if d["sessionType"] not in ("read","listen","tts"):
                        raise ValueError("Unbekannte Sitzungsart.")
                    db.execute("INSERT OR IGNORE INTO sessions(owner,edition,sid,start,end,seconds,kind) VALUES(?,?,?,?,?,?,?)",(owner,edition,d["sessionId"],d["startedAt"],d["endedAt"],duration,d["sessionType"]))
                    db.commit()
                    return self.output({})
            match=re.fullmatch(r"/web/editions/(\d+)|/api/v1/epub/(\d+)/(?:media-overlay/)?file/(.+)",path)
            if match and method=="GET":
                edition,folder=self.lib.edition(db,int(match[1] or match[2]),param("fileId"))
                if match[1]:
                    info=json.loads((folder/"index.json").read_text(encoding="utf8"))
                    return self.output({k:v for k,v in info.items() if k!="files"}|{"fileId":edition["id"]})
                files=json.loads((folder/"resources.json").read_text(encoding="utf8"))
                name=unquote(match[3])
                for _ in range(2):
                    if name in files:
                        break
                    name=unquote(name)
                mime=files[name]
                with linked_media.member(folder,name,resource(folder,name)) as (stream,size):
                    return self.stream_open(stream,size,mime)
            if path=="/api/v1/user-statistics/daily-reading" and method=="GET":
                return self.output([{"day":k,"readingSeconds":int(v)} for k,v in sorted(merged(db,owner)["days"].items())])
            if path=="/api/v1/user-statistics/summary" and method=="GET":
                items=catalog(db,owner)
                return self.output(dict(audilegeActivities=merged(db,owner)["activities"],trackedBooks=len(items),startedBooks=sum(b["readingProgress"]>0 for b in items),
                    inProgressBooks=sum(0<b["readingProgress"]<100 for b in items),completedBooks=sum(b["readingProgress"]>=100 for b in items)))
            self.output({"error":"Nicht gefunden."},404)

    def handle_api(self):
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except PermissionError:
            self.output({"error":"Bitte Benutzername und Passwort prüfen oder erneut anmelden."},401)
        except (KeyError,FileNotFoundError) as error:
            self.output({"error":"Datei, Datensatz oder erforderliches Feld fehlt."},404)
        except sqlite3.IntegrityError:
            self.output({"error":"Für dieses Buch läuft bereits ein Auftrag."},409)
        except (ValueError, TypeError, AttributeError, ET.ParseError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
            self.output({"error":str(error)[:250]},400)
        except Exception:
            import traceback
            traceback.print_exc()
            self.output({"error":"Serverfehler. Details im Serverfenster."},500)

    do_GET=do_HEAD=do_POST=do_PUT=handle_api


@contextmanager
def server_lock(data):
    with (data/".server.lock").open("a+b") as lock:
        lock.seek(0,2)
        if not lock.tell():
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            if sys.platform=="win32":
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("Für diesen Datenordner läuft bereits ein Audilege-Server.")
        yield


def main():
    parser=argparse.ArgumentParser(description="Audilege Server")
    default=Path(os.environ.get("LOCALAPPDATA",Path.home()/".local"/"share"))/"AudilegeServer"
    parser.add_argument("--data",type=Path,default=default)
    parser.add_argument("--medienordner",type=Path,help="Überwachter Ordner für EPUBs, Hörbücher und Podcasts")
    parser.add_argument("--bind",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8472)
    parser.add_argument("--add-user",action="store_true")
    parser.add_argument("--backup",type=Path,help="Offline-Sicherung in einen neuen Ordner schreiben")
    parser.add_argument("--restore",type=Path,help="Geprüfte Sicherung wiederherstellen und bisherigen Bestand aufbewahren")
    parser.add_argument("--reset-password",metavar="BENUTZER",help="Kennwort direkt am Server zurücksetzen")
    parser.add_argument("--open",action="store_true",help="Bibliothek im Standardbrowser öffnen")
    parser.add_argument("--setup-worker",action="store_true",help="Windows-Worker einrichten und prüfen, dann beenden")
    parser.add_argument("--ohne-worker",action="store_true",help="Windows-Server für die Wiedergabe ohne Worker-Einrichtung starten")
    parser.add_argument("--export-abs",nargs=2,metavar=("ADRESSE","DATEI"),help="Audiobookshelf-Statistik einmalig exportieren")
    parser.add_argument("--abs-assistent",action="store_true",help="Interaktiver Statistikexport")
    args=parser.parse_args()
    if args.export_abs or args.abs_assistent:
        from abs_history import main as export
        args_export=args.export_abs
        if args.abs_assistent:
            address=input("Audiobookshelf-Adresse: ").strip()
            folder=Path.home()/"Downloads"
            if not folder.is_dir():
                folder=Path.home()
            target=folder/("Audiobookshelf-Statistik-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".json")
            args_export=[address,str(target)]
        export(args_export)
        print("Exportdatei:",args_export[1])
        return
    def prepare():
        from windows_worker import prepare_worker
        try:
            prepare_worker(ROOT/"worker")
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            raise SystemExit(f"Worker-Einrichtung unterbrochen. {error}\nNach der Korrektur Start-Audilege.cmd erneut öffnen.") from None

    if args.setup_worker:
        if sys.platform != "win32":
            parser.error("--setup-worker ist für Windows. Unter Linux worker/install.sh verwenden.")
        prepare()
        return
    if args.backup or args.restore:
        args.data.mkdir(parents=True,exist_ok=True)
        with server_lock(args.data):print(maintenance.snapshots(args.data,args.backup or args.restore,bool(args.restore)))
        return
    lib=Library(args.data)
    if args.reset_password:
        with lib.db() as db:
            uid=db.execute("SELECT id FROM users WHERE name=?",(args.reset_password,)).fetchone()
            if not uid:raise SystemExit("Unbekanntes Konto.")
            pw=getpass("Neues Passwort: ")
            if pw!=getpass("Passwort wiederholen: "):raise SystemExit("Passwörter unterscheiden sich.")
            db.execute("UPDATE users SET salt=?,digest=? WHERE id=?",(*lib.password_hash(pw),uid[0]))
            db.execute("DELETE FROM tokens WHERE owner=?",(uid[0],))
            db.execute("DELETE FROM recovery_links WHERE owner=?",(uid[0],))
        return
    with lib.db() as db:
        empty=not db.execute("SELECT 1 FROM users").fetchone()
    if empty or args.add_user:
        print("Persönlichen Audilege-Zugang einrichten.")
        name=input("Benutzername: ")
        password=getpass("Passwort (mindestens 10 Zeichen): ")
        if password!=getpass("Passwort wiederholen: "):
            raise SystemExit("Passwörter unterscheiden sich.")
        lib.user(name,password)
        if args.add_user:
            return
    with server_lock(lib.data), ThreadingHTTPServer((args.bind,args.port),Handler) as http:
        with lib.db() as db:
            maintenance.reconcile_trash(lib,db)
            db.execute("UPDATE review_jobs SET state='failed',note='Server neu gestartet. Prüfung erneut starten.' WHERE state='running'")
        if sys.platform == "win32" and not args.ohne_worker:
            prepare()
        http.library=lib
        maintenance.start_update_checks(lib)
        http.inbox=Inbox(lib,args.medienordner)
        http.inbox.start()
        http.subscriptions=Subscriptions(lib)
        http.subscriptions.start()
        if not (sys.platform == "win32" and args.ohne_worker):
            lib.start_worker()
        address="127.0.0.1" if args.bind=="0.0.0.0" else args.bind
        url=f"http://{address}:{http.server_port}"
        print(f"Audilege läuft auf {url} · Daten: {lib.data}",flush=True)
        if args.open:
            import webbrowser
            webbrowser.open(url)
        try:
            http.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            http.subscriptions.stopped.set()
            http.subscriptions.wake.set()


if __name__=="__main__":
    main()
