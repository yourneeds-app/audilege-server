"""Media retention, offline snapshots, profile tools and account recovery."""
import hashlib
import json
import os
import re
import secrets
import shutil
import smtplib
import sqlite3
import ssl
import time
import uuid
from contextlib import closing
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
from zipfile import ZipFile

VERSION="0.4.2"
REPO="https://github.com/yourneeds-app/audilege-server"
SCHEMA="""
CREATE TABLE IF NOT EXISTS player_items(owner INTEGER,book INTEGER,kind TEXT,value TEXT,PRIMARY KEY(owner,book,kind));
CREATE TABLE IF NOT EXISTS bookmarks(id INTEGER PRIMARY KEY,owner INTEGER,book INTEGER,edition INTEGER,chapter INTEGER,offset INTEGER,cue INTEGER,label TEXT);
CREATE TABLE IF NOT EXISTS retention(job INTEGER PRIMARY KEY,decision TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS readalong_exports(edition INTEGER PRIMARY KEY,filename TEXT,path TEXT);
CREATE TABLE IF NOT EXISTS uploaded_originals(job INTEGER PRIMARY KEY,folder TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trash(folder TEXT PRIMARY KEY,job INTEGER,target TEXT);
CREATE TABLE IF NOT EXISTS recovery(owner INTEGER PRIMARY KEY,email TEXT UNIQUE,pending TEXT);
CREATE TABLE IF NOT EXISTS recovery_links(digest BLOB PRIMARY KEY,owner INTEGER,purpose TEXT,expires REAL,email TEXT);
CREATE TABLE IF NOT EXISTS mail_limits(subject TEXT PRIMARY KEY,stamp REAL);
CREATE TABLE IF NOT EXISTS device_tokens(hash BLOB PRIMARY KEY,device TEXT,agent TEXT);
"""
def get_setting(db,key,default=None):
    r=db.execute("SELECT value FROM server_settings WHERE key=?",(key,)).fetchone()
    return json.loads(r[0]) if r else default

def setting(db,key,value):
    db.execute("INSERT OR REPLACE INTO server_settings VALUES(?,?)",(key,json.dumps(value)))

