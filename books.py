"""Index EPUB spine, cover and SMIL cues and serve individual resources without unzipping to client paths."""
import hashlib
import linked_media
import json
import math
import mimetypes
import posixpath
import re
import shutil
import subprocess
from media_tools import audio_metadata, command, probe
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape


def ref(parent, link):
    parts = urlsplit(link)
    path = posixpath.normpath(posixpath.join(posixpath.dirname(parent), unquote(parts.path))) if parts.path else parent
    if parts.scheme or parts.netloc or path.startswith(("/", "../")) or "\\" in path:
        raise ValueError("Ungültiger Verweis im EPUB.")
    return path, unquote(parts.fragment)


def seconds(value):
    value = value.removeprefix("npt=").strip()
    if value.endswith("ms"):
        return float(value[:-2]) / 1000
    parts = value.rstrip("s").split(":")
    return sum(float(v) * 60 ** i for i, v in enumerate(reversed(parts)))


def resource(folder, name):
    return folder / hashlib.sha256(name.encode()).hexdigest()


def xml(folder, name):
    with linked_media.member(folder,name,resource(folder,name)) as (stream,size):
        if size > 24 * 1024**2:
            raise ValueError("Ein Textabschnitt überschreitet 24 MB.")
        return ET.parse(stream).getroot()


def local(node):
    return node.tag.split("}")[-1]


def words(node):
    return " ".join("".join(node.itertext()).split())


def marked_text(body, path):
    # Preserve punctuation and whitespace outside word spans as part of the enclosing sentence.
    tokens, word_ids = [], set()
    def visit(node, anchor="", sentence=""):
        key = node.get("id")
        types = node.get("{http://www.idpf.org/2007/ops}type", "").split()
        if key:
            anchor = path + "#" + key
            if "storyteller:sentence-span" in types:
                sentence = anchor
            if "storyteller:word-span" in types:
                word_ids.add(anchor)
        if node.text:
            tokens.append([node.text, anchor, sentence])
        for child in node:
            visit(child, anchor, sentence)
            if child.tail:
                tokens.append([child.tail, anchor, sentence])
        if local(node) in ("p","h1","h2","h3","li","br","div"):
            tokens.append(["\n","", ""])
    visit(body)
    return tokens, word_ids


def epub_fields(meta):
    def values(tag):
        return ", ".join(n.text.strip() for n in meta.findall("{*}"+tag) if n.text and n.text.strip())
    series = next((n.get("content") or n.text for n in meta.findall("{*}meta") if n.get("name")=="calibre:series" or n.get("property")=="belongs-to-collection"),"")
    isbn=next((n.text for n in meta.findall("{*}identifier") if n.text and
               ("isbn" in n.text.lower() or re.fullmatch(r"(?:97[89])?[\d-]{9,16}[\dXx]",n.text.strip()))),"")
    volume=next((n.get("content") or n.text for n in meta.findall("{*}meta") if n.get("name")=="calibre:series_index" or n.get("property")=="group-position"),"")
    fields=dict(series=series,volume=volume,tags=values("subject"),publisher=values("publisher"),year=values("date")[:4],
                description=values("description"),isbn=isbn.removeprefix("urn:isbn:"))
    return {k:v[:2000] for k,v in fields.items() if v}


