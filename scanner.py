"""Index a local media inbox without modifying the originals."""
import hashlib
import os
from pathlib import Path
import re
import stat
import shutil
import tempfile
from threading import Event, Lock, Thread
from time import time
from datetime import datetime

from library import AUDIO


def shelf_location(source, roots):
    if source:
        path = Path(source)
        for kind, root in roots:
            if root and path.is_relative_to(root):
                return {"kind": kind, "path": path.relative_to(root).as_posix()}
        return {"kind": "source", "path": path.name}
    return {"kind": "library", "path": ""}


def folder_series(location, metadata):
    if location["kind"] not in ("collection", "inbox"):
        return
    parts = location["path"].split("/")
    if parts[0].casefold() in ("audiobooks", "ebooks", "readaloud", "podcasts"):
        parts = parts[1:]
    for i in range(2, len(parts)):
        match = re.match(r"^(?:vol(?:ume)?|band)\.?\s*(\d+(?:[.,]\d+)?)\s*(?:[-–—]|$)", parts[i], re.I)
        if match:
            series = parts[i-1]
            if not metadata.get("series"):
                metadata["series"] = series
            if str(metadata["series"]).casefold() == series.casefold() and metadata.get("volume") in (None, ""):
                whole, _, decimal = match[1].replace(",", ".").partition(".")
                metadata["volume"] = str(int(whole)) + ("." + decimal if decimal else "")
            return


def fingerprint(paths, base=None):
    digest=hashlib.sha256()
    for path in paths:
        info=path.stat()
        name=path.relative_to(base) if base else path.name
        digest.update(os.fsencode(name)+b"\0"+f"{info.st_size}:{info.st_mtime_ns};".encode())
    return digest.hexdigest()


def real_entry(path):
    info=path.lstat()
    return not (stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)


DISC = re.compile(r"(?:cd|dis[ck])\s*[-_. ]*\d+(?:\s*(?:von|of)\s*\d+)?", re.I)


def natural(value):
    return [(1,int(v)) if v.isdigit() else (0,v.casefold()) for v in re.split(r"(\d+)",value)]


def audio_files(paths):
    return sorted((p for p in paths if p.suffix.lower() in AUDIO),key=lambda p:natural(p.name))


def groups(root):
    grouped_discs=set()
    for folder,dirs,files in os.walk(root):
        parent=Path(folder)
        dirs[:]=[n for n in dirs if not n.startswith(".") and real_entry(parent/n)]
        files=[parent/n for n in files if not n.startswith((".","~")) and real_entry(parent/n)]
        for path in sorted(p for p in files if p.suffix.lower()==".epub"):
            yield "ebook",path,[path]
        if parent in grouped_discs:
            grouped_discs.remove(parent)
            continue
        audio=audio_files(files)
        podcasts=any(p.casefold()=="podcasts" for p in parent.relative_to(root).parts)
        if parent==root or parent==root/"Audiobooks" or podcasts:
            for p in audio:yield "podcast" if podcasts else "audio",p,[p]
        else:
            for name in sorted((n for n in dirs if DISC.fullmatch(n)),key=natural):
                disc=parent/name
                tracks=audio_files(p for p in disc.iterdir() if not p.name.startswith((".","~"))
                                   and real_entry(p) and p.is_file())
                audio.extend(tracks)
                grouped_discs.add(disc)
            if audio:yield "audio",parent,audio


