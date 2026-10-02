"""Tela de abertura: verifica atualização e, se o usuário quiser, acompanha a instalação."""
import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser,
    QVBoxLayout, QWidget,
)

from . import __version__, updater

CHECK_LIMIT_MS = 6000     # nunca segura a abertura por mais que isso


class _Signals(QObject):
    checked = Signal(object)          # UpdateInfo | None
    step = Signal(int, str)
    progress = Signal(float, str)
    finished = Signal(object)         # comando para reabrir | None
    failed = Signal(str)
    cancelled = Signal()


class Splash(QWidget):
    """Chama `on_continue()` quando o app deve abrir normalmente."""

    def __init__(self, on_continue, icon_path=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.on_continue = on_continue
        self._done = False
        self._cancel = False
        self.sig = _Signals()
        self.sig.checked.connect(self._on_checked)
        self.sig.step.connect(self._on_step)
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)
        self.sig.failed.connect(self._on_failed)
        self.sig.cancelled.connect(self._on_cancelled)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Portinho")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame()
        box.setObjectName("card")
        box.setStyleSheet("#card { background: #151820; border: 1px solid #2a2f3a; border-radius: 18px; }")
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        if icon_path and os.path.exists(icon_path):
            logo.setPixmap(QPixmap(icon_path).scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        lay.addSpacing(6)

        self.title = QLabel("Procurando atualizações…")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)

        # passos da atualização (escondidos até começar)
        self.steps = []
        for txt in ("Baixando a atualização", "Instalando", "Reiniciando o Portinho"):
            l = QLabel(f"○   {txt}")
            l.setObjectName("muted")
            l.hide()
            lay.addWidget(l)
            self.steps.append([l, txt])

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setStyleSheet("QTextBrowser { background:#0f1117; border:1px solid #2a2f3a; "
                                 "border-radius:9px; padding:6px; color:#c9cfdb; }")
        self.notes.setMaximumHeight(130)
        self.notes.hide()
        lay.addWidget(self.notes)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.detail = QLabel("")
        self.detail.setObjectName("hint")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_no = QPushButton("Agora não")
        self.btn_yes = QPushButton("Atualizar")
        self.btn_yes.setObjectName("primary")
        for b in (self.btn_no, self.btn_yes):
            b.setCursor(Qt.PointingHandCursor)
            b.hide()
            btns.addWidget(b)
        lay.addLayout(btns)
        self.btn_no.clicked.connect(self._skip)
        self.btn_yes.clicked.connect(self._start_update)

        self.setFixedWidth(500)
        self.resize(500, 250)

    # ------------------------------------------------------------ verificação
    def start(self):
        updater.cleanup_old()
        self._center()
        self.show()
        QTimer.singleShot(CHECK_LIMIT_MS, self._check_timeout)
        threading.Thread(target=lambda: self.sig.checked.emit(updater.check()), daemon=True).start()

    def _center(self):
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    def _check_timeout(self):
        if self.btn_yes.isHidden() and not self._done and self.title.text().startswith("Procurando"):
            self._continue()       # internet lenta: abre sem esperar

    def _on_checked(self, info):
        if self._done:
            return
        if info is None:           # sem internet ou já atualizado
            self._continue()
            return
        self.info = info
        self.title.setText(f"Nova versão disponível: {info.version}")
        self.detail.setText("Quer atualizar agora? Leva só um instante.")
        if info.notes.strip():
            self.notes.setMarkdown(info.notes)
            self.notes.show()
        self.bar.hide()
        self.btn_no.show()
        self.btn_yes.show()
        self.btn_yes.setFocus()
        self.adjustSize()
        self._center()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------ atualização
    def _start_update(self):
        self.title.setText(f"Atualizando para a versão {self.info.version}")
        self.notes.hide()
        self.btn_yes.hide()
        self.btn_no.setText("Cancelar")
        self.btn_no.clicked.disconnect()
        self.btn_no.clicked.connect(self._cancel_update)
        for l, _ in self.steps:
            l.show()
        if self.info.kind in ("win-installer",):
            self.steps[1][1] = "Abrindo o instalador"
        self.bar.show()
        self.bar.setRange(0, 0)
        self.detail.setText("")
        self.adjustSize()
        self._center()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            cmd = updater.perform(self.info, self.sig.step.emit, self.sig.progress.emit,
                                  cancelled=lambda: self._cancel)
            self.sig.finished.emit(cmd)
        except updater.Cancelled:
            self.sig.cancelled.emit()
        except Exception as e:
            self.sig.failed.emit(str(e))

    def _mark(self, n):
        for i, (l, txt) in enumerate(self.steps, start=1):
            if i < n:
                l.setText(f"✓   {txt}")
                l.setStyleSheet("color:#4ade80;")
            elif i == n:
                l.setText(f"●   {txt}")
                l.setStyleSheet("color:#e8eaf0; font-weight:600;")
            else:
                l.setText(f"○   {txt}")
                l.setStyleSheet("")

    def _on_step(self, n, text):
        if text:
            self.steps[n - 1][1] = text
        self._mark(n)
        if n >= 2:
            self.btn_no.setEnabled(False)   # instalando: não dá mais para cancelar no meio

    def _on_progress(self, pct, text):
        if pct < 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(pct))
        self.detail.setText(text)

    def _on_finished(self, cmd):
        self._mark(3)
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        if cmd is None:     # o instalador do Windows reabre o app sozinho
            self.detail.setText("O instalador está terminando e vai reabrir o Portinho.")
        else:
            self.detail.setText("Pronto! Abrindo a nova versão…")
            updater.relaunch(cmd)
        QTimer.singleShot(1200, QApplication.instance().quit)

    def _on_failed(self, msg):
        self.title.setText("Não foi possível atualizar")
        self.detail.setText(msg[-600:])
        self.bar.hide()
        self.btn_no.setEnabled(True)
        self.btn_no.setText("Continuar sem atualizar")
        self.btn_no.clicked.disconnect()
        self.btn_no.clicked.connect(self._continue)
        self.adjustSize()

    def _cancel_update(self):
        self._cancel = True
        self.btn_no.setEnabled(False)
        self.detail.setText("Cancelando…")

    def _on_cancelled(self):
        self._continue()

    def _skip(self):
        self._continue()

    def _continue(self):
        if self._done:
            return
        self._done = True
        self.hide()
        self.on_continue()
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.btn_no.isVisible() and self.btn_no.isEnabled():
            self.btn_no.click()
        else:
            super().keyPressEvent(e)
