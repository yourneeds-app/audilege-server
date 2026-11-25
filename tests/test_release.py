import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from test_server import epub
from books import index_epub
from library import Library, get_progress, save_progress
from scanner import Inbox
import curation
import maintenance


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.lib=Library(self.root/"library")
        self.lib.user("fixture","fictional-fixture")
        self.epub=self.root/"fixture.epub"
        self.epub.write_bytes(epub())
        self.book=self.lib.import_tracks([(self.epub,"fixture.epub")],{"category":"ebook"})

    def test_review_undo_stale_and_incremental(self):
        c=dict(provider="ollama",endpoint="http://localhost:11434",sources=[],enabled=True,model="fixture")
        proposal=dict(kind="series",field="series",value="Fiktive Reihe",evidence="library",reason="Fiktives Beispiel.")
        with self.lib.db() as db:
            curation.save_config(self.lib,db,c)
            job=db.execute("INSERT INTO review_jobs VALUES(NULL,'running','')").lastrowid
        with patch.object(curation,"infer",return_value=[proposal]) as model:
            curation.run_job(self.lib,job,c,1,[self.book],["series"],True)
            curation.run_job(self.lib,job,c,1,[self.book],["series"],True)
            model.assert_called_once()
        with self.lib.db() as db:
            self.assertNotIn("series",curation.book_fields(db,self.book))
            suggestion=db.execute("SELECT id FROM suggestions").fetchone()[0]
            curation.decide(db,dict(id=suggestion,action="approve"))
            self.assertEqual(curation.book_fields(db,self.book)["series"],proposal["value"])
            curation.decide(db,dict(id=suggestion,action="undo"))
            self.assertNotIn("series",curation.book_fields(db,self.book))
            with self.assertRaises(ValueError):curation.decide(db,dict(id=suggestion,action="approve"))

    def test_custom_key_is_bound_to_host(self):
        cfg=dict(provider="compatible",endpoint="https://example.invalid/v1")
        with patch.dict(os.environ,{"AUDILEGE_AI_KEY":"fixture","AUDILEGE_AI_ENDPOINT":"https://different.invalid/v1"}):
            self.assertEqual(curation.credential(self.lib,cfg),"")

    def test_supported_provider_response_shapes(self):
        answer='{"suggestions":[]}'
        cases=[
            ("openai",{"choices":[{"message":{"content":answer}}]},"/chat/completions"),
            ("compatible",{"choices":[{"message":{"content":answer}}]},"/chat/completions"),
            ("ollama",{"message":{"content":answer}},"/api/chat"),
            ("anthropic",{"content":[{"text":answer}]},"/messages"),
            ("gemini",{"candidates":[{"content":{"parts":[{"text":answer}]}}]},"/models/fixture:generateContent")]
        for provider,reply,path in cases:
            with self.subTest(provider=provider),patch.object(curation,"request",return_value=reply) as request:
                self.assertEqual(curation.infer(dict(provider=provider,model="fixture"),"","fictional metadata"),[])
                self.assertEqual(request.call_args.args[2],path)

    def test_efficient_start_with_large_catalogue(self):
        from server import catalog
        with self.lib.db() as db:
            edition,_=self.lib.edition(db,self.book)
            for i in range(999):
                book=db.execute("INSERT INTO books(title,author,category,metadata) VALUES(?,'Fixture','ebook','{}')",("Fiktiver Titel "+str(i),)).lastrowid
                e=db.execute("INSERT INTO editions(book,folder,cover) VALUES(?,?,NULL)",(book,uuid.uuid4().hex)).lastrowid
                db.execute("UPDATE books SET edition=? WHERE id=?",(e,book))
            save_progress(db,1,dict(fileId=edition["id"],kind="text",text={"page":1},percentage=12,editedAt="1970-01-01T00:00:00.000Z"))
            shelf=catalog(db,1,start=True)
            self.assertEqual(len(shelf),7)
            self.assertIn(self.book,{b["id"] for b in shelf})
            self.assertEqual(len(catalog(db,1)),1000)

    def test_backup_restore_and_settings(self):
        data=self.lib.data
        private=data/"private";private.mkdir();(private/"local-test").write_text("fictional")
        backup=maintenance.snapshots(data,self.root/"backup")
        self.assertFalse((backup/"private").exists())
        with self.lib.db() as db:db.execute("UPDATE books SET title='Changed'")
        rollback=maintenance.snapshots(data,backup,restore=True)
        self.assertTrue((rollback/"audilege.sqlite3").is_file())
        self.assertEqual((private/"local-test").read_text(),"fictional")
        with self.lib.db() as db:self.assertNotEqual(db.execute("SELECT title FROM books").fetchone()[0],"Changed")
        (backup/"audilege.sqlite3").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError,"Prüfsummenfehler"):maintenance.snapshots(data,backup,restore=True)

    def test_confirmed_retention_export_and_resume(self):
        with self.lib.db() as db:
            original,folder=self.lib.edition(db,self.book)
            eid=original["id"]
            save_progress(db,1,dict(fileId=eid,kind="text",percentage=25,text={"page":1,"webOffset":1},editedAt="1970-01-01T00:00:00.000Z"))
        with self.lib.db() as db:
            maintenance.player(db,1,dict(kind="bookmark",book=self.book,edition=eid,chapter=0,offset=1,label="Fixture"))
            job=db.execute("INSERT INTO jobs(book,owner,folder,language,state,note,source_edition) VALUES(?,1,?,'de','running','',?)",(self.book,uuid.uuid4().hex,eid)).lastrowid
        dest=self.lib.data/"editions"/uuid.uuid4().hex;dest.mkdir()
        (dest/"book.epub").write_bytes(epub(True))
        self.lib.publish(dest,self.book,"audilege",index_epub(dest/"book.epub",dest),job)
        inbox=Inbox(self.lib);inbox.scan();inbox.scan()
        with self.lib.db() as db:
            new,_=self.lib.edition(db,self.book)
            self.assertEqual(get_progress(db,1,new["id"])["text"]["webOffset"],1)
            self.assertEqual(maintenance.player(db,1)["marks"][0]["edition"],new["id"])
            self.assertEqual(db.execute("SELECT count(*) FROM books").fetchone()[0],1)
            exported=Path(db.execute("SELECT path FROM readalong_exports").fetchone()[0])
            self.assertEqual(exported.parent.name,"Readaloud")
            epub_content=(dest/"book.epub").read_bytes()
            self.assertEqual(exported.read_bytes(),epub_content)
            with self.assertRaises(ValueError):maintenance.retention(self.lib,db,{"job":job,"action":"trash"})
            self.assertTrue(folder.is_dir())
            maintenance.retention(self.lib,db,{"job":job,"action":"trash","confirmed":True})
            self.assertFalse(folder.exists());self.assertEqual((dest/"book.epub").read_bytes(),epub_content)
            maintenance.retention(self.lib,db,{"job":job,"action":"restore"})
            self.assertTrue((folder/"book.epub").is_file())
            maintenance.retention(self.lib,db,{"job":job,"action":"trash","confirmed":True})
            with self.assertRaises(ValueError):maintenance.retention(self.lib,db,{"job":job,"action":"purge"})
            maintenance.retention(self.lib,db,{"job":job,"action":"purge","confirmed":True})
            self.assertEqual((dest/"book.epub").read_bytes(),epub_content)
            self.assertTrue(self.epub.is_file())
            self.assertFalse((self.lib.data/"trash"/folder.name).exists())

    def test_verified_email_and_single_use_reset(self):
        with self.lib.db() as db:
            cfg=dict(enabled=True,url="https://example.invalid")
            maintenance.setting(db,"smtp",cfg)
            db.execute("INSERT INTO recovery(owner,pending) VALUES(1,'abc@example.invalid')")
            with patch.object(maintenance,"mail") as mail:
                maintenance.mail_link(db,1,"verify","abc@example.invalid",cfg)
                code=mail.call_args.args[-1].split("#verify=")[1]
            db.commit()
            maintenance.public_account(self.lib,db,"verify",dict(code=code),"fixture")
            self.assertEqual(db.execute("SELECT email FROM recovery").fetchone()[0],"abc@example.invalid")
            with patch.object(maintenance,"mail") as mail:
                maintenance.mail_link(db,1,"reset","abc@example.invalid",cfg)
                code=mail.call_args.args[-1].split("#reset=")[1]
            db.commit()
            maintenance.public_account(self.lib,db,"reset",dict(code=code,password="fixture-updated"),"fixture")
            self.assertEqual(self.lib.login(db,"fixture","fixture-updated"),1)
            with self.assertRaises(ValueError):maintenance.public_account(self.lib,db,"reset",dict(code=code,password="fixture-updated"),"fixture")
