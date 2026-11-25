#!/bin/sh
set -eu
target="${3:-${XDG_DATA_HOME:-$HOME/.local/share}/audilege-worker}"
if [ -L "$target/current" ]; then target=$(readlink -f "$target/current"); fi
if [ ! -f "$target/runtime-path" ]; then
    echo "Zuerst worker/install.sh mit Node 24 und FFmpeg ausführen."
    exit 1
fi
export PATH="$(cat "$target/runtime-path"):$PATH"
if [ "$2" = --probe ]; then
    exec ffprobe -protocol_whitelist file,pipe -v error \
        -show_entries stream=codec_type,codec_name:stream_disposition=attached_pic:format=duration:format_tags -of json "$1"
fi
if [ "$2" = --cover ]; then
    exec ffmpeg -nostdin -v error -protocol_whitelist file,pipe -i "$1" -map 0:v:0 -frames:v 1 -vf scale=600:900:force_original_aspect_ratio=decrease -c:v mjpeg -f image2pipe pipe:1
fi
if [ "$2" = --extract-audio ]; then
    exec ffmpeg -nostdin -v error -protocol_whitelist file,pipe -i "$1" -map 0:a:0 -vn -c:a libmp3lame -q:a 4 -f mp3 pipe:1
fi
if grep -qi wsl2 /proc/sys/kernel/osrelease; then
    # Native modules copy and rename EPUBs in ways that DrvFs cannot always represent.
    # Keep the job on the Linux filesystem and return only the finished publication.
    scratch=$(mktemp -d)
    ulimit -c 0
    trap 'rm -rf -- "$scratch"' EXIT
    trap 'exit 1' HUP INT TERM
    echo 'Arbeitskopie vorbereiten'
    cp -R -- "$1/audio" "$scratch/audio"
    cat "$1/source.epub" > "$scratch/source.epub"
    node "$target/align.mjs" "$scratch" "$2"
    echo 'Fertige Ausgabe übernehmen'
    cat "$scratch/result.epub" > "$1/result.epub.part"
    mv -f -- "$1/result.epub.part" "$1/result.epub"
else
    exec node "$target/align.mjs" "$1" "$2"
fi
