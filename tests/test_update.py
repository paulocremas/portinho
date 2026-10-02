"""Testes do atualizador com um "GitHub" falso local (roda com QT_QPA_PLATFORM=offscreen)."""
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
OUT = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FALHA") + f" {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- servidor falso
STATE = {"tag": "v9.9.9", "assets": {}, "status": 200, "slow": 0}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/latest":
            if STATE["status"] != 200:
                self.send_response(STATE["status"]); self.end_headers(); return
            body = json.dumps({"tag_name": STATE["tag"], "body": "**Novidades**\n\n- tela cheia\n- janela flutuante",
                               "assets": [{"name": n, "size": len(d), "browser_download_url": f"http://127.0.0.1:{port}/a/{n}"}
                                          for n, d in STATE["assets"].items()]}).encode()
        elif self.path.startswith("/a/"):
            body = STATE["assets"][self.path[3:]]
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        for i in range(0, len(body), 65536):
            self.wfile.write(body[i:i + 65536])
            if STATE["slow"]:
                time.sleep(STATE["slow"])


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.handle_error = lambda *a: None   # cliente que cancela no meio fecha a conexão
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
os.environ["PORTINHO_UPDATE_API"] = f"http://127.0.0.1:{PORT}/latest"

from portinho import updater  # noqa: E402  (lê a URL na importação)


def make_tgz(marker):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data, mode in (("portinho/portinho", f"#!/bin/sh\necho {marker}\n".encode(), 0o755),
                                 ("portinho/_internal/lib.txt", marker.encode(), 0o644)):
            ti = tarfile.TarInfo(name); ti.size = len(data); ti.mode = mode
            tf.addfile(ti, io.BytesIO(data))
        ti = tarfile.TarInfo("portinho/_internal/link"); ti.type = tarfile.SYMTYPE; ti.linkname = "lib.txt"
        tf.addfile(ti)
    return buf.getvalue()


print("\n[verificação]")
STATE["assets"] = {"portinho_9.9.9_linux_x86_64.tar.gz": make_tgz("NOVA") * 1}
updater.install_kind = lambda: "linux-dir"
t0 = time.time()
info = updater.check()
check("acha versão nova", info is not None and info.version == "9.9.9", info and info.asset_name)
check("escolhe o pacote certo p/ pasta Linux", info and info.asset_name.endswith("_linux_x86_64.tar.gz"))
STATE["tag"] = "v1.0.0"
check("mesma versão: segue normal", updater.check() is None)
STATE["tag"] = "v0.9"
check("versão mais velha: segue normal", updater.check() is None)
STATE["tag"], STATE["status"] = "v9.9.9", 404
check("sem releases (404): segue normal", updater.check() is None)
STATE["status"] = 200
old_api = updater.API_URL
updater.API_URL = "http://127.0.0.1:1/latest"          # porta fechada = sem internet
t0 = time.time()
check("sem internet: segue normal e rápido", updater.check() is None and time.time() - t0 < 3, f"{time.time()-t0:.2f}s")
updater.API_URL = "http://10.255.255.1/latest"          # rota que não responde
t0 = time.time()
r = updater.check()
check("rede que não responde: desiste em ~2s", r is None and time.time() - t0 < 5, f"{time.time()-t0:.2f}s")
updater.API_URL = old_api
check("comparação de versões", updater.parse_version("v1.10.0") > updater.parse_version("1.9.9")
      and updater.parse_version("1.0.1") > updater.parse_version("v1.0.0"))
updater.install_kind = lambda: "win-installer"
check("Windows instalado: sem Setup no release = não oferece", updater.check() is None)
STATE["assets"]["Portinho-Setup-9.9.9.exe"] = b"MZ" * 10
STATE["assets"]["Portinho.exe"] = b"MZ-portable"
STATE["assets"]["portinho_9.9.9_amd64.deb"] = b"!<arch>"
for kind, suf in (("win-installer", "Setup-9.9.9.exe"), ("win-portable", "Portinho.exe"), ("deb", "_amd64.deb")):
    updater.install_kind = lambda k=kind: k
    i = updater.check()
    check(f"{kind}: escolhe {suf}", i is not None and i.asset_name.endswith(suf), i and i.asset_name)

print("\n[instalar: pasta Linux portátil]")
base = tempfile.mkdtemp()
app_dir = os.path.join(base, "portinho")
os.makedirs(os.path.join(app_dir, "_internal"))
open(os.path.join(app_dir, "portinho"), "w").write("#!/bin/sh\necho VELHA\n")
os.chmod(os.path.join(app_dir, "portinho"), 0o755)
real_exe = sys.executable
sys.executable = os.path.join(app_dir, "portinho")
updater.install_kind = lambda: "linux-dir"
info = updater.check()
steps, prog = [], []
cmd = updater.perform(info, lambda n, t: steps.append(n), lambda p, t: prog.append(p))
out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
check("trocou a pasta pela nova", out == "NOVA", out)
check("manteve permissão de executar e links", os.access(cmd[0], os.X_OK)
      and os.path.islink(os.path.join(app_dir, "_internal", "link")))
check("passos 1 e 2 reportados", steps[:2] == [1, 2], steps)
check("progresso chegou ao fim do download", any(p >= 99.9 for p in prog))
updater.FROZEN = True
updater.cleanup_old()
check("na próxima abertura apaga a pasta .old", not os.path.exists(app_dir + ".old"))

print("\n[instalar: .exe portátil (troca de arquivo)]")
d = tempfile.mkdtemp()
sys.executable = os.path.join(d, "Portinho.exe")
open(sys.executable, "wb").write(b"VELHO")
updater.install_kind = lambda: "win-portable"
info = updater.check()
cmd = updater.perform(info, lambda *a: None, lambda *a: None)
check("exe trocado pelo novo", open(sys.executable, "rb").read() == b"MZ-portable")
check("exe velho guardado como .old", open(sys.executable + ".old", "rb").read() == b"VELHO")
updater.cleanup_old()
check(".old apagado depois", not os.path.exists(sys.executable + ".old"))
sys.executable = real_exe
updater.FROZEN = False

print("\n[cancelar durante o download]")
STATE["assets"]["portinho_9.9.9_linux_x86_64.tar.gz"] = make_tgz("NOVA") + b"\0" * 3_000_000
STATE["slow"] = 0.02
updater.install_kind = lambda: "linux-dir"
info = updater.check()
flag = {"c": False}
threading.Timer(0.3, lambda: flag.update(c=True)).start()
try:
    updater.perform(info, lambda *a: None, lambda *a: None, cancelled=lambda: flag["c"])
    check("cancelar interrompe", False)
except updater.Cancelled:
    check("cancelar interrompe", True)
STATE["slow"] = 0

print("\n[git (rodando do código-fonte)]")
g = tempfile.mkdtemp()
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
sh = lambda *c, cwd=g: subprocess.run(c, cwd=cwd, env=env, capture_output=True, check=True)
sh("git", "init", "-q", "--bare", "-b", "main", "remote.git")
sh("git", "clone", "-q", "remote.git", "a"); sh("git", "clone", "-q", "remote.git", "b")
A, B = os.path.join(g, "a"), os.path.join(g, "b")
open(os.path.join(A, "requirements.txt"), "w").write("")
sh("git", "add", ".", cwd=A); sh("git", "commit", "-qm", "v1", cwd=A); sh("git", "push", "-q", "origin", "main", cwd=A)
sh("git", "pull", "-q", cwd=B)
updater.SRC_ROOT = B
check("git em dia: segue normal", updater._check_git(5) is None)
open(os.path.join(A, "novo.txt"), "w").write("x")
sh("git", "add", ".", cwd=A); sh("git", "commit", "-qm", "Adiciona tela cheia", cwd=A); sh("git", "push", "-q", "origin", "main", cwd=A)
i = updater._check_git(5)
check("git com commit novo: oferece atualizar", i is not None and "Adiciona tela cheia" in i.notes, i and i.notes)
cmd = updater.perform(i, lambda *a: None, lambda *a: None)
check("git pull aplicou", os.path.exists(os.path.join(B, "novo.txt")))
check("reabre com run.py", cmd[-1].endswith("run.py"))

# ---------------------------------------------------------------- telas
print("\n[tela de abertura]")
from PySide6.QtWidgets import QApplication  # noqa: E402
from portinho import theme  # noqa: E402
from portinho.splash import Splash  # noqa: E402

app = QApplication.instance() or QApplication([])
theme.apply(app)
icon = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.png")


def pump(sec, until=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)
        if until and until():
            return True
    return bool(until and until())


def run_splash(kind, setup=None):
    opened = []
    updater.install_kind = lambda: kind
    sp = Splash(lambda: opened.append(True), icon)
    if setup:
        setup(sp)
    sp.start()
    return sp, opened


# 1) sem internet
updater.API_URL = "http://127.0.0.1:1/latest"
t0 = time.time()
sp, opened = run_splash("linux-dir")
check("sem internet: abre o app direto", pump(5, lambda: opened), f"{time.time()-t0:.2f}s")
updater.API_URL = old_api

# 2) já atualizado
STATE["tag"] = "v1.0.0"
sp, opened = run_splash("linux-dir")
sp.grab().save(os.path.join(OUT, "u0_procurando.png"))
check("internet e sem atualização: abre o app", pump(5, lambda: opened))

# 3) atualização -> "Agora não"
STATE["tag"] = "v9.9.9"
sp, opened = run_splash("linux-dir")
check("versão nova: pergunta ao usuário", pump(5, lambda: sp.btn_yes.isVisible()))
check("mostra a versão e as novidades", "9.9.9" in sp.title.text() and sp.notes.isVisible())
sp.grab().save(os.path.join(OUT, "u1_pergunta.png"))
sp.btn_no.click()
check("'Agora não' abre o app normal", pump(1, lambda: opened))

# 4) atualização -> "Atualizar" (pasta Linux), com tela de progresso
base = tempfile.mkdtemp()
app_dir = os.path.join(base, "portinho")
os.makedirs(app_dir)
open(os.path.join(app_dir, "portinho"), "w").write("velha")
sys.executable = os.path.join(app_dir, "portinho")
STATE["slow"] = 0.004
relaunched, quit_called = [], []
updater.relaunch = lambda c: relaunched.append(c)
app.quit = lambda: quit_called.append(True)
sp, opened = run_splash("linux-dir")
pump(5, lambda: sp.btn_yes.isVisible())
sp.btn_yes.click()
check("mostra os passos", pump(3, lambda: sp.steps[0][0].isVisible()))
pump(3, lambda: sp.bar.maximum() == 100 and 5 < sp.bar.value() < 95)
sp.grab().save(os.path.join(OUT, "u2_baixando.png"))
check("barra de progresso andando", sp.bar.maximum() == 100 and sp.bar.value() > 0, f"{sp.bar.value()}%  {sp.detail.text()}")
check("terminou e reiniciou", pump(30, lambda: relaunched), relaunched)
sp.grab().save(os.path.join(OUT, "u3_pronto.png"))
check("passos marcados como feitos", sp.steps[0][0].text().startswith("✓") and sp.steps[1][0].text().startswith("✓"))
check("fecha o app velho", pump(3, lambda: quit_called))
check("não abriu a versão velha", not opened)
STATE["slow"] = 0

# 5) falha no download -> continua sem atualizar
STATE["assets"]["portinho_9.9.9_linux_x86_64.tar.gz"] = b"isto nao e um tar"
sp, opened = run_splash("linux-dir")
pump(5, lambda: sp.btn_yes.isVisible())
sp.btn_yes.click()
check("falha mostra mensagem", pump(10, lambda: sp.title.text().startswith("Não foi possível")))
sp.grab().save(os.path.join(OUT, "u4_falha.png"))
check("pasta original intacta após falha", open(os.path.join(app_dir, "portinho")).read() == "#!/bin/sh\necho NOVA\n")
sp.btn_no.click()
check("'Continuar sem atualizar' abre o app", pump(1, lambda: opened))
sys.executable = real_exe

print(f"\n{len(fails)} falha(s)", fails if fails else "")
print("capturas em", OUT)
srv.shutdown()
sys.stdout.flush()
os._exit(1 if fails else 0)