class Inbox:
    def __init__(self,lib,path=None):
        self.lib=lib
        self.fixed=path is not None
        with lib.db() as db:
            linked=db.execute("SELECT value FROM server_settings WHERE key='linked_folder'").fetchone()
            self.linked=Path(linked[0]) if linked and linked[0] else None
            saved=db.execute("SELECT value FROM server_settings WHERE key='media_folder'").fetchone()
        self.root=self.validate(path or (saved[0] if saved else lib.data/"Medieneingang"))
        if self.fixed or not saved:self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_dir():self.layout(self.root)
        self.pending_root=None
        self.lock=Lock()
        self.wakeup=Event()
        self.manual=False
        self.seen={}
        self.failed={}
        self.state={"running":False,"last":"","imported":0,"waiting":0,"errors":[]}
        self.stopped=Event()

    def status(self):
        with self.lock:return self.state.copy()|{"folder":str(self.pending_root or self.root),"linkedFolder":str(self.linked or ""),"interval":15,"fixed":self.fixed}

    def validate(self,value):
        root=Path(value).resolve()
        if root==root.parent or self.lib.data.is_relative_to(root) or any(root.is_relative_to(self.lib.data/d) for d in ("editions","jobs","uploads","backups","private","trash","thumbnails")):
            raise ValueError("Bitte einen separaten Medienordner auswählen.")
        return root

    @staticmethod
    def layout(root):
        for name in ("Ebooks","Audiobooks","Readaloud","Podcasts"):
            child=root/name
            child.mkdir(exist_ok=True)
            if not child.is_dir() or not real_entry(child):raise ValueError("Der Medienunterordner ist nicht zugänglich.")

    @staticmethod
    def separate(a,b):
        if b and (a.is_relative_to(b) or b.is_relative_to(a)):
            raise ValueError("Medieneingang und direkt eingebundene Sammlung benötigen getrennte Ordner.")

    def change_linked(self,value):
        folder=None
        if value:
            if not isinstance(value,str) or not Path(value).is_absolute():
                raise ValueError("Bitte den vollständigen Ordnerpfad auf dem Server eingeben.")
            folder=self.validate(value)
            self.separate(folder,self.lib.data)
            if not folder.is_dir():
                raise ValueError("Sammlung nicht erreichbar.")
            with os.scandir(folder):pass
        with self.lock:
            if folder:self.separate(folder,self.pending_root or self.root)
            with self.lib.db() as db:
                db.execute("INSERT OR REPLACE INTO server_settings VALUES('linked_folder',?)",(str(folder or ""),))
            self.linked=folder
        self.request()

    def change_folder(self,value):
        if self.fixed:raise ValueError("Der Medienordner ist über den Serverstart festgelegt.")
        if not isinstance(value,str) or not Path(value).is_absolute():
            raise ValueError("Bitte den vollständigen Ordnerpfad auf dem Server eingeben.")
        folder=self.validate(value)
        if not folder.is_dir():raise ValueError("Diesen Ordner kann der Server nicht öffnen.")
        with self.lock:
            self.separate(folder,self.linked)
            self.layout(folder)
            with tempfile.TemporaryFile(dir=folder):pass
            if not shutil.disk_usage(folder).free:raise ValueError("Kein freier Speicherplatz.")
            with self.lib.db() as db:
                db.execute("INSERT OR REPLACE INTO server_settings VALUES('media_folder',?)",(str(folder),))
            self.pending_root=folder
        self.request()

    def request(self):
        with self.lock:self.manual=True
        self.wakeup.set()

    def start(self):
        Thread(target=self.loop,daemon=True,name="Audilege-Medieneingang").start()

    def loop(self):
        while not self.stopped.is_set():
            self.wakeup.clear()
            with self.lock:
                manual,self.manual=self.manual,False
                if self.pending_root is not None:
                    self.root,self.pending_root=self.pending_root,None
                    self.seen={};self.failed={}
            self.scan(manual)
            from curation import start_import_review
            start_import_review(self.lib)
            self.wakeup.wait(15)

    def scan(self,manual=False):
        with self.lock:self.state["running"]=True
        count,waiting=0,0
        errors=[];observed={}
        try:
            with self.lock:
                linked=self.linked
            if self.root.is_dir():
                errors.extend(self.export_completed())
            else:
                errors.append("Der Medieneingang ist derzeit nicht erreichbar.")
            def sources():
                for root,reference in ((self.root,None),(linked,linked)):
                    if root is None:continue
                    if not root.is_dir() or root.resolve()!=root:
                        if reference:errors.append("Die direkt eingebundene Sammlung ist derzeit nicht erreichbar.")
                        continue
                    for kind,base,files in groups(root):
                        yield root,reference,kind,base,files
            with self.lib.db() as db:
                indexed={r[0]:(r[1],r[2]) for r in db.execute("SELECT source,signature,display_source FROM scanned_media")}
            display_updates=[]
            for root,reference,kind,base,files in sources():
                key=os.path.normcase(str(base));rel=str(base.relative_to(root))
                try:
                    multidisc=kind=="audio" and any(p.parent!=base for p in files) and base.is_dir()
                    relative=base if multidisc else None
                    sig=fingerprint(files,relative);observed[key]=sig
                    previous=indexed.get(key)
                    if previous and previous[0]==sig:
                        if previous[1]!=str(base):display_updates.append((str(base),key))
                        continue
                    if not manual and self.failed.get(key,(None,))[0]==sig:
                        errors.append(self.failed[key][1]);continue
                    if self.seen.get(key)!=sig or any(time()-p.stat().st_mtime<5 for p in files):
                        waiting+=1;continue
                    def verify():
                        if fingerprint(files,relative)!=sig:
                            raise InterruptedError("Kopiervorgang läuft noch.")
                    title=base.name if base.is_dir() and (multidisc or len(files)>1) else ""
                    tracks=[(p,p.relative_to(base).as_posix() if multidisc else p.name) for p in files]
                    self.lib.import_tracks(tracks,{"category":kind,"title":title},scan=(key,sig),verify=verify,link_root=reference)
                    display_updates.append((str(base),key))
                    self.failed.pop(key,None);count+=1
                except (FileNotFoundError,InterruptedError):
                    waiting+=1
                except Exception as exc:
                    detail=rel+" · "+str(exc)[:200]
                    self.failed[key]=(observed.get(key),detail);errors.append(detail)
            if display_updates:
                with self.lib.db() as db:
                    db.executemany("UPDATE scanned_media SET display_source=? WHERE source=?",display_updates)
                    db.execute("INSERT OR REPLACE INTO server_settings VALUES('catalog_revision',lower(hex(randomblob(16))))")
        except OSError as exc:
            errors.append(str(exc)[:240])
        finally:
            self.seen=observed
            self.failed={k:v for k,v in self.failed.items() if k in observed}
            with self.lock:
                self.state={"running":False,"last":datetime.now().astimezone().isoformat(timespec="seconds"),
                            "imported":count,"waiting":waiting,"errors":errors[:12]}

    def export_completed(self):
        from maintenance import digest
        output=self.root/"Readaloud"
        errors=[]
        with self.lib.db() as db:
            rows=db.execute("""SELECT x.*,e.folder,e.book FROM readalong_exports x JOIN editions e ON x.edition=e.id
                WHERE x.path IS NULL""").fetchall()
        for row in rows:
            target=output/row["filename"]
            try:
                if target.parent!=output or not output.is_dir() or not real_entry(output):
                    raise OSError("Readaloud ist nicht verfügbar.")
                source=self.lib.data/"editions"/row["folder"]/"book.epub"
                if target.exists():
                    if not real_entry(target) or digest(target)!=digest(source):
                        raise OSError("Eine andere Datei belegt denselben Namen.")
                else:
                    with tempfile.NamedTemporaryFile(dir=output,prefix=".audilege-",delete=False) as temp:
                        stage=Path(temp.name)
                    try:
                        shutil.copyfile(source,stage)
                        if digest(stage)!=digest(source):raise OSError("Kopie konnte nicht bestätigt werden.")
                        if os.name=="nt":stage.rename(target)
                        else:os.link(stage,target)
                    finally:stage.unlink(missing_ok=True)
                with self.lib.db() as db:
                    db.execute("INSERT OR REPLACE INTO scanned_media(source,signature,book) VALUES(?,?,?)",
                               (os.path.normcase(str(target)),fingerprint([target]),row["book"]))
                    db.execute("UPDATE readalong_exports SET path=? WHERE edition=?",(str(target),row["edition"]))
            except OSError as ex:errors.append(target.name+" · "+str(ex))
        return errors
