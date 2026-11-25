import base64
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError
import os
import shutil
import subprocess
import wave

import test_server
from scanner import Inbox


class WorkspaceTest(TestCase):
    setUp=test_server.ServerTest.setUp
    tearDown=test_server.ServerTest.tearDown
    call=test_server.ServerTest.call
    upload=test_server.ServerTest.upload

    def test_roles_and_revoke(self):
        self.call("/web/admin/users",{"name":"reader","password":"fixture-reader"})
        users=self.call("/web/admin/users")
        reader=next(r["id"] for r in users["users"] if r["name"]=="reader")
        access=self.call("/api/v1/auth/login",{"username":"reader","password":"fixture-reader"})["accessToken"]
        headers={"Authorization":"Bearer "+access}
        with self.assertRaises(HTTPError) as error:self.call("/web/admin/users",headers=headers)
        self.assertEqual(error.exception.code,403)
        for path in ["/web/admin/ai/state","/web/admin/directories","/web/admin/system","/web/admin/users/1/devices"]:
            with self.assertRaises(HTTPError) as error:self.call(path,headers=headers)
            self.assertEqual(error.exception.code,403)
        self.assertEqual(len(self.call("/web/profile/devices",headers=headers)["items"]),1)
        with self.assertRaises(HTTPError):self.call("/web/admin/users/"+str(users["self"]),{"enabled":False})
        self.call("/web/admin/users/"+str(reader),{"enabled":False})
        with self.assertRaises(HTTPError) as error:self.call("/web/library",headers=headers)
        self.assertEqual(error.exception.code,401)

    def test_play_queue_is_shared_per_profile_and_can_be_reordered(self):
        with self.lib.db() as db:
            first=db.execute("INSERT INTO books(title,author,category) VALUES('Fiktiv A','Test','audio')").lastrowid
            second=db.execute("INSERT INTO books(title,author,category) VALUES('Fiktiv B','Test','podcast')").lastrowid
        self.call("/web/player",{"book":first,"kind":"queue"})
        self.call("/web/player",{"book":second,"kind":"queue"})
        self.call("/web/player",{"book":second,"kind":"promote"})
        self.assertEqual([(row["book"],row["title"]) for row in self.call("/web/player")["items"]],
                         [(second,"Fiktiv B"),(first,"Fiktiv A")])
        self.lib.user("zweites-profil","fixture-password")
        other=self.call("/api/v1/auth/login",{"username":"zweites-profil","password":"fixture-password"})["accessToken"]
        self.assertEqual(self.call("/web/player",headers={"Authorization":"Bearer "+other})["items"],[])
        remaining=self.call("/web/player",{"book":second,"kind":"queue","remove":True})["items"]
        self.assertEqual([row["book"] for row in remaining],[first])

    def test_bookmarks_are_shared_by_web_and_app_and_isolated_by_profile(self):
        book=self.call("/web/books",{"category":"ebook","files":[self.upload(test_server.epub(),"Test.epub")]})["id"]
        edition=self.call(f"/api/v1/books/{book}")["files"][0]["id"]
        path=f"/api/v1/books/{book}/bookmarks?fileId={edition}"
        web={"kind":"bookmark","book":book,"edition":edition,"chapter":0,"offset":12,"label":"Web"}
        self.call("/web/player",web)
        web_mark=self.call(path)["marks"][0]
        self.assertEqual(web_mark["label"],"Web")
        app={"key":"a714d29a-01de-48ab-9569-af2ec4d8bb5d","chapter":0,"offset":0,
             "label":"Android","cfi":"epubcfi(/6/2!/4/2/1:3)","audio_ms":1234}
        for _ in range(2):
            self.call(path,{"add":[app]})
        marks=self.call("/web/player")["marks"]
        self.assertEqual([m["label"] for m in marks],["Android","Web"])
        self.assertEqual((marks[0]["cfi"],marks[0]["audio_ms"]),(app["cfi"],1234))
        self.lib.user("zweites-profil","fixture-password")
        other=self.call("/api/v1/auth/login",{"username":"zweites-profil","password":"fixture-password"})["accessToken"]
        headers={"Authorization":"Bearer "+other}
        self.assertEqual(self.call(path,{"remove":[web_mark["key"],app["key"]]},headers=headers)["marks"],[])
        self.call(path,{"remove":[web_mark["key"]]})
        self.assertEqual([m["label"] for m in self.call("/web/player")["marks"]],["Android"])
        self.call("/web/player",{"kind":"bookmark","book":book,"remove":marks[0]["id"]})
        self.assertEqual(self.call(path)["marks"],[])

    def test_podcast_auto_download_selects_latest_of_subscribed_shows(self):
        with self.lib.db() as db:
            def episode(title,feed,published):
                book=db.execute("INSERT INTO books(title,author,category) VALUES(?, 'Test','podcast')",(title,)).lastrowid
                edition=db.execute("INSERT INTO editions(book,folder) VALUES(?,?)",(book,title)).lastrowid
                db.execute("UPDATE books SET edition=? WHERE id=?",(edition,book))
                db.execute("INSERT INTO podcast_items(feed,guid,book,show_title,published) VALUES(?,?,?,?,?)",
                           (feed,title,book,"Testshow",published))
                return book
            db.execute("INSERT INTO podcast_feeds(url,title,creator,owner) VALUES('fixture-feed','Testshow','Test',1)")
            episode("Ältere Folge","fixture-feed",100)
            newest=episode("Neueste Folge","fixture-feed",200)
            episode("Einzelimport","manual",300)
        path="/api/v1/podcasts/autodownload"
        self.assertEqual([row["id"] for row in self.call(path)["items"]],[newest])
        self.call("/web/player",{"book":newest,"kind":"played"})
        self.assertEqual(self.call(path)["items"],[])

    def test_sinclair_series_alias_and_renamed_linked_edition(self):
        from server import catalog
        with TemporaryDirectory() as tmp, self.lib.db() as db:
            root=Path(tmp)
            rows=[
                ("Erste Folge","John Sinclair – Edition 2000","1",True),
                ("Spätere Folge","John Sinclair Edition 2000","167",True),
                ("Das Höllenkreuz","John Sinclair Edition 2000","2000",False),
                ("Das Höllenkreuz (Jubiläumsausgabe)","John Sinclair Edition 2000","2000",True),
            ]
            for title,series,volume,present in rows:
                book=db.execute("INSERT INTO books(title,author,category,metadata) VALUES(?,'Jason Dark','audio',?)",
                                (title,json.dumps(dict(series=series,volume=volume)))).lastrowid
                edition=db.execute("INSERT INTO editions(book,folder) VALUES(?,?)",(book,title)).lastrowid
                db.execute("UPDATE books SET edition=? WHERE id=?",(edition,book))
                path=root/title
                if present:path.mkdir()
                db.execute("INSERT INTO scanned_media(source,signature,book) VALUES(?,'fixture',?)",(str(path),book))
            shelf=catalog(db,1,storage_roots=(("collection",root),),show_editions=True)
            self.assertEqual({b["metadata"]["series"] for b in shelf},{"John Sinclair – Edition 2000"})
            self.assertEqual({b["title"] for b in shelf},{r[0] for r in rows if r[3]})

    def test_metadata_and_cover(self):
        item=self.call("/web/books",{"category":"ebook","files":[self.upload(test_server.epub(),"Buch.epub")]})["id"]
        path="/web/admin/metadata/"+str(item)
        self.assertEqual(self.call(path)["author"],"Test")
        png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNuUAAAAASUVORK5CYII=")
        self.call(path,{"title":"Fiktives Buch","tags":"Natur","coverData":base64.b64encode(png).decode()})
        book=self.call("/web/library")["books"][0]
        self.assertEqual((book["title"],book["metadata"]["tags"],book["cover"]),("Fiktives Buch","Natur",True))
        self.assertEqual(self.call(f"/api/v1/books/{item}/thumbnail",raw=True)[2],png)
        thumbnail=f"/api/v1/books/{item}/thumbnail?size=360&rev="
        version=book["coverRevision"]
        self.assertEqual(self.call(thumbnail+version,raw=True)[1]["Cache-Control"],"private, max-age=3600")
        previous=self.call("/web/library")["revision"]
        self.call(path,{"title":"Fiktives Buch","description":"Geänderte Beschreibung"})
        self.assertNotEqual(self.call("/web/library")["revision"],previous)
        self.assertEqual(self.call("/web/library")["books"][0]["coverRevision"],version)
        art=(Path(__file__).resolve().parents[1]/"web/icon.webp").read_bytes()
        self.call(path,{"title":"Fiktives Buch","coverRole":"audio","coverData":base64.b64encode(art).decode()})
        self.assertEqual(self.call(f"/api/v1/books/{item}/cover?art=audio",raw=True)[2],art)
        self.assertNotEqual(self.call("/web/library")["books"][0]["coverRevision"],version)
        self.assertEqual(self.call(thumbnail+version,raw=True)[1]["Cache-Control"],"private, no-cache")
        self.assertEqual(self.call(f"/api/v1/books/{item}/cover?art=book",raw=True)[2],png)
        self.call(path,{"title":"Fiktives Buch","resetRole":"audio"})
        self.assertEqual(self.call(f"/api/v1/books/{item}/cover?art=audio",raw=True)[2],png)

    def test_auto_scan_stability_and_update(self):
        with TemporaryDirectory() as tmp:
            inbox=Inbox(self.lib,tmp);path=Path(tmp)/"Test.epub"
            path.write_bytes(test_server.epub());os.utime(path,(1600000000,1600000000))
            inbox.scan();self.assertEqual(inbox.status()["waiting"],1)
            inbox.scan();book=self.call("/web/library")["books"][0]
            inbox.scan();self.assertEqual(inbox.status()["imported"],0)
            os.utime(path,(1600000001,1600000001));inbox.scan();inbox.scan()
            books=self.call("/web/library")["books"];self.assertEqual(len(books),1)
            self.assertEqual(books[0]["id"],book["id"]);self.assertNotEqual(books[0]["files"],book["files"])
            path.unlink();inbox.scan();self.assertEqual(len(self.call("/web/library")["books"]),1)

    def test_inbox_configuration_survives_restart(self):
        self.http.inbox=Inbox(self.lib)
        with TemporaryDirectory() as temp:
            response=self.call("/web/admin/inbox",{"folder":temp})
            self.assertEqual(Path(response["folder"]),Path(temp))
            self.assertEqual(Inbox(self.lib).root,Path(temp).resolve())
            with self.assertRaises(HTTPError):
                self.call("/web/admin/inbox",{"folder":str(self.lib.data/"editions")})

    def test_feed_preview_import_and_repeat(self):
        wav=io.BytesIO()
        with wave.open(wav,"wb") as w:
            w.setparams((1,2,8000,0,"NONE","NONE"));w.writeframes(bytes(16000))
        rss=b'<rss><channel><title>Fiktiver Podcast</title><item><title>Testfolge</title><guid>one</guid><enclosure url="episode" type="audio/wav"/></item></channel></rss>'
        class Response(io.BytesIO):
            def geturl(self):return "http://localhost/feed"
        def get(url):return Response(rss if url.endswith("feed") else wav.getvalue())
        with patch("podcasts.fetch",side_effect=get):
            url={"url":"http://localhost/feed"};r=self.call("/web/admin/rss/preview",url)
            req=url|{"guid":r["episodes"][0]["guid"]}
            first=self.call("/web/admin/rss/import",req);again=self.call("/web/admin/rss/import",req)
            self.assertEqual(first["id"],again["id"]);self.assertTrue(again["existing"])
            self.assertTrue(self.call("/web/admin/rss/preview",url)["episodes"][0]["imported"])
            self.assertEqual(self.call("/web/library")["books"][0]["category"],"podcast")

    def test_video_enclosure_becomes_audio_and_tags_import(self):
        if not shutil.which("ffmpeg"):self.skipTest("Für diese Medienprobe wird FFmpeg benötigt.")
        with TemporaryDirectory() as tmp:
            track=Path(tmp)/"clip.mp4"
            subprocess.run(["ffmpeg","-v","error","-f","lavfi","-i","color=s=32x32:d=2",
                            "-f","lavfi","-i","sine=frequency=440:duration=2","-c:v","mpeg4","-c:a","aac",
                            "-metadata","artist=Teststimme",str(track)],check=True)
            rss=b'<rss><channel><title>Testfeed</title><item><title>Videofolge</title><enclosure url="/clip.mp4" type="video/mp4"/></item></channel></rss>'
            class Response(io.BytesIO):
                def geturl(self):return "http://localhost/testfeed"
            def get(url):return Response(rss if url.endswith("testfeed") else track.read_bytes())
            with patch("podcasts.fetch",side_effect=get):
                request={"url":"http://localhost/testfeed"};guid=self.call("/web/admin/rss/preview",request)["episodes"][0]["guid"]
                book=self.call("/web/admin/rss/import",request|{"guid":guid})["id"]
                media=self.call("/web/editions/"+str(book))["sections"][0]["cues"][0]
                self.assertTrue(media["path"].endswith(".mp3"));self.assertGreater(media["end"],1.5)
            file=Path(tmp)/"audio.m4a"
            subprocess.run(["ffmpeg","-v","error","-i",str(track),"-vn","-c:a","copy","-metadata","album=Testalbum",
                            "-metadata","genre=Testgenre",str(file)],check=True)
            book=self.call("/web/books",{"category":"audio","files":[self.upload(file.read_bytes(),"unbekannt.m4a")]})["id"]
            stored=self.call(f"/api/v1/books/{book}")
            self.assertEqual((stored["title"],stored["authors"][0]["name"],stored["metadata"]["tags"]),("Testalbum","Teststimme","Testgenre"))