def directory(path):
    if not path:
        roots=[str(Path.home()),"/"] if os.name!="nt" else [c+":\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(c+":\\")]
        return {"path":"","parent":"","folders":roots}
    p=Path(path)
    if not p.is_absolute() or not p.is_dir():raise ValueError("Ungültiger Serverordner.")
    p=p.resolve()
    from scanner import real_entry
    try:names=sorted((str(v) for v in p.iterdir() if not v.name.startswith(".") and v.is_dir() and real_entry(v)),key=str.casefold)
    except OSError:raise ValueError("Dieser Ordner ist nicht zugänglich.") from None
    return {"path":str(p),"parent":str(p.parent) if p!=p.parent else "","folders":names,"free":shutil.disk_usage(p).free}

def source_editions(lib,db,job):
    row=db.execute("""SELECT j.*,b.edition AS active FROM jobs j JOIN books b ON j.book=b.id
        WHERE j.id=? AND j.state='done' AND b.category='audilege' AND b.merged_into IS NULL""",(job,)).fetchone()
    if not row:raise ValueError("Keine abgeschlossene Mitlesefassung.")
    active,folder=lib.edition(db,row["book"])
    if not (folder/"book.epub").is_file():raise ValueError("Die fertige Ausgabe fehlt.")
    return [dict(r) for r in db.execute("""SELECT e.folder,e.id,b.title FROM editions e JOIN books b ON b.id=e.book
        WHERE e.id IN (?,?) AND e.id<>? AND (b.edition<>e.id OR b.merged_into=?) AND NOT EXISTS
        (SELECT 1 FROM jobs WHERE state IN ('running','waiting') AND e.id IN (source_edition,companion_edition))""",
        (row["source_edition"],row["companion_edition"],active["id"],row["book"]))],folder

def reconcile_trash(lib,db):
    for row in db.execute("SELECT folder,target FROM trash").fetchall():
        name,target=row
        if not re.fullmatch("[a-f0-9]{32}",name):raise ValueError("Ungültiger Ausgabeordner.")
        a,b=lib.data/"editions"/name,lib.data/"trash"/name
        if target=="removed":continue
        if target=="purge":
            from scanner import real_entry
            if b.exists():
                if b.resolve().parent!=(lib.data/"trash").resolve() or not real_entry(b) or (lib.data/"trash").resolve()!=lib.data/"trash":
                    raise ValueError("Ungültiger Papierkorbpfad.")
                shutil.rmtree(b)
            db.execute("UPDATE trash SET target='removed' WHERE folder=?",(name,))
            continue
        src,dest=(a,b) if target=="trash" else (b,a)
        if src.is_dir() and not dest.exists():
            dest.parent.mkdir(exist_ok=True)
            src.rename(dest)
        if target=="library" and dest.is_dir():
            db.execute("DELETE FROM trash WHERE folder=? AND target='library'",(name,))

def retention(lib,db,d):
    job=int(d["job"]);action=d.get("action","preview")
    editions,folder=source_editions(lib,db,job)
    extra=db.execute("SELECT folder FROM uploaded_originals WHERE job=?",(job,)).fetchone()
    if extra:editions.append({"folder":extra[0],"title":"Upload"})
    if action=="preview":
        return {"files":[{"name":r["title"],"path":str(lib.data/"editions"/r["folder"]),"bytes":sum(f.stat().st_size for f in (lib.data/"editions"/r["folder"]).glob("*") if f.is_file())} for r in editions]}
    if action not in ("keep","trash","restore","purge"):raise ValueError("Unbekannte Speicherentscheidung.")
    choice=db.execute("SELECT decision FROM retention WHERE job=?",(job,)).fetchone()
    if choice and choice[0]=="purge":raise ValueError("Die Originale wurden bereits endgültig entfernt.")
    if action in ("purge","restore") and (not choice or choice[0]!="trash"):raise ValueError("Keine Originale im Papierkorb.")
    if action=="purge":
        if d.get("confirmed") is not True:raise ValueError("Auswahl bitte bestätigen.")
        db.execute("UPDATE trash SET target='purge' WHERE job=? AND target='trash'",(job,))
    if action in ("trash","purge"):
        if d.get("confirmed") is not True:raise ValueError("Auswahl bitte bestätigen.")
        import zipfile
        with zipfile.ZipFile(folder/"book.epub") as z:
            if z.testzip():raise ValueError("Die fertige Mitlesefassung ist beschädigt.")
        info=json.loads((folder/"index.json").read_text(encoding="utf8"))
        from books import resource
        if not any(s.get("cues") for s in info["sections"]) or not all(resource(folder,k).is_file() for k in json.loads((folder/"resources.json").read_text(encoding="utf8"))):
            raise ValueError("Mitleseressourcen unvollständig.")
    if action=="trash":
        # Older merged editions may only carry their audiobook cover in the predecessor.
        for r in editions:
            old=lib.data/"editions"/r["folder"]
            if not (folder/"audio-cover.jpg").is_file() and (old/"resources.json").is_file():
                mapping=json.loads((old/"resources.json").read_text(encoding="utf8"))
                if "cover.jpg" in mapping and any(k.startswith("track0.") for k in mapping):
                    shutil.copyfile(resource(old,"cover.jpg"),folder/"audio-cover.jpg")
            db.execute("INSERT OR REPLACE INTO trash VALUES(?,?,'trash')",(r["folder"],job))
    if action=="restore":db.execute("UPDATE trash SET target='library' WHERE job=?",(job,))
    db.execute("INSERT OR REPLACE INTO retention VALUES(?,?)",(job,action))
    db.commit()
    db.execute("BEGIN IMMEDIATE");reconcile_trash(lib,db)
    return {}

def snapshots(data,destination,restore=False):
    """Run only while holding the server lock. Never overwrite the only good copy."""
    data=Path(data).resolve();target=Path(destination).resolve()
    if target.is_relative_to(data) or data.is_relative_to(target):raise ValueError("Ein separates Sicherungsverzeichnis wählen.")
    if restore:
        manifest=json.loads((target/"manifest.json").read_text(encoding="utf8"))
        if not manifest.get("files") or "audilege.sqlite3" not in manifest["files"]:raise ValueError("Ungültige Sicherung.")
        stage=data.parent/(data.name+"-restore-"+uuid.uuid4().hex)
        stage.mkdir()
        for name,expected in manifest["files"].items():
            src=(target/name).resolve();out=(stage/name).resolve()
            if (not src.is_relative_to(target) or not out.is_relative_to(stage)
                or Path(name).is_absolute() or ".." in Path(name).parts
                or Path(name).parts[0].casefold() in (".server.lock","private")):raise ValueError("Ungültiger Sicherungspfad.")
            out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,out)
            if digest(out)!=expected:raise ValueError("Prüfsummenfehler bei "+name)
        with closing(sqlite3.connect(stage/"audilege.sqlite3")) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0]!="ok":raise ValueError("Datenbank beschädigt.")
        # The lock file stays in place during the swap, including on Windows.
        previous=data.parent/(data.name+"-before-restore-"+uuid.uuid4().hex)
        previous.mkdir()
        moved=[];installed=[]
        try:
            for f in data.iterdir():
                if f.name not in (".server.lock","private"):f.rename(previous/f.name);moved.append(f.name)
            for f in stage.iterdir():f.rename(data/f.name);installed.append(f.name)
        except OSError:
            for n in reversed(installed):(data/n).rename(stage/n)
            for n in reversed(moved):(previous/n).rename(data/n)
            raise
        stage.rmdir()
        return previous
    if target.exists():raise ValueError("Für die Sicherung einen neuen Ordner wählen.")
    temp=target.with_name(target.name+"-partial-"+uuid.uuid4().hex);temp.mkdir(parents=True)
    files={}
    def source_files():
        from scanner import real_entry
        for current,dirs,names in os.walk(data):
            folder=Path(current)
            dirs[:]=[d for d in dirs if (folder!=data or d.casefold() not in ("private","thumbnails")) and real_entry(folder/d)]
            for name in names:
                p=folder/name
                if real_entry(p):yield p
    for p in source_files():
        rel=p.relative_to(data)
        if not p.is_file() or p.is_symlink() or p.name in (".server.lock","audilege.sqlite3-wal","audilege.sqlite3-shm") or rel.parts[0]=="private":continue
        dst=temp/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        if rel.as_posix()=="audilege.sqlite3":
            with closing(sqlite3.connect(p)) as source,closing(sqlite3.connect(dst)) as dest:source.backup(dest)
        else:shutil.copyfile(p,dst)
        files[rel.as_posix()]=digest(dst)
    (temp/"manifest.json").write_text(json.dumps({"version":VERSION,"files":files}),encoding="utf8")
    temp.rename(target);return target

