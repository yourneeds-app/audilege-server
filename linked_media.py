"""Read-only references to a server-side collection, including EPUB members."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import zipfile


def describe(root, path):
    path = path.resolve(strict=True)
    stat = path.stat()
    return [str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns]


def source_path(link, entry):
    root = Path(link["root"])
    path = root / entry[0]
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_relative_to(root) or not resolved.is_file():
        raise FileNotFoundError("Die eingebundene Quelldatei ist nicht verfügbar.")
    stat = resolved.stat()
    if (stat.st_size, stat.st_mtime_ns) != tuple(entry[1:]):
        raise FileNotFoundError("Die Quelle hat sich geändert. Der Scanner aktualisiert die Ausgabe.")
    return resolved


def reference(folder):
    path = folder / "linked.json"
    return json.loads(path.read_text(encoding="utf8")) if path.is_file() else {}


def original_epub(folder):
    link = reference(folder)
    return source_path(link, link["epub"]) if "epub" in link else folder / "book.epub"


def track_path(folder, name, fallback):
    link = reference(folder)
    if name in link.get("tracks", {}):
        return source_path(link, link["tracks"][name])
    return fallback


def repaired_member(folder,name):
    return folder/"epub-xml"/sha256(name.encode()).hexdigest()


@contextmanager
def member(folder, name, fallback):
    link = reference(folder)
    repaired=repaired_member(folder,name)
    if repaired.is_file():
        if "epub" in link:source_path(link,link["epub"])
        with repaired.open("rb") as stream:
            yield stream,repaired.stat().st_size
        return
    if "epub" in link:
        with zipfile.ZipFile(source_path(link, link["epub"])) as archive:
            info = archive.getinfo(name)
            with archive.open(info) as stream:
                yield stream, info.file_size
    else:
        path = track_path(folder, name, fallback)
        with path.open("rb") as stream:
            yield stream, path.stat().st_size


@contextmanager
def downloadable(folder):
    link = reference(folder)
    original=original_epub(folder) if "tracks" not in link else folder/"book.epub"
    if "tracks" not in link and not (folder/"epub-xml").is_dir():
        yield original
        return
    # Offline clients explicitly request a self-contained EPUB. Build it only for this download.
    with TemporaryDirectory(prefix="audilege-download-") as temp:
        target = Path(temp) / "audio.epub"
        with zipfile.ZipFile(original) as skeleton, zipfile.ZipFile(target, "w") as output:
            for item in skeleton.infolist():
                if item.filename in link.get("tracks",{}):
                    output.write(source_path(link, link["tracks"][item.filename]), item.filename)
                else:
                    repaired=repaired_member(folder,item.filename)
                    if repaired.is_file():
                        output.writestr(item,repaired.read_bytes())
                    else:
                        with skeleton.open(item) as src, output.open(item,"w",force_zip64=item.file_size>=zipfile.ZIP64_LIMIT) as dest:
                            shutil.copyfileobj(src,dest,256*1024)
        yield target

