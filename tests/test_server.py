import io
import json
from pathlib import Path
import sqlite3
import wave
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from abs_history import fetch_history
from library import Library
from server import Handler, ThreadingHTTPServer


def epub(audio=False):
    buf=io.BytesIO()
    with ZipFile(buf,"w") as z:
        z.writestr("mimetype","application/epub+zip")
        z.writestr("META-INF/container.xml",'<container><rootfiles><rootfile full-path="base.opf"/></rootfiles></container>')
        extra='<item id="sm" href="a.smil" media-type="application/smil+xml"/><item id="m" href="a.mp3" media-type="audio/mpeg"/>' if audio else ''
        overlay='media-overlay="sm"' if audio else ''
        z.writestr("base.opf",f'<package><metadata><title>Fiktives Testbuch</title><creator>Test</creator></metadata><manifest><item id="s" href="a.xhtml" media-type="application/xhtml+xml" {overlay}/>{extra}</manifest><spine><itemref idref="s"/></spine></package>')
        z.writestr("a.xhtml",'<html xmlns:epub="http://www.idpf.org/2007/ops"><body><p><span id="s" epub:type="storyteller:sentence-span"><span id="w" epub:type="storyteller:word-span">Hallo</span>!</span></p></body></html>')
        if audio:
            z.writestr("a.smil",'<smil><body><par><text src="a.xhtml#w"/><audio src="a.mp3" clipBegin="1s" clipEnd="2s"/></par></body></smil>')
            z.writestr("a.mp3",b"synthetic-range-fixture")
    return buf.getvalue()


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.lib=Library(self.temp.name)
        self.lib.user("eins","test-fixture-1")
        self.http=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.http.library=self.lib
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url="http://127.0.0.1:"+str(self.http.server_port)
        self.token=""
        self.token=self.call("/api/v1/auth/login",{"username":"eins","password":"test-fixture-1"})["accessToken"]

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.temp.cleanup()

    def call(self,path,data=None,method=None,headers=None,raw=False):
        h={"Authorization":"Bearer "+self.token}
        if data is not None and not isinstance(data,bytes):
            data=json.dumps(data).encode();h["Content-Type"]="application/json"
        req=Request(self.url+path,data,headers=h|(headers or {}),method=method)
        with urlopen(req,timeout=10) as resp:
            if raw:return resp.status,resp.headers,resp.read()
            return json.load(resp)

    def upload(self,content,name):
        return self.call("/web/uploads?name="+quote(name),content)["upload"]

    def test_reader_protocol_ranges_and_conflict(self):
        b=self.call("/web/books",{"files":[self.upload(epub(True),"test.epub")],"category":"ebook"})["id"]
        book=self.call(f"/api/v1/books/{b}");self.assertEqual(book["category"],"audilege")
        f=book["files"][0]["id"]
        index=self.call(f"/web/editions/{b}")
        self.assertTrue(index["sections"][0]["wordTiming"])
        self.assertIn(["Hallo","a.xhtml#w","a.xhtml#s"],index["sections"][0]["tokens"])
        status,h,body=self.call(f"/api/v1/epub/{b}/media-overlay/file/a.mp3?fileId={f}",headers={"Range":"bytes=0-3"},raw=True)
        self.assertEqual((status,body),(206,b"synt"));self.assertTrue(h["Content-Range"].startswith("bytes 0-3/"))
        write={"fileId":f,"kind":"narration","percentage":35,"editedAt":"1970-01-01T00:00:00.000Z","narration":{"fragment":"a.xhtml#w","sectionIndex":0,"seconds":.35}}
        def put():return self.call("/api/v1/reading-progress",{"writes":[write]},"PUT")["results"][0]
        self.assertEqual(put()["status"],"saved")
        self.assertEqual(put()["status"],"superseded")
        self.assertEqual(self.call(f"/api/v1/reading-progress?fileId={f}")["items"][0]["narration"]["seconds"],.35)
        self.assertEqual(self.call("/api/v1/dashboard/scrollers/continue-reading")["books"][0]["id"],b)
        self.assertEqual(self.call("/api/v1/books/query",{"pagination":{"page":0,"size":10}})["total"],1)

    def test_conversion_switches_only_after_success(self):
        bid=self.call("/web/books",{"files":[self.upload(epub(),"test.epub")],"category":"ebook"})["id"]
        f=self.call(f"/web/editions/{bid}")["fileId"]
        original=self.call(f"/api/v1/books/files/{f}/download",raw=True)[2]
        def enqueue():return self.call("/web/align",{"book":bid,"files":[self.upload(b"fixture","001.mp3")],"language":"de"})
        enqueue()
        with self.assertRaises(HTTPError) as ctx:enqueue()
        self.assertEqual(ctx.exception.code,409)
        shelf=lambda:self.call("/web/library")["books"]
        self.assertEqual([b["category"] for b in shelf()],["ebook"])
        with self.lib.db() as db:
            db.execute("UPDATE jobs SET state='failed'")
        self.assertEqual(shelf()[0]["category"],"ebook")
        enqueue()
        from books import index_epub
        folder=Path(self.temp.name)/"editions"/"converted";folder.mkdir()
        (folder/"book.epub").write_bytes(epub(True))
        info=index_epub(folder/"book.epub",folder)
        self.lib.publish(folder,bid,"audilege",info,2)
        self.assertEqual([(b["id"],b["category"]) for b in shelf()],[(bid,"audilege")])
        self.assertEqual(self.call(f"/api/v1/books/files/{f}/download",raw=True)[2],original)

    def test_retry_uses_existing_inputs_and_guards_job_state(self):
        bid=self.call("/web/books",{"files":[self.upload(epub(),"test.epub")],"category":"ebook"})["id"]
        self.call("/web/align",{"book":bid,"files":[self.upload(b"fixture","001.mp3")],"language":"de"})
        with self.lib.db() as db:
            db.execute("UPDATE jobs SET state='failed', source_edition=NULL")
            row=db.execute("SELECT * FROM jobs").fetchone()
        with self.assertRaises(KeyError):self.lib.retry_job(row["owner"]+1,row["id"])
        self.call(f"/web/jobs/{row['id']}/retry",{})
        with self.assertRaises(HTTPError):self.call(f"/web/jobs/{row['id']}/retry",{})
        with self.lib.db() as db:
            self.assertEqual(tuple(db.execute("SELECT folder,state FROM jobs").fetchone()),(row["folder"],"waiting"))
            db.execute("UPDATE jobs SET state='failed', source_edition=-1")
        with self.assertRaises(HTTPError):self.call(f"/web/jobs/{row['id']}/retry",{})
        from library import worker_failure
        log=self.lib.data/"jobs"/row["folder"]/"worker.log"
        log.write_text("Bus error (core dumped)\nrm: Permission denied\n")
        self.assertIn("SIGBUS",worker_failure(log,135))

    def test_zero_length_word_does_not_discard_valid_audio(self):
        from books import index_epub
        with ZipFile(io.BytesIO(epub(True))) as original:
            entries={name:original.read(name) for name in original.namelist()}
        source=Path(self.temp.name)/"timings.epub"
        def index(cue):
            with ZipFile(source,"w") as z:
                for name,data in entries.items():
                    if name=="a.smil":data=data.replace(b"</body>",cue+b"</body>")
                    z.writestr(name,data)
            return index_epub(source,Path(self.temp.name)/"index")["sections"][0]
        point=b'<par><text src="a.xhtml#w"/><audio src="a.mp3" clipBegin="211.08s" clipEnd="211.08s"/></par>'
        chapter=index(point)
        self.assertEqual(len(chapter["cues"]),1)
        self.assertIn(["Hallo","a.xhtml#w","a.xhtml#s"],chapter["tokens"])
        with self.assertRaises(ValueError):index(point.replace(b'clipEnd="211.08s"',b'clipEnd="210s"'))
        with self.assertRaises(ValueError):index(point.replace(b'a.mp3',b'missing.mp3'))

    def test_existing_audio_and_ebook_merge_and_podcast_stays_separate(self):
        wav=io.BytesIO()
        with wave.open(wav,"wb") as f:
            f.setparams((1,2,8000,0,"NONE","not compressed"));f.writeframes(bytes(16000))
        def add(kind,name,data):
            return self.call("/web/books",{"files":[self.upload(data,name)],"category":kind})["id"]
        book=add("ebook","fixture.epub",epub())
        # A PNG embedded in the audio and manually assigned role covers must survive pairing.
        from unittest.mock import patch
        import base64
        png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNuUAAAAASUVORK5CYII=")
        with patch("books.probe",return_value={"format":{"duration":"1","tags":{}},"streams":[{"codec_type":"audio"}],"picture":png}):
            audio=add("audio","A.wav",wav.getvalue())
        book_art=(Path(__file__).resolve().parents[1]/"web/icon.webp").read_bytes()
        audio_art=(Path(__file__).resolve().parents[1]/"web/audilege.webp").read_bytes()
        with self.lib.db() as db:
            db.executemany("INSERT INTO role_covers VALUES(?,?,?,?)",[(book,"book","image/webp",book_art),(audio,"audio","image/webp",audio_art)])
        podcast=add("podcast","P.wav",wav.getvalue())
        self.call("/web/align",{"book":book,"companion":audio,"files":[],"language":"de"})
        with self.assertRaises(HTTPError):
            self.call("/web/align",{"book":audio,"companion":book,"files":[],"language":"de"})
        shelf=lambda:{item["id"]:item["category"] for item in self.call("/web/library")["books"]}
        self.assertEqual(shelf(),{book:"ebook",audio:"audio",podcast:"podcast"})
        from books import index_epub
        folder=self.lib.data/"editions"/"test-result";folder.mkdir()
        (folder/"book.epub").write_bytes(epub(True))
        self.lib.publish(folder,book,"audilege",index_epub(folder/"book.epub",folder),1)
        self.assertEqual(shelf(),{book:"audilege",podcast:"podcast"})
        def art(role):
            return self.call(f"/api/v1/books/{book}/cover?art={role}",raw=True)[2]
        self.assertEqual((art("book"),art("audio")),(book_art,audio_art))
        self.call(f"/web/admin/metadata/{book}",{"title":"Fiktiver Titel","resetRole":"audio"})
        self.assertEqual((art("book"),art("audio")),(book_art,png))
        import maintenance
        with self.lib.db() as db:maintenance.retention(self.lib,db,{"job":1,"action":"trash","confirmed":True})
        self.assertEqual((art("book"),art("audio")),(book_art,png))
        self.assertEqual(self.call(f"/api/v1/books/{audio}")["id"],audio)

    def test_abs_import_preview_repeat_profile_and_rollback(self):
        one={"id":"s-1","libraryItemId":"b","displayTitle":"Das Testbuch","date":"2024-03-31","timeListening":43}
        p={"libraryItemId":"b","progress":.2,"ebookProgress":.5,"isFinished":False,"lastUpdate":10}
        payload=fetch_history("https://abs.example",lambda path:{"sessions":[one],"page":0,"total":1} if "listening-sessions" in path else {"mediaProgress":[p]})
        preview=self.call("/web/abs/preview",payload);self.assertEqual(preview["addedSeconds"],43)
        self.assertFalse(self.call("/web/statistics")["days"])
        self.assertEqual(self.call("/web/abs/import",payload)["newSessions"],1)
        self.assertEqual(self.call("/web/abs/import",payload)["addedSeconds"],0)
        self.assertEqual(self.call("/web/statistics")["positions"][0]["ebook"],.5)
        wrong=dict(payload,sessions=[one,dict(one,id="s-2",timeListening=-1)])
        with self.assertRaises(HTTPError):self.call("/web/abs/import",wrong)
        self.assertEqual(self.call("/web/statistics")["days"],{"2024-03-31":43})
        self.lib.user("zwei","test-fixture-2")
        self.token=self.call("/api/v1/auth/login",{"username":"zwei","password":"test-fixture-2"})["accessToken"]
        self.assertFalse(self.call("/web/statistics")["days"])

    def test_abs_multiple_pages(self):
        rows=[{"id":str(i),"libraryItemId":"book","startedAt":10000,"timeListening":2} for i in range(151)]
        def get(path):
            if "progress" in path:return {"mediaProgress":[]}
            page=int(path.split("page=")[1])
            return {"total":151,"page":page,"sessions":rows[page*100:(page+1)*100]}
        self.assertEqual(len(fetch_history("https://abs.example",get)["sessions"]),151)


if __name__=="__main__":
    unittest.main()
