"""Janela separada do vídeo: modo janela flutuante e modo tela cheia.

O reprodutor não é recriado: só a superfície onde o vídeo é desenhado muda
(QMediaPlayer.setVideoOutput), então vídeo e música seguem tocando sem pausa.
"""
from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import icons


class VideoWindow(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.Window)
        self.main = main
        self.setWindowTitle("Portinho — vídeo")
        self.setObjectName("videoWindow")
        self.setStyleSheet("#videoWindow { background: #000; }")
        self.mode = None            # "popup" | "fullscreen" | None (fechada)
        self._from_popup = False

        self.video = QVideoWidget()
        self.video.setMouseTracking(True)
        self.video.installEventFilter(self)
        self.setMouseTracking(True)

        self.bar = QFrame()
        self.bar.setObjectName("videoBar")
        self.bar.setStyleSheet("#videoBar { background: #12141a; border-top: 1px solid #222733; }")
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(12, 8, 12, 8)
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("play")
        self.btn_play.setToolTip("Tocar / pausar (Espaço)")
        self.btn_play.clicked.connect(main.toggle_play)
        self.time = QLabel("0:00.000")
        self.time.setObjectName("time")
        self.btn_full = QPushButton()
        self.btn_full.setObjectName("icon")
        self.btn_full.setIconSize(QSize(18, 18))
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self.btn_back = QPushButton("  Voltar para a janela principal")
        self.btn_back.setIcon(icons.make("dock"))
        self.btn_back.setIconSize(QSize(18, 18))
        self.btn_back.clicked.connect(self.close)
        for w in (self.btn_play, self.btn_full, self.btn_back):
            w.setFocusPolicy(Qt.NoFocus)
            w.setCursor(Qt.PointingHandCursor)
        bl.addWidget(self.btn_play)
        bl.addWidget(self.time)
        bl.addStretch(1)
        self.hint = QLabel("")
        self.hint.setObjectName("hint")
        bl.addWidget(self.hint)
        bl.addSpacing(10)
        bl.addWidget(self.btn_full)
        bl.addWidget(self.btn_back)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.video, 1)
        lay.addWidget(self.bar)

        # em tela cheia a barra some quando o mouse fica parado
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(2500)
        self._hide_timer.timeout.connect(self._auto_hide)
        self._sized = False

    # ------------------------------------------------------------ modos
    def open_popup(self):
        self.mode = "popup"
        self._from_popup = False
        self._update_bar()
        if self.isFullScreen():
            self.showNormal()
        if not self._sized:
            self._sized = True
            self.resize(860, 540)
        self.show()
        self.raise_()
        self.activateWindow()

    def open_fullscreen(self):
        self._from_popup = self.mode == "popup" and self.isVisible()
        self.mode = "fullscreen"
        self._update_bar()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._poke()

    def exit_fullscreen(self):
        if self.mode != "fullscreen":
            return
        if self._from_popup:
            self.open_popup()
        else:
            self.close()

    def toggle_fullscreen(self):
        if self.mode == "fullscreen":
            self.exit_fullscreen()
        else:
            self.open_fullscreen()

    def _update_bar(self):
        full = self.mode == "fullscreen"
        self.btn_full.setIcon(icons.make("exit_fullscreen" if full else "fullscreen"))
        self.btn_full.setToolTip("Sair da tela cheia (Esc)" if full else "Tela cheia (F)")
        self.hint.setText("Esc = sair  ·  Espaço = tocar  ·  ←/→ = ajustar música" if full else "")
        self.bar.show()

    # ------------------------------------------------------------ barra automática
    def _poke(self):
        self.bar.show()
        self.unsetCursor()
        if self.mode == "fullscreen":
            self._hide_timer.start()

    def _auto_hide(self):
        if self.mode == "fullscreen" and not self.bar.underMouse():
            self.bar.hide()
            self.setCursor(Qt.BlankCursor)

    def eventFilter(self, obj, e):
        if obj is self.video:
            if e.type() == QEvent.MouseMove:
                self._poke()
            elif e.type() == QEvent.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
        return super().eventFilter(obj, e)

    def mouseMoveEvent(self, e):
        self._poke()
        super().mouseMoveEvent(e)

    # ------------------------------------------------------------ teclado / fechar
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.mode == "fullscreen":
            self.exit_fullscreen()
        elif e.key() in (Qt.Key_F, Qt.Key_F11):
            self.toggle_fullscreen()
        else:
            self.main.keyPressEvent(e)   # Espaço, setas… funcionam igual à janela principal

    def closeEvent(self, e):
        self._hide_timer.stop()
        self.mode = None
        self.unsetCursor()
        if self.main is not None:
            self.main.dock_video()
        super().closeEvent(e)
