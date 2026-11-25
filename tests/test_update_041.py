from datetime import date
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave
import zipfile

import test_server
from activity import merged, streak
from abs_history import apply_import
from scanner import Inbox, fingerprint, groups


class UpdateTests(unittest.TestCase):
    setUp=test_server.ServerTest.setUp
    tearDown=test_server.ServerTest.tearDown
    call=test_server.ServerTest.call

    def test_m4b_embedded_chapters_share_a_seekable_track(self):
        with TemporaryDirectory() as tmp:
            source=Path(tmp)/"fixture.m4b"
            source.write_bytes(b"fictional track data")
            media={"format":{"duration":30},"streams":[{"codec_type":"audio"}],"chapters":[
                {"start_time":"0","end_time":"14.5","tags":{"title":"Erstes Kapitel"}},
                {"start_time":"14.5","end_time":"30","tags":{"title":"Zweites Kapitel"}}]}
            with patch("books.probe",return_value=media):
                book=self.lib.import_tracks([(source,source.name)],{"category":"audio","title":"Fiktiv"})
            publication=self.call(f"/web/editions/{book}")
            first,second=publication["sections"]
            self.assertEqual([first["name"],second["name"]],["Erstes Kapitel","Zweites Kapitel"])
            self.assertEqual(first["cues"][0]["path"],second["cues"][0]["path"])
            self.assertEqual((second["cues"][0]["begin"],second["cues"][0]["end"]),(14.5,30))

    def test_pair_scanned_epub_with_audio_folder(self):
        with TemporaryDirectory() as tmp, patch("media_tools.shutil.which",return_value=None):
            inbox=Inbox(self.lib)
            folder=Path(tmp)/"Author"/"Example Series"/"Vol 14 - Fiction"
            folder.mkdir(parents=True)
            with wave.open(str(folder/"Chapter.wav"),"wb") as wav:
                wav.setparams((1,2,8000,0,"NONE","NONE"))
                wav.writeframes(bytes(16000))
            ebook=folder/"Another filename.epub"
            ebook.write_bytes(test_server.epub())
            for p in folder.iterdir():os.utime(p,(1600000000,1600000000))
            inbox.change_linked(tmp)
            inbox.scan();inbox.scan()
            books={b["category"]:b for b in self.call("/web/library")["books"]}
            ids={category:b["id"] for category,b in books.items()}
            self.assertEqual(books["ebook"]["companionId"],ids["audio"])
            mobile=self.call("/api/v1/books/query",{"pagination":{"page":0,"size":100}})["items"]
            self.assertEqual(next(b for b in mobile if b["category"]=="audio")["companionId"],ids["ebook"])
            url=f"/web/books/{ids['audio']}/companions"
            self.assertEqual(self.call(url)["suggested"],ids["ebook"])
            self.assertEqual(self.call(f"/web/books/{ids['ebook']}/companions")["suggested"],ids["audio"])
            second=folder/"Second edition.epub"
            second.write_bytes(ebook.read_bytes());os.utime(second,(1600000000,1600000000))
            inbox.scan();inbox.scan()
            result=self.call(url)
            self.assertIsNone(result["suggested"])
            self.assertEqual(sum(x["sameFolder"] for x in result["choices"]),2)
            self.assertNotIn("companionId",self.call(f"/api/v1/books/{ids['audio']}"))
            self.call("/web/align",{"book":ids["audio"],"companion":ids["ebook"],"files":[],"language":"de"})

    def test_rescan_groups_numbered_discs_and_moves_each_profiles_position(self):
        with TemporaryDirectory() as tmp, patch("media_tools.shutil.which",return_value=None):
            root=Path(tmp)
            title=root/"Author"/"Example Series"/"Vol 07 - Example"
            inbox=Inbox(self.lib)
            inbox.change_linked(str(root))
            for disc in (10,2,1):
                folder=title/f"CD {disc}"
                folder.mkdir(parents=True)
                for track in (2,10):
                    path=folder/f"{track}.wav"
                    with wave.open(str(path),"wb") as wav:
                        wav.setparams((1,2,8000,0,"NONE","NONE"))
                        wav.writeframes(bytes(16000))
                    os.utime(path,(1600000000,1600000000))
                tracks=[folder/"2.wav",folder/"10.wav"]
                book=self.lib.import_tracks([(p,p.name) for p in tracks],{"category":"audio","title":folder.name},
                      scan=(os.path.normcase(str(folder)),fingerprint(tracks)),link_root=root)
                with self.lib.db() as db:
                    if disc in (2,10):
                        from library import save_progress
                        file=db.execute("SELECT edition FROM books WHERE id=?",(book,)).fetchone()[0]
                        save_progress(db,disc,dict(kind="narration",fileId=file,percentage=75,
                            editedAt="1970-01-01T00:00:00.000Z",narration=dict(seconds=1.5,sectionIndex=1)))
                        db.execute("INSERT INTO bookmarks(owner,book,edition,chapter,offset,cue,label) VALUES(?,?,?,1,0,0,'Mark')",(disc,book,file))
            for _ in range(3):inbox.scan()
            self.assertEqual(inbox.status()["errors"],[])
            self.assertEqual(inbox.status()["imported"],0)
            self.http.inbox=inbox
            item=self.call("/web/library")["books"][0]
            self.assertEqual(item["title"],"Example")
            self.assertEqual(item["metadata"]["series"],"Example Series")
            self.assertEqual(item["metadata"]["volume"],"7")
            self.assertEqual(item["storage"]["path"],title.relative_to(root).as_posix())
            with self.lib.db() as db:
                rows=db.execute("SELECT * FROM books WHERE merged_into IS NULL").fetchall()
                self.assertEqual([r["title"] for r in rows],["Example"])
                file=rows[0]["edition"]
                offsets={r["owner"]:json.loads(r["data"])["narration"]["seconds"] for r in db.execute("SELECT * FROM progress WHERE edition=?",(file,))}
                self.assertEqual(offsets,{2:3.5,10:5.5})
                self.assertEqual(dict(db.execute("SELECT owner,chapter FROM bookmarks WHERE edition=?",(file,))),{2:3,10:5})
                dest=self.lib.edition(db,rows[0]["id"])[1]
                info=json.loads((dest/"index.json").read_text(encoding="utf8"))
                self.assertEqual([s["name"] for s in info["sections"]],[f"CD {d}/{i}.wav" for d in (1,2,10) for i in (2,10)])
            sibling=title.parent/"Vol 08 - Separate"
            sibling.mkdir()
            (sibling/"1.wav").touch()
            (title/"CD 1"/"edition.epub").touch()
            self.assertEqual({p for _,p,_ in groups(root)},{title,sibling,title/"CD 1"/"edition.epub"})

    def test_linked_collection_resources_offline_download_and_restart(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            ebook=root/"fiction.EPUB"
            ebook.write_bytes(test_server.epub(True))
            audio=root/"Album"
            audio.mkdir()
            tracks=[]
            for n in (1,2):
                path=audio/f"{n}.WAV"
                with wave.open(str(path),"wb") as f:
                    f.setparams((1,2,16000,0,"NONE","NONE"))
                    f.writeframes(bytes(32000*n))
                tracks.append(path)
            for p in [*tracks,ebook]:os.utime(p,(1600000000,1600000000))
            inbox=Inbox(self.lib)
            with patch("media_tools.shutil.which",return_value=None):
                inbox.change_linked(str(root))
                inbox.scan();inbox.scan()
            self.assertEqual(inbox.status()["errors"],[])
            self.assertEqual(inbox.status()["imported"],2)
            self.assertEqual(set(root.iterdir()),{ebook,audio})
            self.assertEqual(Inbox(self.lib).status()["linkedFolder"],str(root))
            inbox.scan()
            self.assertEqual(inbox.status()["imported"],0)
            with self.lib.db() as db:
                items={r["category"]:dict(r) for r in db.execute("SELECT b.*,e.folder FROM books b JOIN editions e ON e.id=b.edition")}
            self.assertEqual(set(items),{"audilege","audio"})
            self.http.inbox=inbox
            result=self.call("/web/library")
            locations={b["category"]:b["storage"] for b in result["books"]}
            self.assertEqual(locations["audio"]["kind"],"collection")
            self.assertEqual(locations["audio"]["path"].casefold(),"album")
            self.assertEqual(locations["audilege"]["path"].casefold(),"fiction.epub")
            row=items["audio"]
            folder=self.lib.data/"editions"/row["folder"]
            self.assertLess(sum(p.stat().st_size for p in folder.iterdir()),tracks[0].stat().st_size)
            def content(row,path):
                return self.call(f"/api/v1/epub/{row['id']}/file/{path}?fileId={row['edition']}",headers={"Range":"bytes=0-5"},raw=True)
            self.assertEqual(content(row,"track0.wav")[2],tracks[0].read_bytes()[:6])
            def download(row):
                return self.call(f"/api/v1/books/files/{row['edition']}/download",raw=True)[2]
            with zipfile.ZipFile(io.BytesIO(download(row))) as archive:
                self.assertEqual(archive.read("track1.wav"),tracks[1].read_bytes())
            embedded=items["audilege"]
            self.assertEqual(download(embedded),ebook.read_bytes())
            self.assertEqual(content(embedded,"a.mp3")[2],b"synthe")
            self.assertFalse((self.lib.data/"editions"/embedded["folder"]/"book.epub").exists())
            with self.assertRaises(ValueError):inbox.change_folder(str(audio))
            self.assertFalse((audio/"Ebooks").exists())
            inbox.change_linked("")
            self.assertEqual(Inbox(self.lib).status()["linkedFolder"],"")
            self.assertEqual(content(row,"track0.wav")[0],206)

    def test_prefix_form_cookie_and_script_order(self):
        html=self.call("/",raw=True)[2].decode()
        self.assertIn('method="post" action="web/login"',html)
        self.assertNotRegex(html,r'(src|href)="/')
        self.assertEqual(html.count("<script"),1)
        bundle=self.call("/audilege-ui.js?v=0.4.14",raw=True)[2]
        self.assertLess(bundle.index(b"function tr("),bundle.index(b"const categories ="))
        credentials={"username":"eins","password":"test-fixture-1","cookiePath":"/medien/audilege/"}
        origin={"Origin":"https://school.example","Host":"school.example"}
        _,headers,_=self.call("/web/login",credentials,headers=origin,raw=True)
        self.assertIn("Path=/medien/audilege/;",headers["Set-Cookie"])
        self.assertIn("; Secure",headers["Set-Cookie"])
        cookie=headers["Set-Cookie"].split(";")[0]
        _,out,_=self.call("/web/logout",{"cookiePath":"/medien/audilege/"},headers=origin|{"Cookie":cookie},raw=True)
        self.assertIn("Path=/medien/audilege/;",out["Set-Cookie"])
        self.assertIn("Max-Age=0",out["Set-Cookie"])

    def test_merged_history_and_streak_across_sources(self):
        def imported(sid,day,seconds,started=None):
            row=dict(id=sid,date=day,timeListening=seconds,displayTitle="Fixture",libraryItemId="abs-book")
            if started:row["startedAt"]=started
            return row
        with self.lib.db() as db:
            db.execute("INSERT INTO books(id,title,author,category,edition) VALUES(1,'Fixture','A','audio',1)")
            db.execute("INSERT INTO editions VALUES(1,1,'fixture',NULL)")
            def native(sid,kind,start,end,sec):
                db.execute("INSERT INTO sessions(owner,edition,sid,start,end,seconds,kind) VALUES(1,1,?,?,?,?,?)",(sid,start,end,sec,kind))
            native("app","listen","2024-01-02T12:00:00Z","2024-01-02T12:01:00Z",60)
            native("web","read","2024-01-02T23:59:57Z","2024-01-03T00:00:03Z",6)
            payload=dict(format="audilege-abs-1",server="https://abs.example",mediaProgress=[],
                         sessions=[imported("earlier","2024-01-01",20),imported("replica","2024-01-02",60,1704196800000)])
            for _ in range(2):apply_import(db,1,payload,True)
            result=merged(db,1,date(2024,1,4))
            self.assertEqual(result["heardMedia"],1)
            self.assertEqual(result["listeningDays"],{"2024-01-01":20,"2024-01-02":60})
            self.assertEqual(result["days"]["2024-01-03"],3)
            self.assertEqual(result["streak"],{"current":3,"best":3})
            self.assertEqual(len(result["events"]),3)
            self.assertEqual(result["activities"]["listen"]["books"]["orbit:1"]["millis"],80000)
            self.assertEqual(merged(db,2)["heardMedia"],0)
            self.assertEqual(streak(result["days"],date(2024,1,5)),{"current":0,"best":3})

