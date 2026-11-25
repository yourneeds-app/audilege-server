"""Build the portable Windows x64 ZIP from this checkout."""
import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from maintenance import VERSION
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=ROOT.parent/"output"/("audilege-server-"+VERSION))
    dest=parser.parse_args().out.resolve()
    dest.mkdir(parents=True,exist_ok=True)
    name="Audilege-Server-"+VERSION
    archive=dest/(name+"-Windows-x64.zip")
    files=[*ROOT.glob("*.py"), ROOT/"README.md",ROOT/"README.en.md",ROOT/"THIRD_PARTY.md",*ROOT.glob("tests/test_*.py"),
           *(ROOT/"tinytag").glob("*.py"), ROOT/"tinytag"/"LICENSE",
           *(p for p in (ROOT/"web").iterdir() if p.is_file()),*(p for p in (ROOT/"worker").iterdir() if p.is_file())]
    with TemporaryDirectory(prefix="audilege-package-") as temp:
        work=Path(temp)
        subprocess.run([sys.executable,"-m","PyInstaller","--onefile","--console","--name","AudilegeServer",
                       "--exclude-module","numpy","--exclude-module","tkinter","--exclude-module","PyQt5","--exclude-module","PySide6","--exclude-module","IPython",
                       "--icon",str(ROOT/"web"/"icon.webp"),"--distpath",str(work/"dist"),"--workpath",str(work/"work"),
                       "--specpath",str(work),str(ROOT/"server.py")],check=True)
        installer=importlib.metadata.distribution("pyinstaller")
        license=next(p for p in installer.files if str(p).endswith("/licenses/COPYING.txt"))
        with ZipFile(archive.with_suffix(".tmp"),"w",ZIP_DEFLATED) as z:
            for p in files+[ROOT/"Start-Audilege.cmd",ROOT/"Audiobookshelf-Statistik.cmd"]:
                if p.name!="package_windows.py":z.write(p,name+"/"+p.relative_to(ROOT).as_posix())
            z.write(work/"dist"/"AudilegeServer.exe",name+"/AudilegeServer.exe")
            z.write(Path(sys.base_prefix)/"LICENSE.txt",name+"/Lizenzen/Python.txt")
            z.write(installer.locate_file(license),name+"/Lizenzen/PyInstaller.txt")
            pillow=importlib.metadata.distribution("pillow")
            notice=next(p for p in pillow.files if str(p).endswith("/licenses/LICENSE"))
            z.write(pillow.locate_file(notice),name+"/Lizenzen/Pillow.txt")
            # OpenSSL 3 uses the standard Apache license. Use the full upstream text.
            import os
            openssl=Path(os.environ.get("OPENSSL_LICENSE",r"C:\Program Files\Git\usr\share\licenses\libopenssl\LICENSE.txt"))
            if "Apache License" not in openssl.read_text(encoding="utf8"):raise ValueError("OpenSSL 3 license missing")
            z.write(openssl,name+"/Lizenzen/OpenSSL.txt")
    with ZipFile(archive.with_suffix(".tmp")) as z:
        if z.testzip():raise RuntimeError("ZIP-Prüfung fehlgeschlagen.")
    archive.with_suffix(".tmp").replace(archive)
    linux=dest/(name+"-Linux.tar.gz")
    with tarfile.open(linux.with_suffix(".tmp"),"w:gz") as tar:
        for p in files+[ROOT/"start.sh",ROOT/"Audiobookshelf-Statistik.sh"]:
            if p.name=="package_windows.py":continue
            entry=tar.gettarinfo(str(p),name+"/"+p.relative_to(ROOT).as_posix())
            entry.mode=0o755 if p.suffix==".sh" else 0o644
            entry.uid=entry.gid=0;entry.uname=entry.gname=""
            with p.open("rb") as f:tar.addfile(entry,f)
    linux.with_suffix(".tmp").replace(linux)
    (dest/"SHA256SUMS.txt").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in (archive,linux)),encoding="ascii")
    print(archive)

if __name__=="__main__":
    main()
