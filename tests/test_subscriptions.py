"""Use fictional RSS feeds to exercise real imports, cleanup and restart on disk."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import test_server
from library import Library
from podcasts import Subscriptions, cleanup, import_episode, newest, preview
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
