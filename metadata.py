"""Look up public book metadata from the catalogues selected by the administrator."""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import json
import os
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

SOURCES = {"audible-de":"Audible.de", "audible-com":"Audible.com", "google":"Google Books", "openlibrary":"Open Library"}

def plain(value, limit=2000):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", str(value or ""))).split())[:limit]


def query_catalog(source, term):
    if source.startswith("audible-"):
        domain = "api.audible." + ("de" if source == "audible-de" else "com")
        base = "https://" + domain + "/1.0/catalog/products"
        params = {"keywords":term, "num_results":6,"image_sizes":"500", "response_groups":"contributors,product_desc,series,category_ladders,product_extended_attrs,product_attrs,media"}
    elif source == "google":
        base,params = "https://www.googleapis.com/books/v1/volumes", {"q":term,"maxResults":6}
        if key:=os.environ.get("AUDILEGE_GOOGLE_BOOKS_KEY"):
            params["key"]=key
    else:
        base,params = "https://openlibrary.org/search.json", {"q":term,"limit":6,"fields":"title,author_name,first_publish_year,subject,isbn,cover_i"}
    request = Request(base+"?"+urlencode(params), headers={"User-Agent":"Audilege-Server/0.2 (book catalogue lookup)","Accept":"application/json"})
    with urlopen(request, timeout=9) as response:
        data = json.loads(response.read(3_000_001))
    results = []
    if source.startswith("audible-"):
        for item in data.get("products",[]):
            names = lambda key: ", ".join(p["name"] for p in item.get(key,[]) if p.get("name"))
            tags = [p.get("name") for group in item.get("category_ladders",[]) for p in group.get("ladder",[]) if p.get("name")]
            results.append(dict(title=item.get("title"),author=names("authors"),narrator=names("narrators"),image=(item.get("product_images") or {}).get("500"),
                                series=", ".join(s.get("title","") for s in item.get("series",[])),volume=next((s.get("sequence") for s in item.get("series",[]) if s.get("sequence")),""),year=(item.get("release_date") or "")[:4],
                                publisher=item.get("publisher_name"),description=item.get("publisher_summary"),tags=", ".join(dict.fromkeys(tags))))
    elif source == "google":
        for entry in data.get("items",[]):
            item = entry["volumeInfo"]
            results.append(dict(title=item.get("title"), author=", ".join(item.get("authors",[])),publisher=item.get("publisher"),image=(item.get("imageLinks") or {}).get("thumbnail","").replace("http://","https://",1),
                                year=(item.get("publishedDate") or "")[:4],description=item.get("description"),
                                isbn=next((p["identifier"] for p in item.get("industryIdentifiers",[]) if p.get("type")=="ISBN_13"),""),
                                tags=", ".join(item.get("categories",[]))))
    else:
        for item in data.get("docs",[]):
            results.append(dict(title=item.get("title"),author=", ".join(item.get("author_name",[])),year=item.get("first_publish_year"),image=("https://covers.openlibrary.org/b/id/%d-L.jpg?default=false"%item["cover_i"]) if item.get("cover_i") else None,
                                isbn=next(iter(item.get("isbn",[])),""),tags=", ".join(item.get("subject",[])[:6])))
    return [{k:plain(v) for k,v in row.items() if v} | {"source":source} for row in results if row.get("title")]


def search(term, sources):
    term = term.strip() if isinstance(term,str) else ""
    if not 2 <= len(term) <= 200:
        raise ValueError("Bitte 2 bis 200 Zeichen für die Suche angeben.")
    if not isinstance(sources,list) or not sources or any(s not in SOURCES for s in sources):
        raise ValueError("Bitte mindestens einen verfügbaren Anbieter auswählen.")
    matches,failed = [],[]
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        jobs = {s:pool.submit(query_catalog,s,term) for s in dict.fromkeys(sources)}
        for source,job in jobs.items():
            try:
                matches.extend(job.result())
            except (OSError,ValueError,KeyError,TypeError):
                failed.append(SOURCES[source])
    return {"matches":matches, "unavailable":failed}


def cover_url(url):
    parts=urlsplit(url)
    hosts={"m.media-amazon.com","images-na.ssl-images-amazon.com","images-eu.ssl-images-amazon.com","covers.openlibrary.org","books.google.com","books.google.de","books.googleusercontent.com","archive.org"}
    if (parts.scheme!="https" or parts.username or parts.password or parts.port not in (None,443)
        or not (parts.hostname in hosts or (parts.hostname or "").endswith(".us.archive.org"))):
        raise ValueError("Diese Coveradresse gehört zu keinem unterstützten Katalog.")
    return url


class CoverRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,cover_url(newurl))


def fetch_cover(url):
    with build_opener(CoverRedirect()).open(cover_url(url),timeout=15) as response:
        return response.read(5*1024**2+1)


def image_type(data):
    if len(data)>5*1024**2:raise ValueError("Cover dürfen höchstens 5 MB groß sein.")
    if data.startswith(b"\xff\xd8\xff"):return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):return "image/png"
    if data.startswith(b"RIFF") and data[8:12]==b"WEBP":return "image/webp"
    raise ValueError("Bitte ein JPEG-, PNG- oder WebP-Cover auswählen.")
