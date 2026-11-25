"""RSS subscriptions and retention for the server's own podcast media."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import time
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

from media_tools import command
from metadata import image_type

KEEP = 5
INTERVAL = 15 * 60

TYPES={"audio/mpeg":".mp3","audio/mp3":".mp3","audio/mp4":".m4a","audio/x-m4a":".m4a","audio/ogg":".ogg","audio/flac":".flac","audio/wav":".wav"}
AUDIO_EXT={".mp3",".m4b",".m4a",".ogg",".wav",".flac"}


def http_url(value):
    p=urlsplit(value)
    if p.scheme not in ("http","https") or not p.hostname or p.username or p.password:
        raise ValueError("Bitte eine HTTP- oder HTTPS-Adresse ohne eingebettete Anmeldedaten angeben.")
    return value


class WebRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,http_url(newurl))


def fetch(url):
    try:
        return build_opener(WebRedirect()).open(Request(http_url(url),headers={"User-Agent":"Audilege-Server/0.2"}),timeout=45)
    except URLError as exc:
        raise ValueError("Der Feed oder die Mediendatei ist vom Server aus nicht erreichbar.") from exc


def episodes(url):
    with fetch(url) as response:
        data=response.read(4*1024**2+1)
        if len(data)>4*1024**2:raise ValueError("Der Feed ist zu groß.")
        base=response.geturl()
    channel=ET.fromstring(data).find("{*}channel")
    if channel is None:raise ValueError("Kein RSS-Podcastfeed gefunden.")
    show=(channel.findtext("{*}title") or "Podcast")[:300]
    creator=(channel.findtext("{*}author") or channel.findtext("{*}creator") or "")[:300]
    def artwork(node):
        for image in node.findall("{*}image")+node.findall("{*}thumbnail"):
            link=image.get("href") or image.get("url") or image.findtext("{*}url")
            if link:return urljoin(base,link)
        return ""
    show_image=artwork(channel)
    items={}
    for item in channel.findall("{*}item"):
        media=item.find("{*}enclosure")
        if media is None:media=item.find("{http://search.yahoo.com/mrss/}content")
        if media is None or not media.get("url"):continue
        src=http_url(urljoin(base,media.get("url")))
        ext=Path(urlsplit(src).path).suffix.lower()
        mime=media.get("type","").split(";")[0].lower()
        if mime.startswith("image/"):continue
        key=sha256((item.findtext("{*}guid") or src).encode()).hexdigest()
        date=(item.findtext("{*}pubDate") or item.findtext("{*}date") or "")[:60]
        published=None
        if date:
            try:
                try: stamp=parsedate_to_datetime(date)
                except ValueError: stamp=datetime.fromisoformat(date.replace("Z","+00:00"))
                published=int((stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp())
            except (ValueError,TypeError,OverflowError,OSError):pass
        if key not in items:
            items[key]=dict(guid=key,title=(item.findtext("{*}title") or show)[:300],src=src,
                            ext=ext if ext in AUDIO_EXT else TYPES.get(mime,""),date=date,published=published,
                            image=artwork(item) or show_image,length=media.get("length"))
    return show,creator,items,show_image


def preview(lib,url):
    show,creator,items,_=episodes(url)
    with lib.db() as db:
        seen={r[0] for r in db.execute("SELECT guid FROM podcast_items WHERE feed=?",(url,))}
        refresh_metadata(db,url,show,creator,items,seen)
    return {"show":show,"creator":creator,"episodes":[{"guid":k,"title":items[k]["title"],"date":items[k]["date"],"imported":k in seen} for k in newest(items)]}


def newest(items, stored=()):
    # RSS order breaks date ties and serves as the fallback for undated feeds.
    dates={key:item["published"] for key,item in items.items()}
    for key,published in stored:
        if dates.get(key) is None:dates[key]=published
    return sorted(dates,key=lambda k:(dates[k] is not None,dates[k] or 0),reverse=True)


def refresh_metadata(db,url,show,creator,items,known):
    db.executemany("""UPDATE podcast_items SET published=coalesce(?,published),show_title=?,creator=coalesce(nullif(?,''),creator)
                      WHERE feed=? AND guid=?""",[(items[k]["published"],show,creator,url,k) for k in known if k in items])


def import_episode(lib,owner,url,guid):
    with lib.db() as db:
        row=db.execute("SELECT book FROM podcast_items WHERE feed=? AND guid=?",(url,guid)).fetchone()
        if row:return {"id":row[0],"existing":True}
        if db.execute("SELECT 1 FROM podcast_feeds WHERE url=?",(url,)).fetchone():
            raise ValueError("Bei einem Abonnement lädt Audilege automatisch die fünf neuesten Folgen.")
    show,creator,items,_=episodes(url)
    if guid not in items:raise ValueError("Diese Folge ist im Feed nicht mehr verfügbar.")
    return download(lib,url,show,creator,items[guid])


def fetch_art(url):
    if url:
        try:
            with fetch(url) as response:image=response.read(5*1024**2+1)
            return image_type(image),image
        except (ValueError,OSError,HTTPException):pass
    return None


def download(lib,url,show,creator,ep,subscription=None,order=()):
    with TemporaryDirectory(dir=lib.data/"uploads",prefix="rss-") as staging:
        folder=Path(staging);source=folder/"enclosure"
        with fetch(ep["src"]) as response,source.open("xb") as dest:
            size=getattr(response,"headers",{}).get("Content-Length")
            if size is None and (ep.get("length") or "").isdigit() and int(ep["length"])>0:
                size=ep["length"]
            count=0
            while chunk:=response.read(256*1024):
                count+=len(chunk)
                if count>6*1024**3:raise ValueError("Die Mediendatei ist größer als 6 GB.")
                dest.write(chunk)
            if not count or (size is not None and count!=int(size)):
                raise ValueError("Die Mediendatei wurde unvollständig übertragen.")
        ext=ep["ext"] or ".mp3"
        target=folder/("content"+ext)
        if ep["ext"]:source.replace(target)
        else:
            with target.open("xb") as stream:
                subprocess.run(command(source,"--extract-audio"),stdout=stream,stderr=subprocess.DEVNULL,timeout=7200,check=True)
        art=fetch_art(ep["image"])
        podcast=dict(feed=url,guid=ep["guid"],show=show,creator=creator,published=ep["published"],subscription=subscription,order=order,art=art)
        try:
            book=lib.import_tracks([(target,ep["title"]+ext)],dict(category="podcast",title=ep["title"],author=show),podcast=podcast)
            return {"id":book}
        except sqlite3.IntegrityError:
            with lib.db() as db:
                row=db.execute("SELECT book FROM podcast_items WHERE feed=? AND guid=?",(url,ep["guid"])).fetchone()
            if row:return {"id":row[0],"existing":True}
            raise


def prune(db,url,order):
    """Retire complete editions in the publication transaction. Journal disk work for retry."""
    ranks={guid:i for i,guid in enumerate(order)}
    rows=db.execute("""SELECT p.guid,p.book,b.title FROM podcast_items p JOIN books b ON b.id=p.book
                       WHERE p.feed=? AND b.category='podcast' ORDER BY p.published DESC,p.book DESC""",(url,)).fetchall()
    for row in sorted(rows,key=lambda r:ranks.get(r["guid"],len(ranks)))[KEEP:]:
        book=row["book"]
        for edition,folder in db.execute("SELECT id,folder FROM editions WHERE book=?",(book,)):
            if not re.fullmatch("[0-9a-f]{32}",folder):
                raise ValueError("Ungültiger Medienordner der Podcastfolge.")
            db.execute("INSERT OR IGNORE INTO podcast_cleanup VALUES(?)",(folder,))
            db.execute("UPDATE sessions SET archived_title=?,edition=NULL WHERE edition=?",(row["title"],edition))
            db.execute("DELETE FROM progress WHERE edition=?",(edition,))
            for key,value in (("retired_book",book),("retired_edition",edition)):
                db.execute("""INSERT INTO server_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE
                              SET value=max(CAST(value AS INTEGER),CAST(excluded.value AS INTEGER))""",(key,value))
        db.execute("DELETE FROM editions WHERE book=?",(book,))
        db.execute("DELETE FROM book_covers WHERE book=?",(book,))
        db.execute("DELETE FROM podcast_items WHERE feed=? AND guid=?",(url,row["guid"]))
        db.execute("DELETE FROM books WHERE id=?",(book,))


def cleanup(lib):
    base=lib.data/"editions"
    if base.resolve()!=base:return
    with lib.db() as db:
        folders=[row[0] for row in db.execute("SELECT folder FROM podcast_cleanup")]
    for name in folders:
        path=base/name
        if not re.fullmatch("[0-9a-f]{32}",name) or path.resolve()!=path or path.parent!=base:continue
        try:shutil.rmtree(path)
        except FileNotFoundError:pass
        except OSError:continue  # On Windows a player can still hold an open media handle.
        with lib.db() as db:db.execute("DELETE FROM podcast_cleanup WHERE folder=?",(name,))


class Subscriptions:
    def __init__(self,lib):
        self.lib=lib
        self.wake=Event()
        self.stopped=Event()

    def subscribe(self,url,owner):
        show,creator,_,_=episodes(url)
        with self.lib.db() as db:
            db.execute("""INSERT INTO podcast_feeds(url,title,creator,owner) VALUES(?,?,?,?)
                          ON CONFLICT(url) DO NOTHING""",(url,show,creator,owner))
        self.wake.set()
        return {"title":show}

    def sync(self,feed):
        url=feed["url"]
        show,creator,items,show_image=episodes(url)
        with self.lib.db() as db:
            cached=db.execute("SELECT source FROM podcast_art WHERE feed=?",(feed["id"],)).fetchone()
        art=fetch_art(show_image) if show_image and (not cached or cached[0]!=show_image) else None
        with self.lib.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM podcast_feeds WHERE id=?",(feed["id"],)).fetchone():return
            if art:
                db.execute("INSERT OR REPLACE INTO podcast_art VALUES(?,?,?,?)",(feed["id"],show_image,*art))
            elif not show_image:
                db.execute("DELETE FROM podcast_art WHERE feed=?",(feed["id"],))
            stored=dict(db.execute("SELECT guid,published FROM podcast_items WHERE feed=? ORDER BY book DESC",(url,)))
            refresh_metadata(db,url,show,creator,items,stored)
            db.execute("UPDATE podcast_feeds SET title=?,creator=? WHERE id=?",(show,creator,feed["id"]))
        if not items:return
        order=newest(items,stored.items())
        failed=False
        for key in order[:KEEP]:
            if key not in stored:
                try:
                    download(self.lib,url,show,creator,items[key],feed["id"],order)
                except (ValueError,OSError,HTTPException,subprocess.SubprocessError):
                    failed=True
                else:cleanup(self.lib)
        if failed:raise ValueError("Mindestens eine Folge ist noch nicht vollständig geladen.")
        with self.lib.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM podcast_feeds WHERE id=?",(feed["id"],)).fetchone():prune(db,url,order)
        cleanup(self.lib)

    def run_due(self):
        cleanup(self.lib)
        with self.lib.db() as db:
            feeds=db.execute("SELECT * FROM podcast_feeds WHERE due<=? ORDER BY due,id",(time(),)).fetchall()
        for feed in feeds:
            if self.stopped.is_set():return
            try:
                self.sync(feed)
                error=""
            except Exception:
                # Signed feed and enclosure URLs must not be copied into status messages.
                error="Abruf unvollständig. Audilege versucht es in fünf Minuten erneut."
            with self.lib.db() as db:
                db.execute("UPDATE podcast_feeds SET due=?,checked=?,error=? WHERE id=?",
                           (int(time())+(300 if error else INTERVAL),int(time()),error,feed["id"]))

    def start(self):
        # Called under the server's exclusive data-directory lock, before accepting requests.
        with self.lib.db() as db:
            db.execute("""INSERT OR IGNORE INTO podcast_cleanup SELECT folder FROM podcast_building
                          WHERE folder NOT IN (SELECT folder FROM editions)""")
            db.execute("DELETE FROM podcast_building")
        uploads=self.lib.data/"uploads"
        if uploads.resolve()==uploads:
            for partial in uploads.glob("rss-*"):
                if re.fullmatch(r"rss-[a-z0-9_]{8}",partial.name) and partial.resolve()==partial and partial.is_dir():
                    shutil.rmtree(partial,ignore_errors=True)
        def loop():
            while not self.stopped.is_set():
                self.wake.clear()
                try:self.run_due()
                except (sqlite3.Error,OSError):pass
                self.wake.wait(30)
        Thread(target=loop,name="Audilege-Podcasts",daemon=True).start()
