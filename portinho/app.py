"""Portinho — troca a música de um vídeo do YouTube por um arquivo do PC, alinhando pelo espectrograma."""
import os
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__, audio, download, icons, theme
from .log import LOG_PATH, install_excepthook, log, tail
from .player import MusicPlayer
from .timeline import Timeline, fmt_delta, fmt_time
from .videowindow import VideoWindow

APP_NAME = "Portinho"
SYNC_TOLERANCE = 0.040   # s de diferença antes de ressincronizar a música
# Qualidade máxima: maior resolução/fps e o melhor áudio disponíveis. AV1 fica de fora porque o
# reprodutor embutido não decodifica (tela preta); o YouTube oferece VP9 nas mesmas resoluções.
VIDEO_FORMAT = "bv*[vcodec!^=av01]+ba/b[vcodec!^=av01]/bv*+ba/b"
AUDIO_FORMAT = "ba/b"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".aif", ".aiff", ".wma", ".opus", ".alac"}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".ts"}


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, APP_NAME, "videos")
    os.makedirs(d, exist_ok=True)
    return d


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class Bridge(QObject):
    """Leva resultados das threads de trabalho para a thread da interface."""
    status = Signal(str)
    progress = Signal(float)              # 0..100, -1 = indeterminado, >=100 esconde
    videoReady = Signal(str, str)         # caminho, título
    trackReady = Signal(str, object)      # "video"/"music", dict
    error = Signal(str)
    exported = Signal(str)
    wavReady = Signal(str, str)           # arquivo de áudio baixado, título


def fmt_bpm(bpm):
    return f"{bpm:.1f}".removesuffix(".0").replace(".", ",")


def run_bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def card():
    f = QFrame()
    f.setObjectName("card")
    return f


