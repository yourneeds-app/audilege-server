"""Provision and use the alignment worker for the native Windows server."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.request import urlopen

MANAGED = "Audilege-Worker"
BASE_IMAGE = "ubuntu-base-24.04.5-base-amd64.tar.gz"
BASE_URL = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/" + BASE_IMAGE
BASE_HASH = "e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86"


def wsl_output(*args):
    data = subprocess.check_output(["wsl.exe", *args])
    encoding = "utf-16-le" if b"\x00" in data else "utf-8-sig"
    return data.decode(encoding).strip("\ufeff \r\n")


def linux_command(distro, user=None):
    args = ["wsl.exe", "--distribution", distro]
    if user:
        args += ["--user", user]
    return args + ["--cd", "/", "--exec"]


def linux_path(cmd, path):
    return subprocess.check_output(cmd + ["wslpath", "-a", "-u", Path(path).resolve().as_posix()],
                                   encoding="utf-8").strip()


def worker_command(shim, path, mode):
    cmd = linux_command(os.environ.get("AUDILEGE_WSL", "Ubuntu"), os.environ.get("AUDILEGE_WSL_USER"))
    args = cmd + ["sh", linux_path(cmd, shim), linux_path(cmd, path), mode]
    if target := os.environ.get("AUDILEGE_WORKER_DIR"):
        args.append(target)
    return args


def ensure_wsl():
    if not shutil.which("wsl.exe"):
        raise RuntimeError("Dieses Paket benötigt Windows x64 mit aktuellem WSL 2. Windows aktualisieren und erneut starten.")
    if subprocess.run(["wsl.exe", "--status"], stdout=subprocess.DEVNULL).returncode == 0:
        return
    print("Windows richtet WSL 2 ein. Bitte die Windows-Abfrage bestätigen.", flush=True)
    elevation = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                    "$ErrorActionPreference='Stop'; $p=Start-Process wsl.exe -ArgumentList '--install','--no-distribution' "
                    "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"], check=False)
    if elevation.returncode in (1641, 3010):
        raise RuntimeError("Windows benötigt einen Neustart. Danach Start-Audilege.cmd erneut öffnen.")
    if subprocess.run(["wsl.exe", "--status"], stdout=subprocess.DEVNULL).returncode:
        raise RuntimeError("WSL 2 ist noch nicht bereit. Falls Windows einen Neustart verlangt, den PC neu starten "
                           "und Start-Audilege.cmd erneut öffnen. Virtualisierung muss aktiviert sein.")


def base_directory(distro):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Lxss") as root:
        for index in range(winreg.QueryInfoKey(root)[0]):
            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                if winreg.QueryValueEx(key, "DistributionName")[0].casefold() == distro.casefold():
                    return Path(os.path.expandvars(winreg.QueryValueEx(key, "BasePath")[0])).resolve()
    raise RuntimeError("Die registrierte Audilege-Worker-Umgebung wurde nicht gefunden.")


def install_base(store):
    print("Audilege lädt die Ubuntu-Grundlage für den Worker.", flush=True)
    store.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(dir=store) as temp:
        image = Path(temp) / BASE_IMAGE
        digest = hashlib.sha256()
        with urlopen(BASE_URL, timeout=120) as response, image.open("wb") as target:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                target.write(chunk)
        if digest.hexdigest() != BASE_HASH:
            raise RuntimeError("Die Prüfsumme des Ubuntu-Downloads stimmt nicht. Bitte die Einrichtung erneut starten.")
        imported=subprocess.run(["wsl.exe", "--import", MANAGED, str(store/"linux"), str(image), "--version", "2"])
        if imported.returncode:
            raise RuntimeError("Windows konnte die WSL-2-Umgebung nicht starten. Die WSL-Meldung oben prüfen. "
                               "Virtualisierung und die Windows-Funktion „Plattform für virtuelle Computer“ werden benötigt. "
                               "Nach einem angeforderten Neustart dieselbe Startdatei öffnen.")


def existing_worker(distros):
    for name in sorted(distros, key=lambda s: s != "Ubuntu"):
        if not re.fullmatch(r"Ubuntu(?:-\d+\.\d+)?", name, re.I):
            continue
        cmd = linux_command(name)
        found = subprocess.run(cmd + ["sh", "-c",
            'test "$(id -u)" != 0 && grep -qi wsl2 /proc/sys/kernel/osrelease && '
            'test -s "$HOME/.local/share/audilege-worker/runtime-path"'], capture_output=True)
        if found.returncode == 0:
            return name
    return MANAGED


def prepare_worker(worker_folder):
    import msvcrt
    store = Path(os.environ["LOCALAPPDATA"])/"Audilege-Worker"
    store.mkdir(parents=True, exist_ok=True)
    with (store/"setup.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("Die Worker-Einrichtung läuft bereits in einem anderen Fenster.") from error
        provision(worker_folder, store)


def provision(worker_folder, store):
    ensure_wsl()
    installed = wsl_output("--list", "--quiet").splitlines()
    names = {name.casefold(): name for name in installed}
    selected = os.environ.get("AUDILEGE_WSL") or names.get(MANAGED.casefold()) or existing_worker(installed)
    distro = names.get(selected.casefold(), selected)
    user = os.environ.get("AUDILEGE_WSL_USER")
    if distro.casefold() == MANAGED.casefold():
        if MANAGED.casefold() not in names:
            install_base(store)
        if not os.path.samefile(base_directory(MANAGED), store/"linux"):
            raise RuntimeError("Der WSL-Name Audilege-Worker gehört bereits zu einer anderen Installation.")
        root = linux_command(distro, "root")
        script = worker_folder/"ubuntu-base.sh"
        # Send the packaged script on stdin; this also works before Windows drives are mounted.
        with script.open("rb") as source:
            subprocess.run(root + ["sh", "-s"], stdin=source, check=True)
        user = "audilege"
    elif distro.casefold() not in names:
        raise RuntimeError(f"Die eingestellte WSL-Distribution {distro} ist nicht installiert.")
    cmd = linux_command(distro, user)
    print(f"Abgleich in {distro} prüfen. Beim ersten Start werden Werkzeuge und deutsches Sprachmodell eingerichtet.", flush=True)
    args = cmd + ["sh", linux_path(cmd, worker_folder/"setup-windows.sh")]
    if target := os.environ.get("AUDILEGE_WORKER_DIR"):
        args.append(target)
    subprocess.run(args, check=True)
    os.environ["AUDILEGE_WSL"] = distro
    if user:
        os.environ["AUDILEGE_WSL_USER"] = user
