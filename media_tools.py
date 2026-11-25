import json
from pathlib import Path
import shutil
import subprocess
import sys

PROBE = ["-show_entries","stream=codec_type,codec_name:stream_disposition=attached_pic:format=duration:format_tags","-of","json"]
COVER = ["-map","0:v:0","-frames:v","1","-vf","scale=600:900:force_original_aspect_ratio=decrease","-c:v","mjpeg","-f","image2pipe","pipe:1"]
AUDIO = ["-map","0:a:0","-vn","-c:a","libmp3lame","-q:a","4","-f","mp3","pipe:1"]


def command(path, mode):
    binary = "ffprobe" if mode=="--probe" else "ffmpeg"
    if shutil.which(binary):
        base = [binary,"-v","error","-protocol_whitelist","file,pipe"]
        return base+PROBE+[str(path)] if mode=="--probe" else base+["-nostdin","-i",str(path)]+(COVER if mode=="--cover" else AUDIO)
    if sys.platform=="win32":
        from windows_worker import worker_command
        root=Path(sys.executable if getattr(sys,"frozen",False) else __file__).resolve().parent
        return worker_command(root/"worker"/"run.sh",path,mode)
    raise ValueError(f"Für diesen Import wird {binary} benötigt.")


def probe(path):
    r=subprocess.run(command(path,"--probe"),capture_output=True,timeout=60,check=True)
    return json.loads(r.stdout)


def audio_metadata(info):
    tags={k.lower():str(v).strip() for k,v in info["format"].get("tags",{}).items()}
    fields={"title":tags.get("album") or tags.get("title"), "author":tags.get("album_artist") or tags.get("artist"),
            "narrator":tags.get("narrator"),"year":(tags.get("date") or "")[:4],"publisher":tags.get("publisher"),
            "series":tags.get("series"),"tags":tags.get("genre"),"description":tags.get("description") or tags.get("comment"),
            "isbn":tags.get("isbn")}
    return {k:v[:2000] for k,v in fields.items() if v}
