"""Verificação e instalação de atualizações (GitHub Releases, ou git quando roda do código-fonte).

Tipos de instalação e como cada um se atualiza:
  win-installer  instalado pelo Portinho-Setup.exe -> baixa o Setup novo e roda com /SILENT
                 (o Inno mostra a barra de instalação e reabre o app no final)
  win-portable   Portinho.exe avulso              -> baixa o .exe novo e troca o arquivo
  deb            /opt/portinho via .deb            -> baixa o .deb e instala com pkexec apt-get
  linux-dir      pasta portátil (.tar.gz)          -> baixa o .tar.gz e troca a pasta
  git            código-fonte clonado              -> git pull + pip install -r requirements.txt
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

from . import __version__

REPO = "paulocremas/portinho"
API_URL = os.environ.get("PORTINHO_UPDATE_API", f"https://api.github.com/repos/{REPO}/releases/latest")
UA = {"User-Agent": f"Portinho/{__version__}", "Accept": "application/vnd.github+json"}
FROZEN = getattr(sys, "frozen", False)
SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cancelled(Exception):
    pass


class UpdateInfo:
    def __init__(self, kind, version, notes, url=None, size=0, asset_name=""):
        self.kind, self.version, self.notes = kind, version, notes
        self.url, self.size, self.asset_name = url, size, asset_name


def _popen_kw():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def parse_version(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def has_internet(timeout=2.0):
    host = re.sub(r"^https?://([^/:]+).*", r"\1", API_URL)
    port = 80 if API_URL.startswith("http://") else 443
    m = re.match(r"^https?://[^/:]+:(\d+)", API_URL)
    if m:
        port = int(m.group(1))
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def install_kind():
    if not FROZEN:
        if os.path.isdir(os.path.join(SRC_ROOT, ".git")) and shutil.which("git"):
            return "git"
        return "source"
    exe = os.path.abspath(sys.executable)
    exe_dir = os.path.dirname(exe)
    onefile = os.path.normcase(os.path.abspath(getattr(sys, "_MEIPASS", exe_dir))) != os.path.normcase(exe_dir)
    if os.name == "nt":
        if onefile:
            return "win-portable"
        return "win-installer"     # pasta: instalada pelo Setup (ou atualiza para a versão instalada)
    if exe_dir.startswith("/opt/portinho"):
        try:
            if subprocess.run(["dpkg-query", "-W", "portinho"], capture_output=True).returncode == 0:
                return "deb"
        except OSError:
            pass
    return "linux-dir"


ASSET_PATTERNS = {
    "win-installer": r"Portinho-Setup-.*\.exe$",
    "win-portable": r"^Portinho\.exe$",
    "deb": r"_amd64\.deb$",
    "linux-dir": r"_linux_x86_64\.tar\.gz$",
}


def check(timeout=4.0):
    """Retorna UpdateInfo se houver versão nova, senão None. Nunca levanta erro."""
    try:
        if not has_internet():
            return None
        kind = install_kind()
        if kind == "git":
            return _check_git(timeout)
        if kind == "source":
            return None
        req = urllib.request.Request(API_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.load(r)
        tag = rel.get("tag_name", "")
        if parse_version(tag) <= parse_version(__version__):
            return None
        pat = re.compile(ASSET_PATTERNS[kind])
        for a in rel.get("assets", []):
            if pat.search(a.get("name", "")):
                return UpdateInfo(kind, tag.lstrip("v"), rel.get("body") or "",
                                  a["browser_download_url"], a.get("size", 0), a["name"])
        return None
    except Exception:
        return None


def _git(*args, timeout=15):
    return subprocess.run(["git", "-C", SRC_ROOT, *args], capture_output=True, text=True,
                          timeout=timeout, **_popen_kw())


def _check_git(timeout):
    if _git("fetch", "--quiet", timeout=max(timeout, 8)).returncode != 0:
        return None
    r = _git("rev-list", "--count", "HEAD..@{u}")
    if r.returncode != 0 or int(r.stdout.strip() or 0) == 0:
        return None
    log = _git("log", "--format=• %s", "HEAD..@{u}").stdout.strip()
    sha = _git("rev-parse", "--short", "@{u}").stdout.strip()
    return UpdateInfo("git", sha, log)


# ---------------------------------------------------------------- instalação
def download(url, dest, progress, cancelled=lambda: False):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancelled():
                raise Cancelled()
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            progress(done, total)


def perform(info, step, progress, cancelled=lambda: False):
    """Instala a atualização. Retorna o comando para reabrir o app (ou None se o
    instalador externo cuida disso). step(n, texto) / progress(pct ou -1, texto)."""
    tmp = tempfile.mkdtemp(prefix="portinho_update_")

    def dl():
        step(1, "Baixando a atualização")
        path = os.path.join(tmp, info.asset_name)

        def cb(done, total):
            mb = f"{done / 1e6:.1f}" + (f" de {total / 1e6:.1f} MB" if total else " MB")
            progress(done * 100 / total if total else -1, mb)
        download(info.url, path, cb, cancelled)
        return path

    if info.kind == "git":
        step(1, "Baixando as mudanças (git pull)")
        progress(-1, "")
        r = _git("pull", "--ff-only", timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "git pull falhou")
        step(2, "Instalando dependências")
        req = os.path.join(SRC_ROOT, "requirements.txt")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", req],
                           capture_output=True, text=True, **_popen_kw())
        if r.returncode != 0 and "No module named pip" in r.stderr and shutil.which("uv"):
            # ambientes criados pelo uv não têm pip
            r = subprocess.run(["uv", "pip", "install", "-q", "--python", sys.executable, "-r", req],
                               capture_output=True, text=True, **_popen_kw())
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-800:] or "falha ao instalar dependências")
        return [sys.executable, os.path.join(SRC_ROOT, "run.py")]

    if info.kind == "win-installer":
        setup = dl()
        step(2, "Abrindo o instalador")
        progress(-1, "O instalador mostra o andamento e reabre o Portinho no final")
        subprocess.Popen([setup, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0), env=clean_env())
        return None

    if info.kind == "win-portable":
        new = dl()
        step(2, "Instalando")
        progress(-1, "")
        exe = os.path.abspath(sys.executable)
        old = exe + ".old"
        if os.path.exists(old):
            os.remove(old)
        os.replace(exe, old)            # o Windows deixa renomear o .exe em uso
        shutil.move(new, exe)
        return [exe]

    if info.kind == "deb":
        deb = dl()
        step(2, "Instalando (vai pedir sua senha)")
        progress(-1, "Aguardando a senha…")
        if not shutil.which("pkexec"):
            raise RuntimeError(f"Instale manualmente:\nsudo apt install {deb}")
        os.chmod(tmp, 0o755)
        os.chmod(deb, 0o644)
        p = subprocess.Popen(["pkexec", "apt-get", "install", "-y", "--allow-downgrades",
                              "-o", "APT::Status-Fd=1", deb],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = []
        for line in p.stdout:
            tail = (tail + [line.strip()])[-15:]
            m = re.match(r"(pmstatus|dlstatus):[^:]*:([\d.]+):(.*)", line)
            if m:
                progress(float(m.group(2)), m.group(3).strip())
        if p.wait() != 0:
            if p.returncode in (126, 127):
                raise Cancelled()
            raise RuntimeError("\n".join(tail) or "apt-get falhou")
        return ["/opt/portinho/portinho"]

    if info.kind == "linux-dir":
        tgz = dl()
        step(2, "Instalando")
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
        parent = os.path.dirname(app_dir)
        stage = tempfile.mkdtemp(prefix=".portinho_new_", dir=parent)
        with tarfile.open(tgz) as tf:
            members = tf.getmembers()
            for i, m in enumerate(members):
                if cancelled():
                    raise Cancelled()
                tf.extract(m, stage, filter="tar") if hasattr(tarfile, "data_filter") else tf.extract(m, stage)
                if i % 25 == 0:
                    progress(i * 100 / len(members), "Extraindo arquivos")
        new_dir = os.path.join(stage, "portinho")
        if not os.path.isfile(os.path.join(new_dir, "portinho")):
            raise RuntimeError("pacote inválido")
        old = app_dir + ".old"
        shutil.rmtree(old, ignore_errors=True)
        os.replace(app_dir, old)
        os.replace(new_dir, app_dir)
        shutil.rmtree(stage, ignore_errors=True)
        return [os.path.join(app_dir, "portinho")]

    raise RuntimeError(f"tipo de instalação desconhecido: {info.kind}")


def clean_env():
    """Ambiente para abrir outro programa empacotado sem herdar o nosso (pasta temporária,
    LD_LIBRARY_PATH...). Sem isso, o Portinho reaberto usaria a pasta do processo antigo."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    elif FROZEN and os.name != "nt":
        env.pop("LD_LIBRARY_PATH", None)
    return env


def relaunch(cmd):
    kw = {"start_new_session": True} if os.name != "nt" else \
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    subprocess.Popen(cmd, close_fds=True, env=clean_env(), **kw)


def cleanup_old():
    """Apaga sobras de uma atualização anterior (.old)."""
    if not FROZEN:
        return
    exe = os.path.abspath(sys.executable)
    for p in (exe + ".old", os.path.dirname(exe) + ".old"):
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
