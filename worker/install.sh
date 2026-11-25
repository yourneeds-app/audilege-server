#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target="${AUDILEGE_WORKER_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/audilege-worker}"
mkdir -p "$target"
nodebin=$(command -v node) || { echo "Node.js 24 LTS fehlt."; exit 1; }
"$nodebin" -e 'if(Number(process.versions.node.split(".")[0])<24) process.exit(1)' || { echo "Node.js ab 24 benötigt."; exit 1; }
command -v npm >/dev/null
ffmpeg=$(command -v ffmpeg)
ffprobe=$(command -v ffprobe)
"$ffprobe" -v quiet -output_format json -show_versions >/dev/null || { echo "FFmpeg und FFprobe ab Version 7 installieren."; exit 1; }
cp "$here/package.json" "$here/package-lock.json" "$here/align.mjs" "$target/"
cd "$target"
npm ci --no-audit --no-fund
printf '%s\n' "$(dirname "$nodebin"):$(dirname "$ffmpeg"):$(dirname "$ffprobe")" > runtime-path
echo "Audilege-Abgleich eingerichtet."