def digest(file):
    with file.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest() if hasattr(hashlib,"file_digest") else digest_stream(f)
def digest_stream(f):
    h=hashlib.sha256()
    for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def smtp_config(db):
    return get_setting(db,"smtp",{})
def mail(cfg,addr,subject,text):
    msg=EmailMessage();msg["From"]=cfg["sender"];msg["To"]=addr;msg["Subject"]=subject;msg.set_content(text)
    with smtplib.SMTP(cfg["host"],cfg["port"],timeout=12) as s:
        s.starttls(context=ssl.create_default_context())
        if cfg["user"]:s.login(cfg["user"],os.environ.get("AUDILEGE_SMTP_PASSWORD",""))
        s.send_message(msg)
def address(s):
    if not isinstance(s,str) or not re.fullmatch(r"[^@\s<>\r\n]+@[^@\s<>]+\.[^@\s<>]+",s) or len(s)>254:raise ValueError("Ungültige E-Mail-Adresse.")
    return s.strip().casefold()
def mail_link(db,owner,purpose,addr,cfg):
    code=secrets.token_urlsafe(32);key=hashlib.sha256(code.encode()).digest()
    db.execute("DELETE FROM recovery_links WHERE (owner=? AND purpose=?) OR expires<?",(owner,purpose,time.time()))
    db.execute("INSERT INTO recovery_links VALUES(?,?,?,?,?)",(key,owner,purpose,time.time()+1200,addr))
    url=cfg["url"]+"/#"+purpose+"="+code
    mail(cfg,addr,"Audilege · "+("Adresse bestätigen" if purpose=="verify" else "Passwort zurücksetzen"),"Dieser Link ist 20 Minuten gültig:\n"+url)
def rate(db,subjects):
    t=time.time();db.execute("DELETE FROM mail_limits WHERE stamp<?",(t-3600,))
    for subject in subjects:
        key=hashlib.sha256(subject.encode()).hexdigest()
        if db.execute("SELECT 1 FROM mail_limits WHERE subject=? AND stamp>?",(key,t-60)).fetchone():return False
        db.execute("INSERT OR REPLACE INTO mail_limits VALUES(?,?)",(key,t))
    return True
def public_account(lib,db,action,d,ip):
    cfg=smtp_config(db)
    if action=="available":return {"enabled":bool(cfg.get("enabled"))}
    db.execute("BEGIN IMMEDIATE")
    if not cfg.get("enabled"):raise ValueError("Die E-Mail-Wiederherstellung ist nicht eingerichtet.")
    if action=="forgot":
        name=str(d.get("name","")).strip().lower()
        permit=rate(db,["ip:"+ip,"user:"+name])
        row=db.execute("SELECT u.id,r.email FROM users u JOIN recovery r ON u.id=r.owner WHERE u.enabled=1 AND (lower(u.name)=? OR r.email=?) AND r.email IS NOT NULL",(name,name)).fetchone()
        db.commit()
        if row and permit:
            # The response and its latency must not reveal whether an account exists.
            import threading
            def notify():
                try:
                    with lib.db() as conn:mail_link(conn,row[0],"reset",row[1],cfg)
                except (OSError,smtplib.SMTPException):pass
            threading.Thread(target=notify,daemon=True).start()
        return {}
    code=hashlib.sha256(str(d.get("code","")).encode()).digest()
    row=db.execute("SELECT l.* FROM recovery_links l JOIN users u ON u.id=l.owner WHERE l.digest=? AND l.purpose=? AND l.expires>? AND u.enabled=1",(code,action,time.time())).fetchone()
    if not row:raise ValueError("Link ungültig oder abgelaufen.")
    if action=="verify":
        if not db.execute("UPDATE recovery SET email=pending,pending=NULL WHERE owner=? AND pending=?",(row["owner"],row["email"])).rowcount:raise ValueError("Adresse geändert.")
        db.execute("DELETE FROM recovery_links WHERE owner=?",(row["owner"],))
    elif action=="reset":
        if not db.execute("SELECT 1 FROM recovery WHERE owner=? AND email=?",(row["owner"],row["email"])).fetchone():raise ValueError("Adresse geändert.")
        db.execute("UPDATE users SET salt=?,digest=? WHERE id=?",(*lib.password_hash(d["password"]),row["owner"]))
        db.execute("DELETE FROM tokens WHERE owner=?",(row["owner"],))
        db.execute("DELETE FROM recovery_links WHERE owner=?",(row["owner"],))
    else:raise KeyError(action)
    db.commit();return {}

