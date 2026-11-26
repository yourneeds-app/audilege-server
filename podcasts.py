"""RSS subscriptions and retention for the server's own podcast media."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import time
from unicodedata import normalize
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET

from media_tools import command
from metadata import image_type, plain

KEEP = 5
INTERVAL = 15 * 60
ART_RETRY = 24 * 60 * 60
ART_REFRESH = 7 * ART_RETRY
ART_POLICY = "official-show-v1:"

# Some mirrored feeds shorten the show title or have several namesakes in Apple Podcasts.
OFFICIAL_FEEDS = {
    "pietcast": ("PietCast", "https://feeds.megaphone.fm/pietcast"),
    "mmo news": ("MMO News", "https://feed.podbean.com/mmonewspodcast/feed.xml"),
    "pc games podcast": ("PC Games Podcast", "https://podcast.audiocon.de/rss/e3b46afb420723b1696effa0ad7c85c8f59ca495"),
}

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
        for image in node.findall("{*}image"):
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
                            length=media.get("length"),description=plain(item.findtext("{*}description"),8000))
    channel_id=channel.findtext("{http://www.youtube.com/xml/schemas/2015}channelId") or ""
    channel_link=channel.findtext("{*}link") or ""
    youtube=youtube_channel(channel_id,channel_link)
    if not youtube:
        youtube=next((video for item in channel.findall("{*}item")
                      if (video:=youtube_video(item.findtext("{*}link") or ""))),"")
    mirrored=bool(youtube or re.search(r"\s*\(youtube\)\s*$",show,re.I) or youtube_art(show_image))
    return show,creator,items,show_image,mirrored


def preview(lib,url):
    show,creator,items,_,_=episodes(url)
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
    show,creator,items,show_image,mirrored=episodes(url)
    if guid not in items:raise ValueError("Diese Folge ist im Feed nicht mehr verfügbar.")
    audible_image,metadata=audible_podcast(show,{guid:items[guid]["title"]})
    _,art=official_artwork(show,creator,url,show_image,mirrored,audible_image)
    return download(lib,url,show,creator,items[guid],art=art,metadata=episode_metadata(items[guid],metadata.get(guid)))


def fetch_art(url):
    if url:
        try:
            with fetch(url) as response:
                if youtube_art(response.geturl()):return None
                image=response.read(5*1024**2+1)
            return image_type(image),image
        except (ValueError,OSError,HTTPException):pass
    return None


def youtube_channel(channel_id,link):
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}",channel_id):
        return "https://www.youtube.com/channel/"+channel_id
    try:parts=urlsplit(link)
    except ValueError:return ""
    if parts.hostname not in ("youtube.com","www.youtube.com","m.youtube.com"):
        return ""
    match=re.match(r"^(/(?:channel/UC[A-Za-z0-9_-]{22}|(?:user|c)/[^/]+|@[^/]+))(?:/|$)",parts.path)
    return "https://www.youtube.com"+match[1] if match else ""


def youtube_video(link):
    try:parts=urlsplit(link)
    except ValueError:return ""
    if parts.hostname in ("youtube.com","www.youtube.com","m.youtube.com") and parts.path=="/watch":
        video=parse_qs(parts.query).get("v",[""])[0]
    elif parts.hostname=="youtu.be":
        video=parts.path.strip("/")
    else:return ""
    return "https://www.youtube.com/watch?v="+video if re.fullmatch(r"[A-Za-z0-9_-]{11}",video) else ""


class ArtworkRedirect(HTTPRedirectHandler):
    def __init__(self,hosts):
        self.hosts=hosts

    def validate(self,url):
        parsed=urlsplit(http_url(url))
        if parsed.scheme!="https" or parsed.hostname not in self.hosts or parsed.port not in (None,443):
            raise ValueError("Unbekannter Anbieter für Podcastbilder.")
        return url

    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,self.validate(newurl))


def public_artwork_request(url,hosts,limit):
    redirect=ArtworkRedirect(hosts)
    req=Request(redirect.validate(url),headers={"User-Agent":"Audilege-Server","Accept-Language":"de,en;q=0.9"})
    with build_opener(redirect).open(req,timeout=6) as response:
        return response.read(limit+1)


def youtube_art(url):
    try:host=urlsplit(url).hostname or ""
    except ValueError:return False
    return host in {"ytimg.com","yt3.ggpht.com","yt3.googleusercontent.com"} or host.endswith(".ytimg.com")


def show_name(value):
    return re.sub(r"\s*\(youtube\)\s*$","",str(value or ""),flags=re.I).strip()


def title_key(value):
    return " ".join(re.findall(r"[^\W_]+",normalize("NFC",show_name(value)).casefold()))


def audible_podcast(show,titles):
    """Return a verified parent and metadata from episodes linked to that parent."""
    query_show=show_name(show)
    expected={title_key(query_show)}
    if title_key(query_show)=="mmo news":expected.add("mmo news dein mmorpg podcast")

    def products(term,limit):
        query=urlencode(dict(keywords=term,num_results=limit,image_sizes=500,
                            response_groups="product_attrs,product_desc,relationships,media,category_ladders"))
        host="api.audible.de"
        data=public_artwork_request("https://"+host+"/1.0/catalog/products?"+query,{host},3*1024**2)
        return json.loads(data).get("products",[])

    try:
        rows=products(query_show,25)
        parents={row["asin"]:row for row in rows if row.get("content_delivery_type")=="PodcastParent"
                 and row.get("asin") and title_key(row.get("title")) in expected}
        if len(parents)!=1:return "",{}
        parent_id,parent=next(iter(parents.items()))
        def episode(rows,key):
            matches={row["asin"]:row for row in rows if row.get("content_delivery_type")=="PodcastEpisode"
                     and row.get("asin") and title_key(row.get("title"))==key and any(
                         link.get("relationship_to_product")=="parent" and link.get("asin")==parent_id
                         for link in row.get("relationships",[]))}
            return next(iter(matches.values())) if len(matches)==1 else {}

        metadata={}
        for guid,title in titles.items():
            key=title_key(title)
            if not key:continue
            match=episode(rows,key)
            if not match:
                try:match=episode(products(title,6),key)
                except (ValueError,OSError,HTTPException):continue
            if not match:continue
            tags=[part.get("name") for ladder in match.get("category_ladders",[]) for part in ladder.get("ladder",[]) if part.get("name")]
            fields=dict(description=plain(match.get("publisher_summary") or match.get("merchandising_summary"),8000),
                        publisher=plain(match.get("publisher_name")),year=plain(match.get("release_date"))[:4],
                        tags=plain(", ".join(dict.fromkeys(tags))),audibleAsin=match["asin"])
            metadata[guid]={key:value for key,value in fields.items() if value}
        return (parent.get("product_images") or {}).get("500") or "",metadata
    except (ValueError,OSError,HTTPException,AttributeError,TypeError,KeyError):
        return "",{}


def official_artwork(show,creator,feed_url,feed_image,mirrored,audible_image=""):
    if not mirrored and (art:=fetch_art(feed_image)):
        return feed_image,art
    if audible_image:
        try:
            data=public_artwork_request(audible_image,{"m.media-amazon.com"},5*1024**2)
            return audible_image,(image_type(data),data)
        except (ValueError,OSError,HTTPException):pass
    def name(value):
        return " ".join(show_name(value).casefold().split())
    lookup,known_feed=OFFICIAL_FEEDS.get(name(show),(show,"")) if mirrored else (show,"")
    lookup=show_name(lookup)
    try:
        query=urlencode(dict(term=lookup,country="de",media="podcast",entity="podcast",limit=12))
        data=public_artwork_request("https://itunes.apple.com/search?"+query,{"itunes.apple.com"},512*1024)
        rows=json.loads(data).get("results",[])
        references={feed_url.rstrip("/")}
        if known_feed:references.add(known_feed.rstrip("/"))
        exact=[row for row in rows if (row.get("feedUrl") or "").rstrip("/") in references]
        titles=[row for row in rows if name(row.get("collectionName"))==name(show)]
        matches=exact or [row for row in titles if creator and name(row.get("artistName"))==name(creator)]
        if not matches and mirrored and not known_feed:
            # A mirror often repeats the title as its author. Use a catalogue
            # result only when the exact title identifies one feed.
            feeds={row["feedUrl"] for row in titles if row.get("feedUrl")}
            if len(feeds)==1:matches=[row for row in titles if row.get("feedUrl") in feeds]
        images={row.get("artworkUrl600") or row.get("artworkUrl100") for row in matches}-{None,""}
        if len(images)==1:
            source=images.pop()
            hosts={f"is{i}-ssl.mzstatic.com" for i in range(1,6)}
            image=public_artwork_request(source,hosts,5*1024**2)
            return source,(image_type(image),image)
    except (ValueError,OSError,HTTPException,AttributeError,TypeError):
        pass
    return "",None


def episode_metadata(item,audible):
    fields={"description":item["description"]} if item["description"] else {}
    return fields|(audible or {})


def download(lib,url,show,creator,ep,subscription=None,order=(),art=None,metadata=None):
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
        podcast=dict(feed=url,guid=ep["guid"],show=show,creator=creator,published=ep["published"],
                     subscription=subscription,order=order,art=art,metadata=metadata or {})
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
        show,creator,_,_,_=episodes(url)
        with self.lib.db() as db:
            db.execute("""INSERT INTO podcast_feeds(url,title,creator,owner) VALUES(?,?,?,?)
                          ON CONFLICT(url) DO NOTHING""",(url,show,creator,owner))
        self.wake.set()
        return {"title":show}

    def sync(self,feed):
        url=feed["url"]
        show,creator,items,show_image,mirrored=episodes(url)
        art_hint=ART_POLICY+sha256(json.dumps(["" if mirrored else show_image,mirrored,show,creator]).encode()).hexdigest()
        checked=int(time())
        with self.lib.db() as db:
            art_state=db.execute("SELECT art_checked,art_hint FROM podcast_feeds WHERE id=?",(feed["id"],)).fetchone()
            stored=db.execute("SELECT guid,published,metadata FROM podcast_items WHERE feed=? ORDER BY book DESC",(url,)).fetchall()
        if art_state is None:return
        known={row["guid"]:row["published"] for row in stored}
        previous={row["guid"]:json.loads(row["metadata"]) for row in stored}
        order=newest(items,known.items())
        refresh_art=art_state["art_hint"]!=art_hint or checked>=art_state["art_checked"]
        titles={key:items[key]["title"] for key in order[:KEEP] if key in items and
                (key not in known or (refresh_art and not previous[key].get("audibleAsin")))}
        audible_image,metadata=audible_podcast(show,titles) if titles or refresh_art else ("",{})
        source,art="",None
        if refresh_art:
            source,art=official_artwork(show,creator,url,show_image,mirrored,audible_image)
        with self.lib.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM podcast_feeds WHERE id=?",(feed["id"],)).fetchone():return
            if refresh_art:
                db.execute("UPDATE podcast_feeds SET art_checked=?,art_hint=? WHERE id=?",
                           (checked+(ART_REFRESH if art else ART_RETRY),art_hint,feed["id"]))
                if art:
                    db.execute("""INSERT INTO podcast_art VALUES(?,?,?,?) ON CONFLICT(feed) DO UPDATE
                                  SET source=excluded.source,mime=excluded.mime,image=excluded.image
                                  WHERE podcast_art.source<>excluded.source OR podcast_art.image<>excluded.image""",
                               (feed["id"],source,*art))
            stored_art=db.execute("SELECT mime,image FROM podcast_art WHERE feed=?",(feed["id"],)).fetchone()
            refresh_metadata(db,url,show,creator,items,known)
            for key in known.keys() & items.keys():
                if key not in metadata and previous[key].get("audibleAsin"):continue
                fields=episode_metadata(items[key],metadata.get(key))
                if fields and fields!=previous[key]:
                    db.execute("UPDATE podcast_items SET metadata=? WHERE feed=? AND guid=?",(json.dumps(fields),url,key))
            db.execute("UPDATE podcast_feeds SET title=?,creator=? WHERE id=?",(show,creator,feed["id"]))
        if not items:return
        failed=False
        for key in order[:KEEP]:
            if key not in known:
                try:
                    download(self.lib,url,show,creator,items[key],feed["id"],order,tuple(stored_art) if stored_art else None,
                             episode_metadata(items[key],metadata.get(key)))
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
            db.execute("DELETE FROM podcast_art WHERE feed IN (SELECT id FROM podcast_feeds WHERE art_hint NOT LIKE ?)",(ART_POLICY+"%",))
            db.execute("UPDATE podcast_feeds SET due=0 WHERE art_hint NOT LIKE ?",(ART_POLICY+"%",))
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
