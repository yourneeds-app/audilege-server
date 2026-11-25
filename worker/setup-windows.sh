#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
target="${1:-${XDG_DATA_HOME:-$HOME/.local/share}/audilege-worker}"
case "$target" in /*) ;; *) echo "Der Worker-Ordner muss ein absoluter Linux-Pfad sein."; exit 1 ;; esac
if [ "$(id -u)" = 0 ] || [ "$(uname -m)" != x86_64 ] || ! grep -qi wsl2 /proc/sys/kernel/osrelease; then
    echo "Der Worker benötigt WSL 2 (x64) mit einem normalen Linux-Benutzer."
    exit 1
fi
mkdir -p "$target/versions"
exec 9>"$target/.setup.lock"
flock 9
stamp=$(cd "$here" && sha256sum align.mjs package.json package-lock.json setup-windows.sh check.mjs | sha256sum | cut -d' ' -f1)

check_worker() (
    cd "$1" || exit 1
    test -s runtime-path || exit 1
    export PATH="$(cat runtime-path):/usr/local/bin:/usr/bin:/bin"
    node -e 'if (+process.versions.node.split(".")[0] < 24) process.exit(1)' &&
        ffmpeg -version >/dev/null &&
        ffprobe -v quiet -output_format json -show_versions >/dev/null &&
        node --input-type=module - < "$here/check.mjs"
)

if [ -f "$target/current/.version" ] && [ "$(cat "$target/current/.version")" = "$stamp" ] && check_worker "$target/current"; then
    echo "Abgleich bereit."
    exit 0
fi
# A manual installation from earlier releases may already contain everything.
if [ ! -L "$target/current" ] && cmp -s "$here/package-lock.json" "$target/package-lock.json" &&
    cmp -s "$here/align.mjs" "$target/align.mjs" && check_worker "$target"; then
    echo "Vorhandener Abgleich bereit."
    exit 0
fi
echo "Richte Node.js, FFmpeg und die Abgleich-Software für diesen Benutzer ein."
stage=$(mktemp -d "$target/versions/setup.XXXXXXXX")
cleanup() {
    if [ -n "$stage" ]; then rm -rf -- "$stage"; fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
cd "$stage"
fetch() {
    curl -fLsS --retry 3 --connect-timeout 20 --proto '=https' --proto-redir '=https' "$1" -o "$2"
    printf '%s  %s\n' "$3" "$2" | sha256sum -c -
}
fetch https://nodejs.org/dist/v24.12.0/node-v24.12.0-linux-x64.tar.xz node.tar.xz bdebee276e58d0ef5448f3d5ac12c67daa963dd5e0a9bb621a53d1cefbc852fd
mkdir node media
tar xJf node.tar.xz -C node --strip-components=1
fetch https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz media.tar.xz abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67
tar xJf media.tar.xz -C media --strip-components=1
rm node.tar.xz media.tar.xz
export PATH="$stage/node/bin:$stage/media:/usr/local/bin:/usr/bin:/bin"
cp "$here/package.json" "$here/package-lock.json" "$here/align.mjs" .
ONNXRUNTIME_NODE_INSTALL_CUDA=skip npm ci --no-fund --no-audit
printf '%s\n' "$stage/node/bin:$stage/media" > runtime-path
echo "Deutsches Sprachmodell laden und auf der CPU testen."
check_worker "$stage"
printf '%s\n' "$stamp" > .version
# Keep the previous version usable by jobs already in progress.
ln -s "$stage" "$stage/activate"
mv -Tf "$stage/activate" "$target/current"
stage=
echo "Abgleich bereit."