def update_info():
    req=Request("https://api.github.com/repos/yourneeds-app/audilege-server/releases/latest",headers={"User-Agent":"Audilege/"+VERSION})
    try:
        with urlopen(req,timeout=8) as r:latest=json.loads(r.read(1_000_001))["tag_name"]
    except OSError:raise ValueError("Kein öffentliches Release erreichbar.")
    return {"installed":VERSION,"latest":latest,"url":REPO+"/releases/latest"}

def start_update_checks(lib):
    from threading import Thread
    def check():
        while True:
            with lib.db() as db:
                enabled=get_setting(db,"daily_updates",False)
                last=get_setting(db,"update_checked",0)
            if enabled and time.time()-last>=86400:
                try:result=update_info()
                except (OSError,ValueError,KeyError):result={}
                with lib.db() as db:
                    setting(db,"update_checked",time.time())
                    if result:setting(db,"update_result",result)
            time.sleep(300)
    Thread(target=check,name="Audilege-Updates",daemon=True).start()

def player(db,owner,d=None):
    if d is not None:
        db.execute("BEGIN IMMEDIATE")
        kind=d.get("kind")
        book=int(d["book"])
        row=db.execute("SELECT edition FROM books WHERE id=? AND merged_into IS NULL",(book,)).fetchone()
        if not row:raise KeyError(book)
        if kind=="bookmark":
            if d.get("remove"):
                db.execute("DELETE FROM bookmarks WHERE owner=? AND book=? AND id=?",(owner,book,int(d["remove"])))
            else:
                if row[0]!=d.get("edition"):raise ValueError("Ausgabe hat sich geändert.")
                db.execute("INSERT INTO bookmarks(owner,book,edition,chapter,offset,cue,label) VALUES(?,?,?,?,?,?,?)",
                    (owner,book,row[0],max(0,int(d["chapter"])),max(0,int(d["offset"])),int(d.get("cue",-1)),str(d["label"])[:220]))
        elif kind in ("queue","played"):
            if d.get("remove"):db.execute("DELETE FROM player_items WHERE owner=? AND book=? AND kind=?",(owner,book,kind))
            else:
                value="1"
                if kind=="queue":
                    value=str(db.execute("SELECT coalesce(max(CAST(value AS INTEGER)),0)+1 FROM player_items WHERE owner=? AND kind='queue'",(owner,)).fetchone()[0])
                db.execute("INSERT OR IGNORE INTO player_items VALUES(?,?,?,?)",(owner,book,kind,value))
        elif kind=="promote":
            db.execute("UPDATE player_items SET value=(SELECT coalesce(min(CAST(value AS INTEGER)),0)-1 FROM player_items WHERE owner=? AND kind='queue') WHERE owner=? AND book=? AND kind='queue'",(owner,owner,book))
        else:raise ValueError("Unbekannte Aktion.")
    return {"items":[dict(r) for r in db.execute("SELECT i.* FROM player_items i JOIN books b ON i.book=b.id WHERE owner=? AND b.merged_into IS NULL ORDER BY CAST(value AS INTEGER),book",(owner,))],
            "marks":[dict(r) for r in db.execute("SELECT * FROM bookmarks WHERE owner=? ORDER BY id DESC",(owner,))]}

def devices(db,owner,remove=None):
    if remove:
        db.execute("DELETE FROM tokens WHERE owner=? AND hash IN (SELECT hash FROM device_tokens WHERE device=?)",(owner,remove))
        db.commit()
    return {"items":[dict(r) for r in db.execute("""SELECT d.device,d.agent,max(t.expires) AS expires FROM device_tokens d
        JOIN tokens t ON t.hash=d.hash WHERE t.owner=? AND t.expires>? GROUP BY d.device ORDER BY expires DESC""",(owner,time.time()))]}
