"""Instalador gráfico para Linux (pacote portátil): `portinho --install` / `--uninstall`.

Copia o app para ~/.local/share/portinho, cria o atalho no menu e o comando
~/.local/bin/portinho. Não precisa de senha. As atualizações depois trocam essa pasta.
"""
import os
import shutil
import subprocess
import sys
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from . import __version__, theme

HOME = os.path.expanduser("~")
DATA = os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share")
DEST = os.path.join(DATA, "portinho")
BIN = os.path.join(HOME, ".local", "bin", "portinho")
DESKTOP = os.path.join(DATA, "applications", "portinho.desktop")
ICON = os.path.join(DATA, "icons", "hicolor", "512x512", "apps", "portinho.png")

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Portinho
GenericName=Sincronizar música com vídeo
Comment=Troque a música de um vídeo do YouTube alinhando pelo espectrograma
Exec="{exe}" %F
Icon=portinho
Terminal=false
Categories=AudioVideo;Audio;Video;
MimeType=audio/x-wav;audio/wav;audio/mpeg;audio/flac;audio/ogg;audio/mp4;video/mp4;video/x-matroska;video/webm;
StartupWMClass=portinho
"""


class _Sig(QObject):
    step = Signal(int)
    progress = Signal(int, str)
    done = Signal()
    failed = Signal(str)


class InstallWindow(QWidget):
    def __init__(self, uninstall=False):
        super().__init__()
        self.uninstall = uninstall
        self.src = os.path.dirname(os.path.abspath(sys.executable))
        self.setWindowTitle("Remover o Portinho" if uninstall else "Instalar o Portinho")
        self.setFixedWidth(520)
        self.sig = _Sig()
        self.sig.step.connect(self._mark)
        self.sig.progress.connect(self._prog)
        self.sig.done.connect(self._done)
        self.sig.failed.connect(self._failed)

        box = QFrame()
        box.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(26, 24, 26, 20)
        lay.setSpacing(10)
        head = QHBoxLayout()
        logo = QLabel()
        cands = [os.path.join(b, "assets", "icon.png") for b in
                 (getattr(sys, "_MEIPASS", ""), os.path.join(self.src, "_internal"), self.src) if b]
        icon = next((c for c in cands if os.path.exists(c)), cands[-1])
        if os.path.exists(icon):
            logo.setPixmap(QPixmap(icon).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.setWindowIcon(QIcon(icon))
        self.icon_src = icon
        head.addWidget(logo)
        head.addSpacing(8)
        tl = QVBoxLayout()
        t = QLabel("Portinho")
        t.setObjectName("title")
        v = QLabel(f"versão {__version__}")
        v.setObjectName("muted")
        tl.addWidget(t)
        tl.addWidget(v)
        head.addLayout(tl)
        head.addStretch(1)
        lay.addLayout(head)

        self.title = QLabel("Remover o Portinho deste computador?" if uninstall else
                            "Instalar o Portinho no seu usuário (não pede senha)")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        where = QLabel(f"Pasta: {DEST}")
        where.setObjectName("hint")
        where.setWordWrap(True)
        lay.addWidget(where)

        names = (["Removendo arquivos", "Removendo atalho do menu"] if uninstall else
                 ["Copiando arquivos", "Criando atalho no menu", "Pronto"])
        self.steps = []
        for n in names:
            l = QLabel(f"○   {n}")
            l.setObjectName("muted")
            lay.addWidget(l)
            self.steps.append((l, n))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.detail = QLabel("")
        self.detail.setObjectName("hint")
        lay.addWidget(self.detail)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.close)
        self.btn_go = QPushButton("Remover" if uninstall else "Instalar")
        self.btn_go.setObjectName("primary")
        self.btn_go.clicked.connect(self._start)
        for b in (self.btn_cancel, self.btn_go):
            b.setCursor(Qt.PointingHandCursor)
            btns.addWidget(b)
        lay.addLayout(btns)

    def _mark(self, n):
        for i, (l, txt) in enumerate(self.steps):
            if i < n:
                l.setText(f"✓   {txt}")
                l.setStyleSheet("color:#4ade80;")
            elif i == n:
                l.setText(f"●   {txt}")
                l.setStyleSheet("color:#e8eaf0; font-weight:600;")

    def _prog(self, pct, text):
        self.bar.setValue(pct)
        self.detail.setText(text)

    def _start(self):
        self.btn_go.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            if self.uninstall:
                self._do_uninstall()
            else:
                self._do_install()
            self.sig.done.emit()
        except Exception as e:
            self.sig.failed.emit(str(e))

    def _do_install(self):
        self.sig.step.emit(0)
        files = []
        for root, dirs, fs in os.walk(self.src):
            for f in fs:
                files.append(os.path.join(root, f))
        total = sum(os.path.getsize(f) for f in files if not os.path.islink(f)) or 1
        stage = DEST + ".new"
        shutil.rmtree(stage, ignore_errors=True)
        done = 0
        for root, dirs, fs in os.walk(self.src):
            rel = os.path.relpath(root, self.src)
            os.makedirs(os.path.join(stage, rel), exist_ok=True)
            for d in dirs:      # links para pastas
                sp = os.path.join(root, d)
                if os.path.islink(sp):
                    os.symlink(os.readlink(sp), os.path.join(stage, rel, d))
            for f in fs:
                sp, dp = os.path.join(root, f), os.path.join(stage, rel, f)
                if os.path.islink(sp):
                    os.symlink(os.readlink(sp), dp)
                    continue
                shutil.copy2(sp, dp)
                done += os.path.getsize(sp)
                self.sig.progress.emit(int(done * 90 / total), f"{done / 1e6:.0f} de {total / 1e6:.0f} MB")
        old = DEST + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(DEST):
            os.replace(DEST, old)
        os.replace(stage, DEST)
        shutil.rmtree(old, ignore_errors=True)

        self.sig.step.emit(1)
        exe = os.path.join(DEST, "portinho")
        for p in (BIN, DESKTOP, ICON):
            os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.lexists(BIN):
            os.remove(BIN)
        os.symlink(exe, BIN)
        with open(DESKTOP, "w") as f:
            f.write(DESKTOP_ENTRY.format(exe=exe))
        os.chmod(DESKTOP, 0o755)
        if os.path.exists(self.icon_src):
            shutil.copy2(self.icon_src, ICON)
        for cmd in (["update-desktop-database", "-q", os.path.dirname(DESKTOP)],
                    ["gtk-update-icon-cache", "-q", "-t", os.path.join(DATA, "icons", "hicolor")]):
            try:
                subprocess.run(cmd, capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.sig.progress.emit(100, "")

    def _do_uninstall(self):
        self.sig.step.emit(0)
        self.sig.progress.emit(30, "")
        shutil.rmtree(DEST, ignore_errors=True)
        self.sig.step.emit(1)
        for p in (BIN, DESKTOP, ICON):
            if os.path.lexists(p):
                os.remove(p)
        self.sig.progress.emit(100, "")

    def _done(self):
        self._mark(len(self.steps))
        self.btn_cancel.hide()
        self.btn_go.setEnabled(True)
        self.btn_go.clicked.disconnect()
        if self.uninstall:
            self.title.setText("O Portinho foi removido.")
            self.btn_go.setText("Fechar")
            self.btn_go.clicked.connect(self.close)
        else:
            self.title.setText("Instalado! O Portinho já está no menu de aplicativos.")
            self.btn_go.setText("Abrir o Portinho")
            self.btn_go.clicked.connect(self._open)

    def _open(self):
        subprocess.Popen([os.path.join(DEST, "portinho")], start_new_session=True)
        self.close()

    def _failed(self, msg):
        self.title.setText("Não foi possível concluir")
        self.detail.setText(msg)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("Fechar")


def run(uninstall=False):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    theme.apply(app)
    w = InstallWindow(uninstall)
    w.show()
    return app.exec()