def index_epub(epub, folder, *, linked=False):
    folder.mkdir(exist_ok=True, parents=True)
    files = {}
    with zipfile.ZipFile(epub) as z:
        entries = [e for e in z.infolist() if not e.is_dir()]
        if len(entries) > 45000 or sum(e.file_size for e in entries) > 12 * 1024**3:
            raise ValueError("Dieses EPUB ist zu groß.")
        for e in entries:
            name = e.filename
            if posixpath.normpath(name) != name or name.startswith(("/", "../")) or "\\" in name or name in files:
                raise ValueError("Ungültiger Dateiname im EPUB.")
            files[name] = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if linked:
                continue
            with z.open(e) as src, resource(folder, name).open("wb") as dest:
                shutil.copyfileobj(src, dest, 256 * 1024)
    container = xml(folder, "META-INF/container.xml")
    root = container.find(".//{*}rootfile")
    if root is None:
        raise ValueError("Das EPUB enthält kein Inhaltsverzeichnis.")
    opf = root.attrib["full-path"]
    package = xml(folder, opf)
    meta = package.find("{*}metadata")
    title = meta.findtext("{*}title") or epub.stem
    author = ", ".join(n.text for n in meta.findall("{*}creator") if n.text)
    language = meta.findtext("{*}language") or "de"
    cover_id = next((n.get("content") for n in meta.findall("{*}meta") if n.get("name") == "cover"), None)
    manifest, cover = {}, None
    for item in package.findall(".//{*}manifest/{*}item"):
        key = item.get("id")
        path, _ = ref(opf, item.attrib["href"])
        if path not in files:
            continue
        mime = item.get("media-type", "")
        if re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+",mime):
            files[path] = mime
        manifest[key] = (path, item.get("media-overlay"))
        if ("cover-image" in item.get("properties", "").split() or key == cover_id) and files[path] in ("image/jpeg","image/png","image/webp"):
            cover = path
    if linked and cover:
        with zipfile.ZipFile(epub) as archive:
            if archive.getinfo(cover).file_size <= 24 * 1024**2:
                with archive.open(cover) as src, resource(folder,cover).open("wb") as dest:
                    shutil.copyfileobj(src,dest)
            else:
                cover=None
    sections = []
    for item in package.findall(".//{*}spine/{*}itemref"):
        path, overlay = manifest[item.attrib["idref"]]
        page = xml(folder, path)
        body = page.find(".//{*}body")
        if body is None:
            continue
        anchors = {node.get("id"): node for node in body.iter() if node.get("id")}
        heading = next((words(n) for n in body.iter() if local(n) in ("h1","h2","h3") and words(n)), None)
        lines = [words(n) for n in body.iter() if local(n) in ("p","h1","h2","h3","li") and words(n)]
        cues = []
        if overlay:
            smil, _ = manifest[overlay]
            for par in xml(folder, smil).findall(".//{*}par"):
                txt, audio = par.find("{*}text"), par.find("{*}audio")
                if txt is None or audio is None:
                    continue
                target, anchor = ref(smil, txt.attrib["src"])
                sound, _ = ref(smil, audio.attrib["src"])
                begin, end = seconds(audio.get("clipBegin","0")), seconds(audio.attrib["clipEnd"])
                if target != path and target in files:
                    continue  # Some EPUBs share one overlay across several spine documents.
                if target != path or sound not in files or not files[sound].startswith("audio/"):
                    raise ValueError(f"Text oder Tonspur im Zeitplan {smil} nicht gefunden.")
                if anchor and anchor not in anchors:
                    raise ValueError("Zeitmarke ohne zugehörige Textstelle.")
                if not math.isfinite(begin+end) or not 0 <= begin <= end:
                    raise ValueError(f"Ungültiges Zeitintervall im Zeitplan {smil}.")
                if begin==end:
                    # CTC can assign a word two identical timestamps. Its text remains in the spine.
                    continue
                cues.append({"path":sound, "begin":begin, "end":end, "anchor":path+"#"+anchor})
        tokens, word_ids = marked_text(body,path)
        sections.append({"path":path, "name":heading or f"Abschnitt {len(sections)+1}", "lines":lines or [words(body)],
                         "tokens":tokens, "wordTiming":bool(cues) and all(c["anchor"] in word_ids for c in cues), "cues":cues})
    if not sections:
        raise ValueError("Das EPUB enthält keine lesbaren Abschnitte.")
    spine_step = (list(package).index(package.find("{*}spine")) + 1) * 2
    result = dict(title=title, author=author, metadata=epub_fields(meta), language=language, cover=cover, sections=sections, files=files, spineStep=spine_step)
    (folder/"resources.json").write_text(json.dumps(files),encoding="utf8")
    (folder/"index.json").write_text(json.dumps(result,ensure_ascii=False),encoding="utf8")
    return result


def audio_epub(target, tracks, title, author, *, linked=False):
    """Give the current Android reader seekable audio chapters in an EPUB media overlay."""
    items, spine, timings = [], [], []
    fields={}
    with zipfile.ZipFile(target, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        for i, (track, label) in enumerate(tracks):
            metadata = probe(track)
            if i==0:
                fields=audio_metadata(metadata)
                title=title or fields.pop("title","") or Path(label).stem
                author=author or fields.pop("author","")
                image=metadata.get("picture")
                if image and len(image)<=24*1024**2 and image.startswith((b"\xff\xd8",b"\x89PNG")):
                    cover,mime=("cover.jpg","image/jpeg") if image.startswith(b"\xff\xd8") else ("cover.png","image/png")
                    z.writestr(cover,image)
                    items.append(f'<item id="cover" href="{cover}" media-type="{mime}" properties="cover-image"/>')
                elif any(s.get("disposition",{}).get("attached_pic") for s in metadata["streams"]):
                    picture=subprocess.run(command(track,"--cover"),capture_output=True,timeout=60)
                    if picture.returncode==0 and picture.stdout.startswith(b"\xff\xd8"):
                        z.writestr("cover.jpg",picture.stdout)
                        items.append('<item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
            duration = float(metadata["format"]["duration"])
            if not any(s["codec_type"]=="audio" for s in metadata["streams"]) or not math.isfinite(duration) or duration <= 0:
                raise ValueError("Die Datei enthält keine gültige Tonspur.")
            ext = track.suffix.lower()
            audio = f"track{i}{ext}"
            mime = {".m4b":"audio/mp4",".m4a":"audio/mp4",".mp3":"audio/mpeg",".ogg":"audio/ogg",".wav":"audio/wav",".flac":"audio/flac"}[ext]
            items += [f'<item id="p{i}" href="{i}.xhtml" media-type="application/xhtml+xml" media-overlay="s{i}"/>',f'<item id="s{i}" href="{i}.smil" media-type="application/smil+xml"/>', f'<item id="a{i}" href="{audio}" media-type="{mime}"/>']
            spine.append(f'<itemref idref="p{i}"/>')
            timings.append(f'<meta property="media:duration" refines="#s{i}">{duration:.3f}s</meta>')
            if linked:
                z.writestr(audio,b'')
            else:
                z.write(track,audio)
            z.writestr(f"{i}.xhtml",f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(label)}</title></head><body><h1 id="track">{escape(label)}</h1></body></html>')
            z.writestr(f"{i}.smil",f'<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0"><body><seq><par><text src="{i}.xhtml#track"/><audio src="{audio}" clipBegin="0s" clipEnd="{duration:.3f}s"/></par></seq></body></smil>')
        z.writestr("book.opf", f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:audilege:{target.parent.name}</dc:identifier><dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator><dc:language>de</dc:language>{"".join(timings)}</metadata><manifest>{"".join(items)}</manifest><spine>{"".join(spine)}</spine></package>')
    return {k:v for k,v in fields.items() if k not in ("title","author")}
