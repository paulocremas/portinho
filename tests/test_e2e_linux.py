"""Ponta a ponta com o pacote real: instalar (tela) -> detectar atualização -> atualizar -> abrir -> remover.

Uso: QT_QPA_PLATFORM=offscreen python tests/test_e2e_linux.py dist/portinho_X_linux_x86_64.tar.gz [saida]
A pasta pessoal é redirecionada para uma pasta temporária (não mexe na sua).
"""
import http.server
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

TGZ = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp())
os.makedirs(OUT, exist_ok=True)
T = tempfile.mkdtemp(prefix="portinho_e2e_")
HOME = os.path.join(T, "home")
os.makedirs(HOME)
os.environ["HOME"] = HOME
os.environ.pop("XDG_DATA_HOME", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
fails = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FALHA") + f" {name}" + (f"  ({detail})" if detail else ""), flush=True)
    if not cond:
        fails.append(name)


# "GitHub" falso servindo o próprio .tar.gz como versão nova
STATE = {"tag": "v9.9.9"}
DATA = open(TGZ, "rb").read()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/latest":
            body = json.dumps({"tag_name": STATE["tag"], "body": "teste", "assets": [
                {"name": "portinho_9.9.9_linux_x86_64.tar.gz", "size": len(DATA),
                 "browser_download_url": f"http://127.0.0.1:{port}/a.tgz"}]}).encode()
        else:
            body = DATA
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
srv.handle_error = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_address[1]}/latest"
os.environ["PORTINHO_UPDATE_API"] = API

print("\n[extrair o pacote portátil]")
ext = os.path.join(T, "baixados")
with tarfile.open(TGZ) as tf:
    tf.extractall(ext, filter="tar")
src_exe = os.path.join(ext, "portinho", "portinho")
check("tem o app e o instalar.sh", os.access(src_exe, os.X_OK)
      and os.access(os.path.join(ext, "portinho", "instalar.sh"), os.X_OK))


def run(cmd, timeout=60, **env):
    e = dict(os.environ, **env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)


r = run([src_exe, "--check-update"])
check("pasta extraída: detecta 'linux-dir' e acha a versão nova", "linux-dir" in r.stdout and "9.9.9" in r.stdout,
      r.stdout.strip().replace("\n", " | "))

print("\n[instalador gráfico]")
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
from portinho import installer_ui, theme  # noqa: E402
theme.apply(app)
real_exe = sys.executable
sys.executable = src_exe                     # o instalador copia a pasta deste executável
w = installer_ui.InstallWindow()
w.show()
w.grab().save(os.path.join(OUT, "i0_instalar.png"))


def pump(sec, until):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.01)
        if until():
            return True
    return False


w.btn_go.click()
pump(10, lambda: w.bar.value() > 30)
w.grab().save(os.path.join(OUT, "i1_copiando.png"))
check("barra de progresso da cópia", w.bar.value() > 0, f"{w.bar.value()}%  {w.detail.text()}")
check("instalação terminou", pump(120, lambda: w.btn_go.text() == "Abrir o Portinho"), w.title.text())
w.grab().save(os.path.join(OUT, "i2_pronto.png"))
dest = installer_ui.DEST
inst_exe = os.path.join(dest, "portinho")
check("app copiado para ~/.local/share/portinho", dest.startswith(HOME) and os.access(inst_exe, os.X_OK), dest)
desk = open(installer_ui.DESKTOP).read()
check("atalho no menu criado", f'Exec="{inst_exe}" %F' in desk and "Icon=portinho" in desk)
check("comando ~/.local/bin/portinho", os.path.realpath(installer_ui.BIN) == inst_exe)
check("ícone instalado", os.path.exists(installer_ui.ICON))
sys.executable = real_exe

print("\n[app instalado]")
r = run([inst_exe, "--check-update"])
check("instalado: detecta 'linux-dir' e acha a versão nova", "linux-dir" in r.stdout and "9.9.9" in r.stdout,
      r.stdout.strip().replace("\n", " | "))
r = run([inst_exe, "--check-update"], PORTINHO_UPDATE_API="http://127.0.0.1:1/latest")
check("sem internet: 'nenhuma' e internet: False", "nenhuma" in r.stdout and "internet: False" in r.stdout,
      r.stdout.strip().replace("\n", " | "))

print("\n[atualizar a cópia instalada com o pacote baixado]")
from portinho import updater  # noqa: E402
updater.API_URL = API
updater.install_kind = lambda: "linux-dir"
sys.executable = inst_exe
marker = os.path.join(dest, "_internal", "MARCA_VERSAO_VELHA")
open(marker, "w").write("x")
info = updater.check()
check("acha a versão 9.9.9", info is not None and info.version == "9.9.9")
prog = []
cmd = updater.perform(info, lambda *a: None, lambda p, t: prog.append(p))
check("pasta trocada pela nova (marca da velha sumiu)", not os.path.exists(marker))
check("comando para reabrir aponta para o app instalado", cmd == [inst_exe], cmd)
updater.FROZEN = True
updater.cleanup_old()
check("sobra .old apagada", not os.path.exists(dest + ".old"))
sys.executable = real_exe

print("\n[abrir a versão atualizada]")
p = subprocess.Popen([inst_exe], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                     env=dict(os.environ, QT_QPA_PLATFORM="offscreen", PORTINHO_UPDATE_API="http://127.0.0.1:1/latest"))
time.sleep(6)
alive = p.poll() is None
p.terminate()
log = p.communicate(timeout=10)[0]
check("abre e fica aberto (sem internet -> segue normal)", alive, "" if alive else log[-400:])
STATE["tag"] = "v1.0.0"
p = subprocess.Popen([inst_exe], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                     env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
time.sleep(6)
alive = p.poll() is None
p.terminate()
log = p.communicate(timeout=10)[0]
check("abre e fica aberto (internet, sem atualização -> segue normal)", alive, "" if alive else log[-400:])
check("sem erros no log", "Traceback" not in log, log[-300:] if "Traceback" in log else "")

print("\n[desinstalar]")
sys.executable = inst_exe
u = installer_ui.InstallWindow(uninstall=True)
u.show()
u.btn_go.click()
check("remoção terminou", pump(30, lambda: u.btn_go.text() == "Fechar"))
check("arquivos e atalhos removidos", not os.path.exists(dest) and not os.path.exists(installer_ui.DESKTOP)
      and not os.path.lexists(installer_ui.BIN))
sys.executable = real_exe

print(f"\n{len(fails)} falha(s)", fails if fails else "", flush=True)
srv.shutdown()
os._exit(1 if fails else 0)
