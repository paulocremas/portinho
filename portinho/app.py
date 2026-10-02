"""Portinho — troca a música de um vídeo do YouTube por um arquivo do PC, alinhando pelo espectrograma."""
import os
import subprocess
import sys
import threading
import time
from collections import deque

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import audio, theme
from .player import MusicPlayer
from .timeline import Timeline, fmt_delta, fmt_time

APP_NAME = "Portinho"
SYNC_TOLERANCE = 0.040   # s de diferença antes de ressincronizar a música
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

        self.video_path = None
        self.music_path = None
        self.video_flux = None
        self.music_flux = None
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
        self.vplayer.errorOccurred.connect(lambda _e, msg: msg and self._on_error(f"Vídeo: {msg}"))
        self.mplayer = MusicPlayer()

        self.playing = False
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
        r.addWidget(self.url_edit, 1)
        r.addWidget(self.btn_dl)
        vc.addLayout(r)
        self.video_info = QLabel("Sem anúncios · o vídeo toca sem o som original")
        self.video_info.setObjectName("muted")
        vc.addWidget(self.video_info)
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
                      "roda = zoom  ·  Shift+roda / botão direito = rolar  ·  Espaço = tocar  ·  ←/→ = 10 ms  ·  Ctrl+Z = desfazer")
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
        for w in (self.offset_spin, self.btn_minus, self.btn_plus):
            w.setEnabled(has_m)
        self.btn_auto.setEnabled(both and "align" not in self.busy)
        self.btn_export.setEnabled(has_v and has_m and "export" not in self.busy)
        self.btn_dl.setEnabled("download" not in self.busy)
        self.btn_undo.setEnabled(bool(self.undo_stack))
        for badge, done in ((self.video_step, self.timeline.video.loaded),
                            (self.music_step, self.timeline.music.loaded),
                            (self.align_step, self._auto_done or bool(self.undo_stack))):
            if badge.property("done") != done:
                badge.setProperty("done", done)
                repolish(badge)

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
        QMessageBox.warning(self, APP_NAME, msg)

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
            import yt_dlp

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

            opts = {
                "format": "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(data_dir(), "%(id)s.%(ext)s"),
                "ffmpeg_location": audio.ffmpeg_exe(),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [hook],
            }
            deno = os.path.join(audio.resource_dir(), "deno.exe" if os.name == "nt" else "deno")
            if os.path.exists(deno):
                opts["js_runtimes"] = {"deno": {"path": deno}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = next(e for e in info["entries"] if e)
                reqs = info.get("requested_downloads") or []
                path = reqs[0]["filepath"] if reqs else ydl.prepare_filename(info)
            self.busy.discard("download")
            self.bridge.videoReady.emit(path, info.get("title") or os.path.basename(path))
        except Exception as e:
            msg = str(e).replace("\x1b[0;31m", "").replace("\x1b[0m", "")
            self.bridge.error.emit(f"Não foi possível baixar o vídeo.\n\n{msg}")

    def open_local_video(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT))
        path, _ = QFileDialog.getOpenFileName(self, "Escolher vídeo", "", f"Vídeos ({exts});;Todos (*)")
        if path:
            self.load_video(path, os.path.basename(path))

    def load_video(self, path, title=""):
        self.stop()
        self.video_path = path
        self.video_flux = None
        self._auto_done = False
        self.timeline.video.duration = 0.0
        self.timeline.video.image = None
        self.timeline.suggestion = None
        self.vplayer.setSource(QUrl.fromLocalFile(path))
        self.video_stack.setCurrentIndex(1)
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
            rgb, flux = audio.spectrogram(data.mean(axis=1))
            result = {"rgb": rgb, "flux": flux, "duration": len(data) / audio.SR, "path": path}
            if kind == "music":
                result["data"] = data
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
            self.mplayer.set_data(r["data"])
            self.music_flux = r["flux"]
            self.dropzone.setText(f"♪   {os.path.basename(r['path'])}\n"
                                  f"{fmt_time(r['duration'], ms=False)}  ·  clique para trocar")
            self.dropzone.setProperty("done", True)
            repolish(self.dropzone)
        self.busy.discard("analyze_" + kind)
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
            self.seek(0.0)
            t = 0.0
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

    def _on_playback_state(self, state):
        if state == QMediaPlayer.StoppedState and self.playing:
            self.pause()   # fim do vídeo

    def _tick(self):
        t = self.current_time()
        tl = self.timeline
        now = time.perf_counter()
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
        self.time_label.setText(f"{fmt_time(t)}  /  {fmt_time(dur, ms=False)}" if dur else fmt_time(t))

    # ================================================================ exportar
    def export(self):
        if not self.video_path or self.music_path is None:
            return
        base = os.path.splitext(os.path.basename(self.video_path))[0]
        out, _ = QFileDialog.getSaveFileName(self, "Salvar vídeo",
                                             os.path.join(os.path.expanduser("~"), f"{base}_nova_musica.mp4"),
                                             "MP4 (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
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
                cmd += ["-ss", f"{d:.4f}"]
            cmd += ["-i", self.music_path]
            chain = f"[1:a]aresample={audio.SR}"
            if d < 0:
                ms = int(round(-d * 1000))
                chain += f",adelay={ms}|{ms}"
            chain += f",volume={mvol:.3f}[m]"
            if vvol > 0 and self.video_flux is not None:
                fc = f"{chain};[0:a]volume={vvol:.3f}[o];[m][o]amix=inputs=2:normalize=0:duration=longest[a]"
            else:
                fc = chain.replace("[m]", "[a]")
            cmd += ["-filter_complex", fc, "-map", "0:v:0", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
                    "-t", f"{duration:.3f}", "-movflags", "+faststart", out]
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
        self._refresh_enabled()
        QMessageBox.information(self, APP_NAME, f"Vídeo salvo em:\n{out}")

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
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # clicar fora dos campos tira o foco deles (libera Espaço/setas)
        fw = QApplication.focusWidget()
        if fw is not None:
            fw.clearFocus()
        super().mousePressEvent(e)

    def closeEvent(self, e):
        self.mplayer.close()
        self.vplayer.stop()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("portinho")
    theme.apply(app)
    for base in (audio.resource_dir(), os.path.join(os.path.dirname(__file__), "..")):
        icon = os.path.join(base, "assets", "icon.png")
        if os.path.exists(icon):
            app.setWindowIcon(QIcon(icon))
            break
    w = MainWindow()
    if w._start_maximized:
        w.showMaximized()
    else:
        w.show()
    # arquivos/links passados na linha de comando ("Abrir com…" do gerenciador de arquivos)
    for arg in sys.argv[1:]:
        if arg.startswith("http"):
            w.url_edit.setText(arg)
            w.download()
        elif os.path.isfile(arg):
            ext = os.path.splitext(arg)[1].lower()
            if ext in AUDIO_EXT:
                w.load_music(os.path.abspath(arg))
            elif ext in VIDEO_EXT:
                w.load_video(os.path.abspath(arg), os.path.basename(arg))
    sys.exit(app.exec())