def step_badge(n):
    b = QLabel(str(n))
    b.setObjectName("step")
    b.setAlignment(Qt.AlignCenter)
    return b


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(860, 600)
        scr = QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else None
        if avail is not None and (avail.height() < 900 or avail.width() < 1300):
            self._start_maximized = True           # telas pequenas (ex.: 1366x768)
            self.resize(avail.width(), avail.height())
        else:
            self._start_maximized = False
            self.resize(1240, 860)
        self.setAcceptDrops(True)

        self.bridge = Bridge()
        self.bridge.status.connect(self._on_status)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.videoReady.connect(self.load_video)
        self.bridge.trackReady.connect(self._on_track_ready)
        self.bridge.error.connect(self._on_error)
        self.bridge.exported.connect(self._on_exported)
        self.bridge.wavReady.connect(self._on_wav_ready)

        self.video_path = None
        self.music_path = None
        self.video_flux = None
        self.music_flux = None
        self.analysis = {"video": {}, "music": {}}     # tom e BPM detectados
        self._analysis_ui = {}
        self.busy = set()

        # --- reprodução ---
        self.video_audio = QAudioOutput()
        self.video_audio.setVolume(0.0)        # o vídeo toca SEM o som original
        self.vplayer = QMediaPlayer()
        self.vplayer.setAudioOutput(self.video_audio)
        self.video_widget = QVideoWidget()
        self.vplayer.setVideoOutput(self.video_widget)
        self.vplayer.playbackStateChanged.connect(self._on_playback_state)
        self.vplayer.durationChanged.connect(self._on_video_duration)
        self.vplayer.errorOccurred.connect(lambda _e, msg: msg and self._on_error(f"Não consegui tocar o vídeo.\n\n{msg}"))
        self.mplayer = MusicPlayer()
        self.vwin = None             # janela separada do vídeo (flutuante / tela cheia)
        self.video_out = False

        self.playing = False
        self.loop = False
        self._last_loop = 0.0
        self._clock_t0 = 0.0
        self._clock_pos = 0.0
        self._drift = deque(maxlen=6)
        self._anchor = None
        self._need_resync = False
        self._last_resync = 0.0
        self.undo_stack, self.redo_stack = [], []
        self._last_push = 0.0
        self._auto_done = False      # auto-alinhamento já rodou para este par de arquivos

        self._build_ui()
        self._refresh_enabled()

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ================================================================ UI
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(10)

        # ---- cabeçalho
        head = QHBoxLayout()
        title = QLabel("Portinho")
        title.setObjectName("title")
        sub = QLabel("Troque a música de um vídeo: carregue os dois e arraste até encaixar.")
        sub.setObjectName("subtitle")
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(sub, 1, Qt.AlignBottom)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        head.addWidget(self.status_label)
        head.addWidget(self.progress, 0, Qt.AlignVCenter)
        lay.addLayout(head)

        # ---- passos 1 e 2
        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.video_card = card()
        vc = QVBoxLayout(self.video_card)
        vc.setContentsMargins(16, 14, 16, 14)
        t = QHBoxLayout()
        self.video_step = step_badge(1)
        t.addWidget(self.video_step)
        lt = QLabel("Vídeo do YouTube")
        lt.setObjectName("cardTitle")
        t.addWidget(lt)
        t.addStretch(1)
        btn_local = QPushButton("Abrir do PC…")
        btn_local.setObjectName("ghost")
        btn_local.setCursor(Qt.PointingHandCursor)
        btn_local.clicked.connect(self.open_local_video)
        t.addWidget(btn_local)
        vc.addLayout(t)
        r = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Cole o link do YouTube aqui (Ctrl+V)")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self.download)
        self.btn_dl = QPushButton("Carregar")
        self.btn_dl.setObjectName("primary")
        self.btn_dl.setCursor(Qt.PointingHandCursor)
        self.btn_dl.clicked.connect(self.download)
        self.btn_wav = QPushButton("Baixar áudio .wav")
        self.btn_wav.setCursor(Qt.PointingHandCursor)
        self.btn_wav.setToolTip("Salva o áudio do vídeo em WAV, na qualidade máxima\n"
                                "(melhor faixa do YouTube, taxa original, 32 bits sem perdas)")
        self.btn_wav.clicked.connect(self.save_wav)
        r.addWidget(self.url_edit, 1)
        r.addWidget(self.btn_dl)
        r.addWidget(self.btn_wav)
        vc.addLayout(r)
        self.video_info = QLabel("Sem anúncios · o vídeo toca sem o som original")
        self.video_info.setObjectName("muted")
        vc.addWidget(self.video_info)
        vc.addWidget(self._analysis_row("video"))
        cards.addWidget(self.video_card, 3)

        self.music_card = card()
        mc = QVBoxLayout(self.music_card)
        mc.setContentsMargins(16, 14, 16, 14)
        t = QHBoxLayout()
        self.music_step = step_badge(2)
        t.addWidget(self.music_step)
        lt = QLabel("Música")
        lt.setObjectName("cardTitle")
        t.addWidget(lt)
        t.addStretch(1)
        mc.addLayout(t)
        self.dropzone = QPushButton("♪   Arraste a música aqui ou clique para escolher\nWAV · MP3 · FLAC · OGG · M4A")
        self.dropzone.setObjectName("dropzone")
        self.dropzone.setCursor(Qt.PointingHandCursor)
        self.dropzone.setMinimumHeight(60)
        self.dropzone.clicked.connect(self.open_music)
        mc.addWidget(self.dropzone)
        mc.addWidget(self._analysis_row("music"))
        self.compare_label = QLabel("")
        self.compare_label.setObjectName("muted")
        self.compare_label.hide()
        mc.addWidget(self.compare_label)
        cards.addWidget(self.music_card, 2)
        lay.addLayout(cards)

        # ---- vídeo + linha do tempo
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        self.video_stack = QStackedWidget()
        self.video_stack.setObjectName("videoBox")
        self.video_stack.setMinimumHeight(140)
        ph = QLabel("▶\n\nO vídeo aparece aqui")
        ph.setObjectName("placeholder")
        ph.setAlignment(Qt.AlignCenter)
        ph.setStyleSheet("background:#0a0b0f; border-radius:14px;")
        self.video_stack.addWidget(ph)
        self.video_stack.addWidget(self.video_widget)
        away = QWidget()
        away.setStyleSheet("background:#0a0b0f; border-radius:14px;")
        al = QVBoxLayout(away)
        al.addStretch(1)
        msg = QLabel("O vídeo está em outra janela")
        msg.setObjectName("placeholder")
        msg.setAlignment(Qt.AlignCenter)
        al.addWidget(msg)
        back = QPushButton("  Trazer o vídeo de volta")
        back.setIcon(icons.make("dock"))
        back.setIconSize(QSize(18, 18))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.close_video_window)
        al.addWidget(back, 0, Qt.AlignCenter)
        al.addStretch(1)
        self.video_stack.addWidget(away)
        self.video_widget.installEventFilter(self)
        split.addWidget(self.video_stack)

        bottom = card()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(14, 12, 14, 10)
        bl.setSpacing(10)

        # transporte
        tr = QHBoxLayout()
        tr.setSpacing(8)
        self.btn_play = QPushButton("▶")
        self.btn_play.setObjectName("play")
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.setToolTip("Tocar / pausar (Espaço)")
        self.btn_play.clicked.connect(self.toggle_play)
        tr.addWidget(self.btn_play)
        self.time_label = QLabel("0:00.000")
        self.time_label.setObjectName("time")
        self.time_label.setMinimumWidth(self.time_label.fontMetrics().horizontalAdvance("00:00.000 / 00:00") + 40)
        tr.addWidget(self.time_label)
        self.btn_full = QPushButton()
        self.btn_full.setObjectName("icon")
        self.btn_full.setIcon(icons.make("fullscreen"))
        self.btn_full.setIconSize(QSize(18, 18))
        self.btn_full.setToolTip("Tela cheia (F ou duplo clique no vídeo)")
        self.btn_full.clicked.connect(self.fullscreen_video)
        self.btn_pop = QPushButton()
        self.btn_pop.setObjectName("icon")
        self.btn_pop.setIcon(icons.make("popup"))
        self.btn_pop.setIconSize(QSize(18, 18))
        self.btn_pop.setToolTip("Abrir o vídeo numa janela separada (feche-a para voltar)")
        self.btn_pop.clicked.connect(self.popout_video)
        self.btn_loop = QPushButton()
        self.btn_loop.setObjectName("icon")
        self.btn_loop.setIcon(icons.make("loop"))
        self.btn_loop.setIconSize(QSize(18, 18))
        self.btn_loop.setCheckable(True)
        self.btn_loop.setToolTip("Repetir: ao acabar, volta para o início da música (L)")
        self.btn_loop.toggled.connect(lambda on: setattr(self, "loop", on))
        tr.addWidget(self.btn_loop)
        tr.addWidget(self.btn_full)
        tr.addWidget(self.btn_pop)
        tr.addStretch(1)

        lbl = QLabel("Deslocamento da música")
        lbl.setObjectName("muted")
        tr.addWidget(lbl)
        self.btn_minus = QPushButton("−")
        self.btn_minus.setObjectName("icon")
        self.btn_minus.setToolTip("Adiantar a música 10 ms (←)")
        self.btn_minus.setAutoRepeat(True)
        self.btn_minus.clicked.connect(lambda: self.nudge(-0.01))
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setDecimals(3)
        self.offset_spin.setRange(-36000, 36000)
        self.offset_spin.setSingleStep(0.01)
        self.offset_spin.setSuffix(" s")
        self.offset_spin.setAlignment(Qt.AlignCenter)
        self.offset_spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.offset_spin.setKeyboardTracking(False)
        self.offset_spin.setToolTip("Positivo = a música começa depois do início do vídeo")
        self.offset_spin.valueChanged.connect(self._on_spin)
        self.btn_plus = QPushButton("+")
        self.btn_plus.setObjectName("icon")
        self.btn_plus.setToolTip("Atrasar a música 10 ms (→)")
        self.btn_plus.setAutoRepeat(True)
        self.btn_plus.clicked.connect(lambda: self.nudge(0.01))
        tr.addWidget(self.btn_minus)
        tr.addWidget(self.offset_spin)
        tr.addWidget(self.btn_plus)
        self.btn_auto = QPushButton("Alinhar automaticamente")
        self.btn_auto.setObjectName("primary")
        self.btn_auto.setCursor(Qt.PointingHandCursor)
        self.btn_auto.setToolTip("Compara os dois espectrogramas e encaixa a música sozinho")
        self.btn_auto.clicked.connect(lambda: self.auto_align())
        tr.addWidget(self.btn_auto)
        self.btn_undo = QPushButton("↶")
        self.btn_undo.setObjectName("icon")
        self.btn_undo.setToolTip("Desfazer (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        tr.addWidget(self.btn_undo)
        tr.addStretch(1)

        self.btn_export = QPushButton("Exportar vídeo…")
        self.btn_export.setToolTip("Salva um MP4 com a música alinhada no lugar do som original")
        self.btn_export.clicked.connect(self.export)
        tr.addWidget(self.btn_export)
        bl.addLayout(tr)

        # cabeçalho da linha do tempo
        th = QHBoxLayout()
        self.align_step = step_badge(3)
        th.addWidget(self.align_step)
        lt = QLabel("Arraste os espectrogramas até os desenhos coincidirem")
        lt.setObjectName("cardTitle")
        th.addWidget(lt)
        th.addStretch(1)

        def mini_slider(text, value, tip, fn):
            l = QLabel(text)
            l.setObjectName("muted")
            l.setToolTip(tip)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(value)
            sl.setFixedWidth(80)
            sl.setToolTip(tip)
            sl.valueChanged.connect(fn)
            th.addWidget(l)
            th.addWidget(sl)
            th.addSpacing(6)
            return sl

        self.vvol = mini_slider("Som original", 0, "Volume do áudio original do vídeo (0 = mudo)",
                                lambda v: self.video_audio.setVolume(v / 100))
        self.mvol = mini_slider("Música", 100, "Volume da música",
                                lambda v: setattr(self.mplayer, "volume", v / 100))
        th.addSpacing(10)
        for txt, tip, fn in (("−", "Afastar (roda do mouse)", lambda: self.timeline.zoom(1 / 1.5)),
                             ("+", "Aproximar (roda do mouse)", lambda: self.timeline.zoom(1.5)),
                             ("Ver tudo", "Mostrar os dois inteiros", lambda: self.timeline.fit())):
            b = QPushButton(txt)
            b.setObjectName("icon")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            th.addWidget(b)
        bl.addLayout(th)

        self.timeline = Timeline()
        self.timeline.offsetsChanged.connect(self._on_timeline_offsets)
        self.timeline.dragFinished.connect(self._push_undo)
        self.timeline.seekRequested.connect(self.seek)
        bl.addWidget(self.timeline, 1)

        hint = QLabel("Arrastar = mover  ·  Shift = ajuste fino  ·  Ctrl = sem ímã  ·  clique = ir para o ponto  ·  "
                      "roda = zoom  ·  Shift+roda / botão direito = rolar  ·  Espaço = tocar  ·  ←/→ = 10 ms  ·  Ctrl+Z = desfazer  ·  "
                      "L = repetir  ·  F = tela cheia")
        hint.setObjectName("hint")
        hint.setMinimumWidth(10)
        bl.addWidget(hint)

        split.addWidget(bottom)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([380, 380])
        self.split = split
        self._user_split = False
        split.splitterMoved.connect(lambda *_: setattr(self, "_user_split", True))
        lay.addWidget(split, 1)
        self.setCentralWidget(root)

        # botões sem foco: Espaço e setas ficam para tocar/ajustar
        for w in self.findChildren(QPushButton) + self.findChildren(QSlider):
            w.setFocusPolicy(Qt.NoFocus)

        # cada combinação uma vez só (duplicada o Qt considera ambígua e não dispara)
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self.redo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self.redo)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # a linha do tempo é o coração do app: fica com a maior parte,
        # até o usuário mover o divisor por conta própria
        if hasattr(self, "split") and not self._user_split:
            h = self.split.height()
            self.split.setSizes([int(h * 0.36), int(h * 0.64)])

    def _refresh_enabled(self):
        has_v = bool(self.video_path)
        has_m = self.mplayer.data is not None
        both = self.video_flux is not None and self.music_flux is not None
        self.btn_play.setEnabled(has_v or has_m)
        self.btn_loop.setEnabled(has_v or has_m)
        self.btn_full.setEnabled(has_v)
        self.btn_pop.setEnabled(has_v)
        for w in (self.offset_spin, self.btn_minus, self.btn_plus):
            w.setEnabled(has_m)
        self.btn_auto.setEnabled(both and "align" not in self.busy)
        self.btn_export.setEnabled(has_v and has_m and "export" not in self.busy)
        self.btn_dl.setEnabled("download" not in self.busy)
        self.btn_wav.setEnabled("wav" not in self.busy)
        self.btn_undo.setEnabled(bool(self.undo_stack))
        for badge, done in ((self.video_step, self.timeline.video.loaded),
                            (self.music_step, self.timeline.music.loaded),
                            (self.align_step, self._auto_done or bool(self.undo_stack))):
            if badge.property("done") != done:
                badge.setProperty("done", done)
                repolish(badge)

    # ================================================================ vídeo fora da janela
    def _ensure_vwin(self):
        if self.vwin is None:
            self.vwin = VideoWindow(self)
        return self.vwin

    def _move_video_out(self):
        if not self.video_out:
            self.video_out = True
            self.vplayer.setVideoOutput(self._ensure_vwin().video)
            self.video_stack.setCurrentIndex(2)
            self._refresh_frame()

    def popout_video(self):
        if not self.video_path:
            return
        self._move_video_out()
        self.vwin.open_popup()

    def fullscreen_video(self):
        if not self.video_path:
            return
        self._move_video_out()
        self.vwin.open_fullscreen()

    def toggle_fullscreen(self):
        if self.vwin is not None and self.vwin.mode == "fullscreen":
            self.vwin.exit_fullscreen()
        else:
            self.fullscreen_video()

    def close_video_window(self):
        if self.vwin is not None and self.vwin.isVisible():
            self.vwin.close()          # closeEvent chama dock_video()
        else:
            self.dock_video()

    def dock_video(self):
        """Volta o vídeo para a janela principal (chamado ao fechar a janela separada)."""
        if not self.video_out:
            return
        self.video_out = False
        self.vplayer.setVideoOutput(self.video_widget)
        self.video_stack.setCurrentIndex(1 if self.video_path else 0)
        self._refresh_frame()
        self.activateWindow()

    def _refresh_frame(self):
        # pausado, a nova superfície ficaria preta até o próximo quadro: pede o quadro atual
        if self.video_path and not self.playing:
            self.vplayer.setPosition(self.vplayer.position())

    def eventFilter(self, obj, e):
        if obj is self.video_widget and e.type() == QEvent.MouseButtonDblClick:
            self.fullscreen_video()
            return True
        return super().eventFilter(obj, e)

    # ================================================================ status
    def _on_status(self, msg):
        self.status_label.setText(msg)

    def _on_progress(self, v):
        if v is None or v >= 100:
            self.progress.hide()
            return
        self.progress.show()
        if v < 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(v))

    def _on_error(self, msg):
        self.busy.clear()
        self.bridge.progress.emit(100)
        self.status_label.setText("")
        if self.video_info.text() == "Baixando…":
            self.video_info.setText("Não deu certo — confira o link e tente de novo")
        self._refresh_enabled()
        log.error("aviso ao usuário: %s", msg.replace("\n", " | "))
        box = QMessageBox(QMessageBox.Warning, APP_NAME, msg, QMessageBox.Ok, self)
        box.setInformativeText(f"Registro completo em:\n{LOG_PATH}")
        box.setDetailedText(tail(60))
        box.exec()

    # ================================================================ arrastar arquivos
    def _classify_drop(self, mime):
        if mime.hasUrls():
            for u in mime.urls():
                if u.isLocalFile():
                    ext = os.path.splitext(u.toLocalFile())[1].lower()
                    if ext in AUDIO_EXT:
                        return "music", u.toLocalFile()
                    if ext in VIDEO_EXT:
                        return "video", u.toLocalFile()
                elif u.scheme() in ("http", "https"):
                    return "url", u.toString()
        if mime.hasText() and mime.text().strip().startswith("http"):
            return "url", mime.text().strip()
        return None, None

    def _set_drag_over(self, kind):
        for c, k in ((self.video_card, ("video", "url")), (self.music_card, ("music",))):
            on = kind in k
            if c.property("dragOver") != on:
                c.setProperty("dragOver", on)
                repolish(c)

    def dragEnterEvent(self, e):
        kind, _ = self._classify_drop(e.mimeData())
        if kind:
            e.acceptProposedAction()
            self._set_drag_over(kind)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, _):
        self._set_drag_over(None)

    def dropEvent(self, e):
        self._set_drag_over(None)
        kind, val = self._classify_drop(e.mimeData())
        if kind == "music":
            self.load_music(val)
        elif kind == "video":
            self.load_video(val, os.path.basename(val))
        elif kind == "url":
            self.url_edit.setText(val)
            self.download()
        e.acceptProposedAction()

    # ================================================================ vídeo
    def download(self):
        url = self.url_edit.text().strip()
        if not url or "download" in self.busy:
            return
        if not url.startswith("http"):
            url = "https://" + url
        self.busy.add("download")
        self._refresh_enabled()
        self.video_info.setText("Baixando…")
        self.bridge.status.emit("Baixando o vídeo…")
        self.bridge.progress.emit(0)
        run_bg(self._download_worker, url)

    def _download_worker(self, url):
        try:
            def hook(d):
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    if total:
                        pct = d.get("downloaded_bytes", 0) * 100 / total
                        self.bridge.progress.emit(min(pct, 99))
                        self.bridge.status.emit(f"Baixando o vídeo… {pct:.0f}%")
                elif d.get("status") == "finished":
                    self.bridge.status.emit("Finalizando o download…")
                    self.bridge.progress.emit(-1)

            # mkv aceita qualquer codec sem converter
            info, path = download.fetch(url, VIDEO_FORMAT, "%(id)s.%(ext)s", hook, data_dir(), merge="mkv",
                                        attempt_cb=lambda n: self.bridge.status.emit(f"Tentando de outro jeito ({n})…"))
            self.busy.discard("download")
            self.bridge.videoReady.emit(path, info.get("title") or os.path.basename(path))
        except Exception as e:
            log.exception("download do vídeo falhou")
            self.bridge.error.emit(f"Não foi possível baixar o vídeo.\n\n{e}")

    # ================================================================ áudio .wav
    def save_wav(self):
        """Baixa o melhor áudio do link (ou usa o vídeo aberto) e salva em WAV sem perdas."""
        if "wav" in self.busy:
            return
        url = self.url_edit.text().strip()
        if not url and not self.video_path:
            QMessageBox.information(self, APP_NAME, "Cole um link do YouTube (ou abra um vídeo) primeiro.")
            return
        if url and not url.startswith("http"):
            url = "https://" + url
        self.busy.add("wav")
        self._refresh_enabled()
        self.bridge.status.emit("Baixando o áudio em qualidade máxima…")
        self.bridge.progress.emit(0)
        run_bg(self._wav_worker, url or None)

    def _wav_worker(self, url):
        try:
            if url:
                def hook(d):
                    if d.get("status") == "downloading":
                        total = d.get("total_bytes") or d.get("total_bytes_estimate")
                        if total:
                            pct = d.get("downloaded_bytes", 0) * 100 / total
                            self.bridge.progress.emit(min(pct, 99))
                            self.bridge.status.emit(f"Baixando o áudio… {pct:.0f}%")
                info, src = download.fetch(url, AUDIO_FORMAT, "%(id)s.audio.%(ext)s", hook, data_dir(),
                                           attempt_cb=lambda n: self.bridge.status.emit(f"Tentando de outro jeito ({n})…"))
                title = info.get("title") or "audio"
            else:
                src = self.video_path
                title = os.path.splitext(os.path.basename(src))[0]
            self.bridge.progress.emit(-1)
            self.bridge.wavReady.emit(src, title)
        except Exception as e:
            log.exception("download do áudio falhou")
            self.busy.discard("wav")
            self.bridge.error.emit(f"Não foi possível baixar o áudio.\n\n{e}")

    def _on_wav_ready(self, src, title):
        safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "audio"
        out, _ = QFileDialog.getSaveFileName(self, "Salvar áudio em WAV",
                                             os.path.join(os.path.expanduser("~"), f"{safe}.wav"),
                                             "WAV (*.wav)")
        if not out:
            self.busy.discard("wav")
            self.bridge.progress.emit(100)
            self.bridge.status.emit("")
            self._refresh_enabled()
            return
        if not out.lower().endswith(".wav"):
            out += ".wav"
        self.bridge.status.emit("Gravando o WAV…")
        run_bg(self._wav_convert, src, out)

    def _wav_convert(self, src, out):
        try:
            # sem reamostrar e sem mexer nos canais; float 32 bits guarda exatamente o que o
            # decodificador entrega; rf64 permite arquivos acima de 4 GB
            cmd = [audio.ffmpeg_exe(), "-y", "-v", "error", "-i", src, "-vn", "-map", "0:a:0",
                   "-c:a", "pcm_f32le", "-rf64", "auto", out]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **audio._popen_kwargs())
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="replace"))
            self.busy.discard("wav")
            self.bridge.exported.emit(out)
        except Exception as e:
            self.busy.discard("wav")
            self.bridge.error.emit(f"Falha ao gravar o WAV:\n{e}")

    def open_local_video(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT))
        path, _ = QFileDialog.getOpenFileName(self, "Escolher vídeo", "", f"Vídeos ({exts});;Todos (*)")
        if path:
            self.load_video(path, os.path.basename(path))

    def load_video(self, path, title=""):
        self.stop()
        self.video_path = path
        self.video_flux = None
        self.analysis["video"] = {}
        self._refresh_analysis()
        self._auto_done = False
        self.timeline.video.duration = 0.0
        self.timeline.video.image = None
        self.timeline.suggestion = None
        self.vplayer.setSource(QUrl.fromLocalFile(path))
        self.video_stack.setCurrentIndex(2 if self.video_out else 1)
        self.video_info.setText(f"✓  {title}")
        self.video_info.setToolTip(path)
        self.bridge.status.emit("Lendo o áudio do vídeo…")
        self.bridge.progress.emit(-1)
        self.busy.add("analyze_video")
        self._refresh_enabled()
        run_bg(self._analyze_worker, "video", path)

    def _on_video_duration(self, ms):
        # vídeo sem trilha de áudio: ainda assim mostra o clipe na linha do tempo
        tl = self.timeline
        if ms > 0 and not tl.video.loaded and "analyze_video" not in self.busy:
            tl.video.duration = ms / 1000
            tl.fit()
            self._refresh_enabled()

    # ================================================================ música
    def open_music(self):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXT))
        path, _ = QFileDialog.getOpenFileName(self, "Escolher música", "", f"Áudio ({exts});;Todos (*)")
        if path:
            self.load_music(path)

    def load_music(self, path):
        self.stop()
        self.music_path = path
        self.music_flux = None
        self.analysis["music"] = {}
        self._refresh_analysis()
        self._auto_done = False
        self.timeline.suggestion = None
        self.dropzone.setText(f"♪   {os.path.basename(path)}\nlendo…")
        self.bridge.status.emit("Lendo a música…")
        self.bridge.progress.emit(-1)
        self.busy.add("analyze_music")
        run_bg(self._analyze_worker, "music", path)

    # ================================================================ análise
    def _analyze_worker(self, kind, path):
        try:
            data = audio.decode(path, channels=2)
            mono = data.mean(axis=1)
            rgb, flux = audio.spectrogram(mono)
            result = {"rgb": rgb, "flux": flux, "duration": len(data) / audio.SR, "path": path}
            for name, fn, arg in (("key", audio.detect_key, mono), ("bpm", audio.detect_bpm, flux)):
                try:
                    result[name] = fn(arg)
                except Exception:
                    log.exception("detecção de %s falhou", name)
                    result[name] = None
            if kind == "music":
                # para ouvir: taxa original do arquivo, sem reamostrar
                native = audio.probe_rate(path) or audio.SR
                result["data"] = data if native == audio.SR else audio.decode(path, 2, native)
                result["sr"] = native
            self.bridge.trackReady.emit(kind, result)
        except Exception as e:
            if kind == "video":
                # vídeo pode não ter áudio: segue sem espectrograma
                self.bridge.trackReady.emit("video_noaudio", {"path": path})
            else:
                self.busy.discard("analyze_music")
                self.bridge.error.emit(f"Não consegui ler {os.path.basename(path)}.\n\n{e}")

    def _on_track_ready(self, kind, r):
        tl = self.timeline
        if kind == "video_noaudio":
            self.busy.discard("analyze_video")
            self.bridge.progress.emit(100)
            self.bridge.status.emit("Vídeo sem áudio — sem espectrograma")
            self._on_video_duration(self.vplayer.duration())
            return
        if kind == "video":
            if r["path"] != self.video_path:
                return
            tl.video.set_spectrogram(r["rgb"], audio.FPS, r["duration"])
            self.video_flux = r["flux"]
        else:
            if r["path"] != self.music_path:
                return
            tl.music.set_spectrogram(r["rgb"], audio.FPS, r["duration"])
            self.mplayer.set_data(r["data"], r["sr"])
            self.music_flux = r["flux"]
            self.dropzone.setText(f"♪   {os.path.basename(r['path'])}\n"
                                  f"{fmt_time(r['duration'], ms=False)}  ·  clique para trocar")
            self.dropzone.setProperty("done", True)
            repolish(self.dropzone)
        self.analysis[kind] = {"key": r["key"], "bpm": r["bpm"]}
        self.busy.discard("analyze_" + kind)
        self._refresh_analysis()
        if not self._auto_done:
            # até alinhar: começam juntos
            tl.music.offset = tl.video.offset
            self._sync_spin()
        tl.fit()
        if not any(b.startswith("analyze") or b == "download" for b in self.busy):
            self.bridge.progress.emit(100)
            self.bridge.status.emit("")
        self._refresh_enabled()
        if self.video_flux is not None and self.music_flux is not None and not self._auto_done:
            self.auto_align(silent=True)

    # ================================================================ tom e BPM
    def _analysis_row(self, kind):
        """Linha "Tom: … · 128 BPM  ÷2 ×2" de um cartão (escondida até a análise terminar)."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        lbl = QLabel("")
        lbl.setObjectName("muted")
        row.addWidget(lbl)
        btns = []
        for txt, f, tip in (("÷2", 0.5, "Metade do BPM (o detector contou batidas a mais)"),
                            ("×2", 2.0, "Dobro do BPM (o detector contou só metade das batidas)")):
            b = QPushButton(txt)
            b.setObjectName("ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=kind, f=f: self._scale_bpm(k, f))
            row.addWidget(b)
            btns.append(b)
        row.addStretch(1)
        w.hide()
        self._analysis_ui[kind] = (w, lbl, btns)
        return w

    def _scale_bpm(self, kind, f):
        bpm = self.analysis[kind].get("bpm")
        if bpm:
            self.analysis[kind]["bpm"] = bpm * f
            self._refresh_analysis()

    def _refresh_analysis(self):
        for kind, (w, lbl, btns) in self._analysis_ui.items():
            info = self.analysis[kind]
            parts = []
            if info.get("key"):
                parts.append(f"Tom: {audio.key_name(info['key'])}")
            if info.get("bpm"):
                parts.append(f"{fmt_bpm(info['bpm'])} BPM")
            lbl.setText("  ·  ".join(parts))
            for b in btns:
                b.setVisible(bool(info.get("bpm")))
            w.setVisible(bool(parts))
        self._refresh_compare()

    def _refresh_compare(self):
        v, m = self.analysis["video"], self.analysis["music"]
        parts, tips = [], []
        a, b = v.get("key"), m.get("key")
        if a and b:
            n = audio.semitone_diff(a, b)
            if n == 0:
                parts.append("mesmo tom do vídeo" if a[1] == b[1] else "tom relativo ao do vídeo (mesmas notas)")
            else:
                parts.append(f"tom {abs(n)} {'semitons' if abs(n) > 1 else 'semitom'} "
                             f"{'acima' if n > 0 else 'abaixo'} do vídeo")
            tips.append(f"Tom — vídeo: {audio.key_name(a)}  ·  música: {audio.key_name(b)}")
        a, b = v.get("bpm"), m.get("bpm")
        if a and b:
            ratio = b / a
            while ratio > 2 ** 0.5:         # 70 e 140 BPM são o mesmo pulso: fica com o mais próximo
                ratio /= 2
            while ratio < 2 ** -0.5:
                ratio *= 2
            pct = (ratio - 1) * 100
            if abs(pct) < 1:
                parts.append("mesmo andamento")
            else:
                parts.append(f"andamento {abs(pct):.0f}% mais {'rápido' if pct > 0 else 'lento'}")
            tips.append(f"BPM — vídeo: {fmt_bpm(a)}  ·  música: {fmt_bpm(b)}")
        if not parts:
            self.compare_label.hide()
            return
        txt = "  ·  ".join(parts)
        self.compare_label.setText(txt[0].upper() + txt[1:])
        self.compare_label.setToolTip("\n".join(tips) + "\nEstimativas automáticas: podem errar em músicas com "
                                      "pouca harmonia, sem batida marcada ou que mudam de tom/andamento.")
        self.compare_label.show()

    # ================================================================ alinhamento
    def music_delta(self):
        return self.timeline.music_delta()

    def _offsets(self):
        return (self.timeline.video.offset, self.timeline.music.offset)

    def _set_offsets(self, offs):
        self.timeline.video.offset, self.timeline.music.offset = offs
        self._sync_spin()
        self.timeline.update()
        self._request_resync()

    def _push_undo(self, before=None, coalesce=False):
        now = time.monotonic()
        if coalesce and now - self._last_push < 1.0 and self.undo_stack:
            self._last_push = now
            return
        self._last_push = now if coalesce else 0.0
        self.undo_stack.append(tuple(before) if before is not None else self._offsets())
        self.redo_stack.clear()
        self._refresh_enabled()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._offsets())
            self._set_offsets(self.undo_stack.pop())
            self._refresh_enabled()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._offsets())
            self._set_offsets(self.redo_stack.pop())
            self._refresh_enabled()

    def _sync_spin(self):
        self.offset_spin.blockSignals(True)
        self.offset_spin.setValue(-self.music_delta())
        self.offset_spin.blockSignals(False)

    def _on_timeline_offsets(self):
        self._sync_spin()
        self._request_resync()

    def _on_spin(self, v):
        if abs(v - (-self.music_delta())) < 1e-6:
            return
        self._push_undo(coalesce=True)
        tl = self.timeline
        tl.music.offset = tl.video.offset + v
        tl.update()
        self._request_resync()

    def nudge(self, dt):
        if self.mplayer.data is not None:
            self.offset_spin.setValue(self.offset_spin.value() + dt)

    def auto_align(self, silent=False):
        if self.video_flux is None or self.music_flux is None:
            return
        self.busy.add("align")
        self._refresh_enabled()
        self.bridge.status.emit("Procurando o encaixe…")
        QApplication.processEvents()
        try:
            d = audio.auto_align(self.video_flux, self.music_flux)
        finally:
            self.busy.discard("align")
        self._push_undo()
        self._auto_done = True
        tl = self.timeline
        tl.suggestion = -d
        tl.music.offset = tl.video.offset - d
        self._sync_spin()
        self._request_resync()
        tl.fit()
        self.bridge.status.emit(f"Encaixe sugerido: {fmt_delta(-d)} — toque para conferir")
        self._refresh_enabled()

    # ================================================================ reprodução
    def current_time(self):
        if self.video_path:
            raw = self.vplayer.position() / 1000.0
            if not self.playing or self.vplayer.playbackState() != QMediaPlayer.PlayingState:
                self._anchor = None
                return raw
            # relógio suavizado: a posição do Qt anda em degraus de ~1 quadro
            now = time.perf_counter()
            if self._anchor is None:
                self._anchor = [raw, now]
                return raw
            pred = self._anchor[0] + (now - self._anchor[1])
            err = raw - pred
            if abs(err) > 0.15:
                self._anchor = [raw, now]
                return raw
            self._anchor[0] += err * 0.05
            return pred + err * 0.05
        if self.playing:
            return self._clock_pos + time.perf_counter() - self._clock_t0
        return self._clock_pos

    def total_duration(self):
        if self.video_path:
            return self.timeline.video.duration or self.vplayer.duration() / 1000
        return max(0.0, self.timeline.music.duration - self.music_delta())

    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.video_path and self.mplayer.data is None:
            return
        t = self.current_time()
        dur = self.total_duration()
        if dur and t >= dur - 0.05:
            t = self.loop_range()[0] if self.loop else 0.0
            self.seek(t)
        self.playing = True
        if self.video_path:
            self.vplayer.play()
        else:
            self._clock_pos, self._clock_t0 = t, time.perf_counter()
        if self.mplayer.data is not None:
            try:
                self.mplayer.play(t + self.music_delta())
            except Exception as e:
                self._on_error(f"Erro na saída de áudio:\n{e}")
        self.btn_play.setText("❚❚")

    def pause(self):
        if self.playing and not self.video_path:
            self._clock_pos = self.current_time()
        self.playing = False
        self.vplayer.pause()
        self.mplayer.pause()
        self.btn_play.setText("▶")

    def stop(self):
        self.pause()
        self.seek(0.0)

    def seek(self, t):
        if self.video_path:
            self.vplayer.setPosition(int(t * 1000))
            self._anchor = None
        self._clock_pos, self._clock_t0 = t, time.perf_counter()
        self.mplayer.seek(t + self.music_delta())
        self._drift.clear()
        self.timeline.playhead = t
        self.timeline.update()

    def _request_resync(self):
        self._need_resync = True

    def loop_range(self):
        """Trecho repetido no modo loop: do início ao fim da música (dentro do vídeo)."""
        dur = self.total_duration()
        if self.mplayer.data is None:
            return 0.0, dur
        d = self.music_delta()
        start = max(0.0, -d)
        end = self.timeline.music.duration - d
        if dur:
            end = min(end, dur)
        if end - start < 0.2:          # música fora do vídeo: repete o vídeo todo
            return 0.0, dur
        return start, end

    def _loop_restart(self):
        # o setPosition do vídeo é assíncrono: por alguns ticks a posição ainda é a antiga
        if time.perf_counter() - self._last_loop > 0.3:
            self._last_loop = time.perf_counter()
            self.seek(self.loop_range()[0])
        if self.video_path and self.vplayer.playbackState() != QMediaPlayer.PlayingState:
            self.vplayer.play()

    def _on_playback_state(self, state):
        if state == QMediaPlayer.StoppedState and self.playing:
            if self.loop:
                QTimer.singleShot(0, self._loop_restart)   # fim do vídeo: volta ao início
            else:
                self.pause()   # fim do vídeo

    def _tick(self):
        t = self.current_time()
        tl = self.timeline
        now = time.perf_counter()
        if self.playing and self.loop:
            start, end = self.loop_range()
            if end and t >= end - 0.02 and now - self._last_loop > 0.3:
                self._loop_restart()
                t = start
        if self.playing:
            target = t + self.music_delta()
            if self.mplayer.data is not None and self.mplayer.playing:
                if self._need_resync:
                    # arrastando enquanto toca: ressincroniza no máximo ~12x/s
                    if now - self._last_resync > 0.08:
                        self.mplayer.seek(target)
                        self._drift.clear()
                        self._need_resync = False
                        self._last_resync = now
                else:
                    # mediana das últimas medições: a posição do vídeo "pula" de frame em frame
                    self._drift.append(self.mplayer.time() - target)
                    if len(self._drift) == self._drift.maxlen and \
                            abs(float(np.median(self._drift))) > SYNC_TOLERANCE:
                        self.mplayer.seek(target)
                        self._drift.clear()
            if not self.video_path and t > self.total_duration():
                self.pause()
            tl.ensure_visible(tl.video.offset + t)
        else:
            if self._need_resync:
                self.mplayer.seek(t + self.music_delta())
            self._need_resync = False
        if abs(tl.playhead - t) > 1e-4:
            tl.playhead = t
            tl.update()
        dur = self.total_duration()
        txt = f"{fmt_time(t)}  /  {fmt_time(dur, ms=False)}" if dur else fmt_time(t)
        self.time_label.setText(txt)
        if self.vwin is not None and self.vwin.isVisible():
            self.vwin.time.setText(txt)
            self.vwin.btn_play.setText("❚❚" if self.playing else "▶")

    # ================================================================ exportar
    def export(self):
        if not self.video_path or self.music_path is None:
            return
        base = os.path.splitext(os.path.basename(self.video_path))[0]
        mkv = "MKV — qualidade máxima, áudio sem perdas FLAC (*.mkv)"
        mp4 = "MP4 — áudio AAC 320 kbps, abre em qualquer lugar (*.mp4)"
        out, chosen = QFileDialog.getSaveFileName(self, "Salvar vídeo",
                                                  os.path.join(os.path.expanduser("~"), f"{base}_nova_musica.mkv"),
                                                  f"{mkv};;{mp4}", mkv)
        if not out:
            return
        ext = os.path.splitext(out)[1].lower()
        if ext not in (".mkv", ".mp4"):
            out += ".mp4" if chosen == mp4 else ".mkv"
        self.busy.add("export")
        self._refresh_enabled()
        self.bridge.status.emit("Exportando…")
        self.bridge.progress.emit(-1)
        run_bg(self._export_worker, out, self.music_delta(), self.mvol.value() / 100,
               self.vvol.value() / 100, self.total_duration())

    def _export_worker(self, out, d, mvol, vvol, duration):
        try:
            cmd = [audio.ffmpeg_exe(), "-y", "-v", "error", "-i", self.video_path]
            if d > 0:
                cmd += ["-ss", f"{d:.6f}"]
            cmd += ["-i", self.music_path]
            # sem reamostrar: a música sai na taxa original; volume 100% = não toca nas amostras
            filters = []
            if d < 0:
                rate = audio.probe_rate(self.music_path) or audio.SR
                filters.append(f"adelay=delays={int(round(-d * rate))}S:all=1")   # atraso exato, em amostras
            if abs(mvol - 1.0) > 1e-6:
                filters.append(f"volume={mvol:.3f}")
            chain = "[1:a]" + (",".join(filters) or "anull") + "[m]"
            if vvol > 0 and self.video_flux is not None:
                fc = f"{chain};[0:a]volume={vvol:.3f}[o];[m][o]amix=inputs=2:normalize=0:duration=longest[a]"
            else:
                fc = chain.replace("[m]", "[a]")
            if out.lower().endswith(".mkv"):
                acodec = ["-c:a", "flac", "-compression_level", "8"]
            else:
                acodec = ["-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
            cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]",
                    "-c:v", "copy", *acodec, "-t", f"{duration:.3f}", out]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  **audio._popen_kwargs())
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode(errors="replace"))
            self.bridge.exported.emit(out)
        except Exception as e:
            self.bridge.error.emit(f"Falha ao exportar:\n{e}")

    def _on_exported(self, out):
        self.busy.discard("export")
        self.bridge.progress.emit(100)
        self.bridge.status.emit(f"Salvo: {os.path.basename(out)}")
        self.busy.discard("wav")
        self._refresh_enabled()
        what = "Áudio" if out.lower().endswith(".wav") else "Vídeo"
        QMessageBox.information(self, APP_NAME, f"{what} salvo em:\n{out}")

    # ================================================================ teclado
    def keyPressEvent(self, e):
        # só chega aqui se o widget focado (ex.: campo de texto) não usou a tecla
        step = 0.001 if e.modifiers() & Qt.ShiftModifier else 0.01
        if e.key() == Qt.Key_Space:
            self.toggle_play()
        elif e.key() == Qt.Key_Left:
            self.nudge(-step)
        elif e.key() == Qt.Key_Right:
            self.nudge(step)
        elif e.key() == Qt.Key_Home:
            self.seek(0.0)
        elif e.key() == Qt.Key_L and self.btn_loop.isEnabled():
            self.btn_loop.toggle()
        elif e.key() in (Qt.Key_F, Qt.Key_F11):
            self.toggle_fullscreen()
        elif e.key() == Qt.Key_Escape and self.vwin is not None and self.vwin.mode == "fullscreen":
            self.vwin.exit_fullscreen()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # clicar fora dos campos tira o foco deles (libera Espaço/setas)
        fw = QApplication.focusWidget()
        if fw is not None:
            fw.clearFocus()
        super().mousePressEvent(e)

    def closeEvent(self, e):
        if self.vwin is not None:
            self.vwin.main = None
            self.vwin.hide()
            self.vwin.deleteLater()
        self.mplayer.close()
        self.vplayer.stop()
        super().closeEvent(e)


def _open_main(argv):
    w = MainWindow()
    if w._start_maximized:
        w.showMaximized()
    else:
        w.show()
    # arquivos/links passados na linha de comando ("Abrir com…" do gerenciador de arquivos)
    for arg in argv:
        if arg.startswith("http"):
            w.url_edit.setText(arg)
            w.download()
        elif os.path.isfile(arg):
            ext = os.path.splitext(arg)[1].lower()
            if ext in AUDIO_EXT:
                w.load_music(os.path.abspath(arg))
            elif ext in VIDEO_EXT:
                w.load_video(os.path.abspath(arg), os.path.basename(arg))
    return w


def main():
    install_excepthook()
    import platform
    log.info("Portinho %s iniciando · %s · Python %s · %s", __version__, platform.platform(),
             platform.python_version(), "empacotado" if getattr(sys, "frozen", False) else "código-fonte")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("portinho")
    theme.apply(app)
    icon_path = None
    for base in (audio.resource_dir(), os.path.join(os.path.dirname(__file__), "..")):
        icon = os.path.join(base, "assets", "icon.png")
        if os.path.exists(icon):
            icon_path = icon
            app.setWindowIcon(QIcon(icon))
            break
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    holder = {}

    def go():
        holder["w"] = _open_main(args)

    if "--no-update" in sys.argv or os.environ.get("PORTINHO_NO_UPDATE"):
        go()
    else:
        from .splash import Splash
        holder["splash"] = Splash(go, icon_path)
        holder["splash"].start()
    sys.exit(app.exec())
