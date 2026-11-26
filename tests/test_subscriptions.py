"""Use fictional RSS feeds to exercise real imports, cleanup and restart on disk."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import wave

import test_server
from library import Library
from podcasts import Subscriptions, audible_podcast, cleanup, import_episode, newest, official_artwork, preview
from server import catalog, podcast_subscriptions, revision, stats


class Response(io.BytesIO):
    def __init__(self, body, url, size=None):
        super().__init__(body)
        self.url=url
        self.headers={} if size is None else {"Content-Length":str(size)}

    def geturl(self):
        return self.url


class SubscriptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib=Library(self.tmp.name)
        self.worker=Subscriptions(self.lib)
        self.feeds={"https://a.example/rss":[1,4,3,5,2],"https://b.example/rss":[2,1]}
        self.bad=set()
        self.audio_requests=[]
        body=io.BytesIO()
        with wave.open(body,"wb") as wav:
            wav.setparams((1,2,8000,0,"NONE","NONE"))
            wav.writeframes(bytes(16000))
        self.audio=body.getvalue()
        mocked=patch("podcasts.fetch",side_effect=self.fetch)
        mocked.start()
        self.addCleanup(mocked.stop)
        public=patch("podcasts.public_artwork_request",side_effect=OSError)
        public.start()
        self.addCleanup(public.stop)

    def fetch(self,url):
        if url in self.feeds:
            entries="".join(f'<item><guid>id-{n}</guid><title>Folge {n}</title><pubDate>{n:02} Nov 2026 12:00:00 +0100</pubDate><enclosure url="/{n}.wav" type="audio/wav"/></item>' for n in self.feeds[url])
            return Response(('<rss><channel><title>Testsendung</title><author>Testredaktion</author>'+entries+'</channel></rss>').encode(),url)
        self.audio_requests.append(url)
        return Response(self.audio[:100] if url in self.bad else self.audio,url,len(self.audio))

    def sync(self,url):
        with self.lib.db() as db:feed=db.execute("SELECT * FROM podcast_feeds WHERE url=?",(url,)).fetchone()
        self.worker.sync(feed)

    def copies(self,url):
        with self.lib.db() as db:
            return {row[0]:(row[1],row[2],self.lib.data/"editions"/row[3]) for row in db.execute(
                "SELECT b.title,b.id,e.id,e.folder FROM podcast_items p JOIN books b ON p.book=b.id JOIN editions e ON b.edition=e.id WHERE feed=?",(url,))}

    def test_rollover_removes_media_but_keeps_history_other_feed_and_manual_files(self):
        a,b=self.feeds
        for url in (a,b):self.worker.subscribe(url,1)
        self.worker.run_due()
        old=self.copies(a)["Folge 1"];others=self.copies(b)
        source=Path(self.tmp.name)/"user-import.wav";source.write_bytes(self.audio)
        manual=self.lib.import_tracks([(source,source.name)],{"category":"podcast","title":"Unabhängig"})
        with self.lib.db() as db:
            db.execute("INSERT INTO sessions(owner,edition,sid,start,end,seconds,kind) VALUES(1,?,'s','2026-11-01','2026-11-01',12,'listen')",(old[1],))
        self.feeds[a].extend([6,6,7])
        self.lib=Library(self.tmp.name);self.worker=Subscriptions(self.lib)
        self.sync(a)
        self.assertEqual(set(self.copies(a)),{f"Folge {i}" for i in range(3,8)})
        self.assertFalse(old[2].exists())
        self.assertEqual(self.copies(b),others)
        self.assertTrue(source.is_file())
        with self.lib.db() as db:
            self.assertEqual(len(catalog(db,1)),8)
            self.assertEqual(catalog(db,1,manual)[0]["id"],manual)
            self.assertEqual(stats(db,1)["native"][0]["seconds"],12)
            self.assertFalse(db.execute("SELECT 1 FROM editions WHERE id=?",(old[1],)).fetchone())
        n=len(self.audio_requests);self.sync(a)
        self.assertEqual(n,len(self.audio_requests))
        self.feeds[a]=[1,2]
        self.sync(a)
        self.assertEqual(n,len(self.audio_requests))

    def test_failed_download_does_not_evict_and_disk_cleanup_retries(self):
        url=next(iter(self.feeds));self.worker.subscribe(url,1);self.sync(url)
        before=self.copies(url);self.feeds[url].append(6);self.bad.add("https://a.example/6.wav")
        with self.assertRaises(ValueError):self.sync(url)
        self.assertEqual(self.copies(url),before)
        self.assertTrue(all(folder.is_dir() for _,_,folder in before.values()))
        self.bad.clear()
        with patch("podcasts.cleanup"):self.sync(url)
        retired=before["Folge 1"][2]
        self.assertTrue(retired.is_dir())
        with patch("podcasts.shutil.rmtree",side_effect=PermissionError()):cleanup(self.lib)
        self.assertTrue(retired.is_dir())
        cleanup(Library(self.tmp.name))
        self.assertFalse(retired.exists())

    def test_subscription_adopts_manual_entries_only_for_selected_url(self):
        a,b=self.feeds
        self.feeds[a]=list(range(1,8))
        for url in (a,b):
            for e in preview(self.lib,url)["episodes"]:
                import_episode(self.lib,1,url,e["guid"])
        self.worker.subscribe(a,1);self.worker.subscribe(a,1)
        self.sync(a)
        self.assertEqual(len(self.copies(a)),5)
        self.assertEqual(len(self.copies(b)),2)
        with self.lib.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM podcast_feeds").fetchone()[0],1)

    def test_feed_order_is_stable_for_missing_and_equal_dates(self):
        entries={k:{"published":v} for k,v in [("third",5),("first",8),("equal",8),("undated",None)]}
        self.assertEqual(newest(entries,[("missing",7),("older-undated",None)]),
                         ["first","equal","missing","third","undated","older-undated"])

    def test_mirror_uses_one_official_cover_for_all_episodes(self):
        url="https://a.example/rss"
        video="https://www.youtube.com/watch?v=abc123DEF45"
        image="https://is1-ssl.mzstatic.com/fixture"
        png=b"\x89PNG\r\n\x1a\nfixture"
        rss=f"""<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
            <title>Testsendung (YouTube)</title><itunes:image href="https://a.example/mirror-art.jpg"/>
            <item><guid>1</guid><title>Erste Folge</title><link>{video}</link><enclosure url="/1.wav" type="audio/wav"/>
                  <itunes:image href="https://i.ytimg.com/vi/abc123DEF45/0.jpg"/></item>
            <item><guid>2</guid><title>Zweite Folge</title><enclosure url="/2.wav" type="audio/wav"/></item>
            </channel></rss>"""
        def public(source,hosts,limit):
            if source.startswith("https://api.audible.de/"):return b'{"products":[]}'
            if source.startswith("https://itunes.apple.com/"):
                return json.dumps({"results":[dict(collectionName="Testsendung",feedUrl="https://official.example/rss",
                                                   artworkUrl600=image)]}).encode()
            self.assertEqual(source,image)
            return png
        def fetch(source):
            if source==url:return Response(rss.encode(),url)
            self.assertIn(source,{"https://a.example/1.wav","https://a.example/2.wav"})
            return Response(self.audio,source,len(self.audio))
        with patch("podcasts.fetch",side_effect=fetch), \
             patch("podcasts.public_artwork_request",side_effect=public) as request:
            self.worker.subscribe(url,1)
            self.sync(url)
            self.sync(url)
            self.assertEqual(request.call_count,3)
            with self.lib.db() as db:
                self.assertTrue(podcast_subscriptions(db)[0]["cover"])
                self.assertEqual(db.execute("SELECT count(*) FROM book_covers").fetchone()[0],0)
                self.assertTrue(all(book["cover"] for book in catalog(db,1)))
                db.execute("UPDATE podcast_feeds SET art_checked=0")
            request.side_effect=OSError()
            self.sync(url)
        with self.lib.db() as db:
            self.assertEqual(tuple(db.execute("SELECT source,mime,image FROM podcast_art").fetchone()),(image,"image/png",png))

    def test_public_catalog_requires_exact_feed_or_matching_show_and_creator(self):
        image="https://is1-ssl.mzstatic.com/fixture.jpg"
        rows={"results":[{"feedUrl":"https://feeds.example/rss","collectionName":"Testsendung",
                         "artistName":"Testredaktion","artworkUrl600":image}]}
        data=json.dumps(rows).encode()
        with patch("podcasts.public_artwork_request",return_value=data) as request:
            self.assertEqual(official_artwork("Testsendung","Andere Redaktion","https://other.example/rss","",False),("",None))
            self.assertEqual(request.call_count,1)
        for title,author,feed in [("Testsendung","Testredaktion","https://local.example/rss"),
                                  ("Anderer Titel","Andere Redaktion","https://feeds.example/rss")]:
            with patch("podcasts.public_artwork_request",side_effect=[data,b"\xff\xd8\xfffixture"]):
                self.assertEqual(official_artwork(title,author,feed,"",False),(image,("image/jpeg",b"\xff\xd8\xfffixture")))

    def test_audible_episode_metadata_requires_the_right_parent(self):
        parent=dict(asin="parent",title="Testsendung",content_delivery_type="PodcastParent",
                    product_images={"500":"https://m.media-amazon.com/fixture.jpg"})
        episode=dict(asin="episode",title="Treffer – eine Folge",content_delivery_type="PodcastEpisode",
                     publisher_summary="<p>Beschreibung von Audible</p>",release_date="2026-11-26",
                     relationships=[dict(asin="parent",relationship_to_product="parent")])
        other=episode|dict(asin="other",relationships=[dict(asin="unrelated",relationship_to_product="parent")])
        result=json.dumps({"products":[parent,episode,other]}).encode()
        with patch("podcasts.public_artwork_request",return_value=result):
            image,metadata=audible_podcast("Testsendung (YouTube)",{"matched":"Treffer - eine Folge","unknown":"Andere Folge"})
        self.assertEqual(image,parent["product_images"]["500"])
        self.assertEqual(metadata,{"matched":{"audibleAsin":"episode","description":"Beschreibung von Audible","year":"2026"}})

    def test_shelf_lists_only_subscriptions_including_empty_feeds(self):
        a,b=self.feeds
        import_episode(self.lib,1,b,preview(self.lib,b)["episodes"][0]["guid"])
        self.feeds[a]=[]
        with self.lib.db() as db:before=revision(db)
        self.worker.subscribe(a,1)
        self.sync(a)
        with self.lib.db() as db:
            rows=podcast_subscriptions(db)
            self.assertEqual([r["show"] for r in rows],["Testsendung"])
            self.assertNotIn("url",rows[0])
            self.assertNotEqual(catalog(db,1)[0]["podcast"]["key"],rows[0]["key"])
            self.assertNotEqual(before,revision(db))
            db.execute("DELETE FROM podcast_feeds")
            self.assertEqual(podcast_subscriptions(db),[])


class PodcastCoverTest(unittest.TestCase):
    setUp=test_server.ServerTest.setUp
    tearDown=test_server.ServerTest.tearDown
    call=test_server.ServerTest.call

    def test_existing_episode_uses_show_cover_on_web_and_android_routes(self):
        url="https://example.invalid/rss"
        png=b"\x89PNG\r\n\x1a\nshow"
        with self.lib.db() as db:
            for book in (1,2):
                db.execute("INSERT INTO books(id,title,author,category,edition) VALUES(?,?,?,'podcast',?)",
                           (book,f"Folge {book}","Testsendung",book))
                folder=f"{book:032x}"
                (self.lib.data/"editions"/folder).mkdir()
                db.execute("INSERT INTO editions VALUES(?,?,?,NULL)",(book,book,folder))
                db.execute("INSERT INTO podcast_items(feed,guid,book,show_title,metadata) VALUES(?,?,?,?,?)",
                           (url,str(book),book,"Testsendung",'{"description":"Offizielle Folge"}'))
                db.execute("INSERT INTO book_covers VALUES(?,?,?)",(book,"image/jpeg",b"old-thumbnail"))
            feed=db.execute("INSERT INTO podcast_feeds(url,title,creator,owner) VALUES(?,?,?,?)",
                            (url,"Testsendung","Testredaktion",1)).lastrowid
        with self.assertRaises(HTTPError) as missing:self.call("/api/v1/books/1/thumbnail",raw=True)
        self.assertEqual(missing.exception.code,404)
        with self.lib.db() as db:
            db.execute("INSERT INTO podcast_art VALUES(?,?,?,?)",(feed,"https://example.invalid/show.png","image/png",png))
        for route in (f"/web/podcasts/{feed}/cover","/api/v1/books/1/thumbnail?size=360","/api/v1/books/2/cover?medium=audio&strict=true"):
            self.assertEqual(self.call(route,raw=True)[2],png)
        self.assertEqual(self.call("/api/v1/books/1")["metadata"]["description"],"Offizielle Folge")
