"""Linha do tempo com os espectrogramas do vídeo e da música, arrastáveis.

Interações:
  arrastar um clipe ........ move o clipe (com ímã nas bordas, cabeça e ponto sugerido)
  Ctrl durante o arraste ... desliga o ímã (Alt+arrastar é do sistema no Linux)
  Shift durante o arraste .. ajuste fino (10x mais devagar)
  clique simples ........... leva a reprodução até aquele ponto
  régua / linha branca ..... arrastar para "varrer" o vídeo
  roda ..................... zoom no cursor  ·  Shift+roda / touchpad lateral = rolar
  arrastar fundo vazio, botão direito ou do meio = rolar
"""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

RULER_H = 28
TRACK_H_MIN = 52
TRACK_H_MAX = 130
GAP = 10
PAD_BOTTOM = 8
SNAP_PX = 10
EDGE_PX = 40          # zona de rolagem automática nas bordas
CLICK_PX = 4          # movimento menor que isso = clique, não arraste

BG = QColor("#12141a")
TRACK_BG = QColor("#181b22")
RULER_BG = QColor("#12141a")
GRID = QColor("#232733")
TEXT = QColor("#e8eaf0")
MUTED = QColor("#8b93a7")
PLAYHEAD = QColor("#ffffff")
SNAP = QColor("#a78bfa")


def fmt_time(t, ms=True):
    sign = "-" if t < 0 else ""
    t = abs(t)
    m, s = divmod(t, 60)
    return f"{sign}{int(m)}:{s:06.3f}" if ms else f"{sign}{int(m)}:{int(s):02d}"


def fmt_delta(d):
    return f"{d:+.3f} s".replace(".", ",")


class Track:
    def __init__(self, name, color):
        self.name = name
        self.color = QColor(color)
        self.image = None
        self.fps = 1.0
        self.duration = 0.0
        self.offset = 0.0       # início do clipe na linha do tempo (s)

    @property
    def loaded(self):
        return self.duration > 0

    def set_spectrogram(self, rgb, fps, duration):
        h, w, _ = rgb.shape
        self.image = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format_RGB888).copy()
        self.fps = fps
        self.duration = duration


class Timeline(QWidget):
    offsetsChanged = Signal()
    dragFinished = Signal(tuple)     # offsets (vídeo, música) ANTES do arraste, p/ desfazer
    seekRequested = Signal(float)    # tempo do vídeo (s)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video = Track("Vídeo", "#38bdf8")
        self.music = Track("Música", "#f59e0b")
        self.tracks = [self.video, self.music]
        self.pps = 40.0
        self.view_start = -2.0
        self.playhead = 0.0          # tempo do vídeo (s)
        self.suggestion = None       # deslocamento sugerido pelo auto-alinhar (música - vídeo)
        self._drag = None
        self._hover = None
        self._snap_x = None
        self._mouse = QPointF()
        self.setMinimumHeight(int(RULER_H + 2 * TRACK_H_MIN + 2 * GAP + PAD_BOTTOM))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(16)
        self._edge_timer.timeout.connect(self._edge_scroll)

    # ---------------------------------------------------------- coordenadas
    def t2x(self, t):
        return (t - self.view_start) * self.pps

    def x2t(self, x):
        return x / self.pps + self.view_start

    def track_h(self):
        # faixas elásticas: dividem a altura disponível
        free = self.height() - RULER_H - 2 * GAP - PAD_BOTTOM
        return max(TRACK_H_MIN, min(TRACK_H_MAX, free / 2))

    def track_rect(self, i):
        h = self.track_h()
        y = RULER_H + GAP + i * (h + GAP)
        return QRectF(0, y, self.width(), h)

    def clip_rect(self, i):
        tr, r = self.tracks[i], self.track_rect(i)
        x0, x1 = self.t2x(tr.offset), self.t2x(tr.offset + tr.duration)
        return QRectF(x0, r.top(), x1 - x0, r.height())

    def music_delta(self):
        """d tal que tempo_música = tempo_vídeo + d."""
        return self.video.offset - self.music.offset

    def playhead_x(self):
        return self.t2x(self.video.offset + self.playhead)

    def fit(self):
        ts = [t for t in self.tracks if t.loaded]
        if not ts:
            return
        start = min(t.offset for t in ts)
        end = max(t.offset + t.duration for t in ts)
        span = max(end - start, 1.0)
        self.pps = max(0.5, (self.width() - 40) / span)
        self.view_start = start - 20 / self.pps
        self.update()

    def zoom(self, factor, x=None):
        x = self.width() / 2 if x is None else x
        t = self.x2t(x)
        self.pps = min(max(self.pps * factor, 0.5), 4000.0)
        self.view_start = t - x / self.pps
        self.update()

    def ensure_visible(self, t_timeline):
        if self._drag is not None:
            return
        w = self.width() / self.pps
        if t_timeline < self.view_start or t_timeline > self.view_start + w * 0.92:
            self.view_start = t_timeline - w * 0.1
            self.update()

    # ---------------------------------------------------------- desenho
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)
        self._paint_ruler(p)
        for i in range(len(self.tracks)):
            self._paint_track(p, i)
        if self._snap_x is not None:
            p.setPen(QPen(SNAP, 1.5, Qt.DashLine))
            p.drawLine(QPointF(self._snap_x, RULER_H), QPointF(self._snap_x, self.height()))
        self._paint_playhead(p)
        if self._drag and self._drag["kind"] == "move" and self._drag["moved"]:
            self._paint_badge(p)
        p.end()

    def _step(self):
        steps = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800]
        return next((s for s in steps if s * self.pps >= 80), 1800)

    def _paint_ruler(self, p):
        p.fillRect(QRectF(0, 0, self.width(), RULER_H), RULER_BG)
        step = self._step()
        t = (self.view_start // step) * step
        end = self.x2t(self.width())
        p.setFont(QFont(self.font().family(), 8))
        while t <= end:
            x = self.t2x(t)
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, self.height()))
            p.setPen(MUTED)
            p.drawText(QPointF(x + 4, RULER_H - 10), fmt_time(t, ms=step < 1))
            t += step
        p.setPen(QPen(GRID, 1))
        p.drawLine(QPointF(0, RULER_H - 0.5), QPointF(self.width(), RULER_H - 0.5))

    def _paint_track(self, p, i):
        tr, r = self.tracks[i], self.track_rect(i)
        lane = QPainterPath()
        lane.addRoundedRect(r.adjusted(6, 0, -6, 0), 10, 10)
        p.fillPath(lane, TRACK_BG)

        if not tr.loaded:
            p.setPen(MUTED)
            p.setFont(QFont(self.font().family(), 10))
            msg = "Carregue um vídeo acima" if tr is self.video else "Escolha uma música acima"
            p.drawText(r, Qt.AlignCenter, msg)
            return

        c = self.clip_rect(i)
        dragging = self._drag is not None and self._drag.get("track") is tr and self._drag["moved"]
        hovered = self._hover is tr

        clip = QPainterPath()
        clip.addRoundedRect(c.adjusted(0, 3, 0, -3), 8, 8)
        if dragging:   # "levanta" o clipe: sombra
            shadow = QPainterPath()
            shadow.addRoundedRect(c.adjusted(-2, 6, 2, 2), 10, 10)
            p.fillPath(shadow, QColor(0, 0, 0, 120))

        p.save()
        p.setClipPath(clip)
        p.fillPath(clip, QColor("#000004"))
        if tr.image is not None:
            vx0, vx1 = max(c.left(), 0.0), min(c.right(), float(self.width()))
            if vx1 > vx0:
                sx0 = max(0.0, (self.x2t(vx0) - tr.offset) * tr.fps)
                sx1 = min(float(tr.image.width()), (self.x2t(vx1) - tr.offset) * tr.fps)
                target = QRectF(vx0, c.top() + 3, vx1 - vx0, c.height() - 6)
                source = QRectF(sx0, 0, max(sx1 - sx0, 0.01), tr.image.height())
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawImage(target, tr.image, source)
        if hovered or dragging:   # leve brilho na cor do clipe
            tint = QColor(tr.color)
            tint.setAlpha(28)
            p.fillPath(clip, tint)
        p.restore()

        # borda
        border = QColor(tr.color)
        if not (hovered or dragging):
            border.setAlpha(170)
        p.setPen(QPen(border, 3 if dragging else (2.2 if hovered else 1.6)))
        p.setBrush(Qt.NoBrush)
        p.drawPath(clip)

        # etiqueta (fica visível mesmo se o início do clipe estiver fora da tela)
        label = f"⠿  {tr.name}"
        if tr is self.music and self.video.loaded:
            label += f"   {fmt_delta(-self.music_delta())}"
        p.setFont(QFont(self.font().family(), 9, QFont.Bold))
        lw = p.fontMetrics().horizontalAdvance(label) + 16
        tx = max(c.left(), 0.0) + 6
        if tx + lw < c.right() - 4:
            pill = QPainterPath()
            box = QRectF(tx, c.top() + 7, lw, 20)
            pill.addRoundedRect(box, 6, 6)
            col = QColor(tr.color)
            col.setAlpha(240 if (hovered or dragging) else 215)
            p.fillPath(pill, col)
            p.setPen(QColor("#0b0d12"))
            p.drawText(box, Qt.AlignCenter, label)

    def _paint_playhead(self, p):
        x = self.playhead_x()
        p.setPen(QPen(PLAYHEAD, 2))
        p.drawLine(QPointF(x, RULER_H - 2), QPointF(x, self.height()))
        tri = QPolygonF([QPointF(x - 7, 4), QPointF(x + 7, 4), QPointF(x, RULER_H - 2)])
        p.setBrush(PLAYHEAD)
        p.setPen(Qt.NoPen)
        p.drawPolygon(tri)
        p.setBrush(Qt.NoBrush)

    def _paint_badge(self, p):
        tr = self._drag["track"]
        if self.video.loaded and self.music.loaded:
            txt = f"Música {fmt_delta(-self.music_delta())}"
        else:
            txt = f"Início {fmt_time(tr.offset)}"
        if self._snap_x is not None:
            txt += "  · ímã"
        p.setFont(QFont(self.font().family(), 10, QFont.Bold))
        w = p.fontMetrics().horizontalAdvance(txt) + 20
        x = min(max(self._mouse.x() + 14, 4), self.width() - w - 4)
        y = max(self._mouse.y() - 40, 2)
        box = QRectF(x, y, w, 28)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        p.fillPath(path, QColor("#0b0d12"))
        p.setPen(QPen(tr.color, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(TEXT)
        p.drawText(box, Qt.AlignCenter, txt)

    # ---------------------------------------------------------- hit-test
    def _clip_at(self, pos):
        for i, tr in enumerate(self.tracks):
            if tr.loaded and self.clip_rect(i).contains(pos):
                return tr
        return None

    def _near_playhead(self, pos):
        return abs(pos.x() - self.playhead_x()) <= 5 and pos.y() > RULER_H

    def _update_cursor(self, pos):
        if pos.y() < RULER_H or self._near_playhead(pos):
            self.setCursor(Qt.SizeHorCursor)
        elif self._clip_at(pos) is not None:
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    # ---------------------------------------------------------- ímã
    def _snap_candidates(self, tr):
        """Pares (tempo alvo, borda do clipe: 0=início, dur=fim)."""
        other = self.music if tr is self.video else self.video
        targets = [0.0]
        if tr is self.music:          # mover o vídeo carrega a cabeça junto
            targets.append(self.video.offset + self.playhead)
        if other.loaded:
            targets += [other.offset, other.offset + other.duration]
        cands = [(t, e) for t in targets for e in (0.0, tr.duration)]
        if self.suggestion is not None and other.loaded:
            s = self.suggestion if tr is self.music else -self.suggestion
            cands.append((other.offset + s, 0.0))
        return cands

    def _apply_snap(self, tr, new_offset, enabled):
        self._snap_x = None
        if not enabled:
            return new_offset
        best, best_px = new_offset, SNAP_PX + 1
        for t, edge in self._snap_candidates(tr):
            d_px = abs((new_offset + edge - t) * self.pps)
            if d_px < best_px:
                best, best_px = t - edge, d_px
                self._snap_x = self.t2x(t)
        return best

    # ---------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        pos = e.position()
        self._mouse = pos
        if e.button() == Qt.LeftButton:
            if pos.y() < RULER_H or self._near_playhead(pos):
                self._drag = {"kind": "scrub", "moved": True}
                self._seek_to_x(pos.x())
                return
            tr = self._clip_at(pos)
            if tr is not None:
                self._drag = {"kind": "move", "track": tr, "moved": False,
                              "press_x": pos.x(), "anchor_t": self.x2t(pos.x()),
                              "anchor_off": tr.offset, "fine": bool(e.modifiers() & Qt.ShiftModifier),
                              "before": (self.video.offset, self.music.offset)}
                self.setCursor(Qt.ClosedHandCursor)
                return
            self._drag = {"kind": "pan", "moved": False, "press_x": pos.x(),
                          "vs0": self.view_start, "click_seek": True}
            return
        if e.button() in (Qt.MiddleButton, Qt.RightButton):
            self._drag = {"kind": "pan", "moved": True, "press_x": pos.x(),
                          "vs0": self.view_start, "click_seek": False}
            self.setCursor(Qt.SizeHorCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._mouse = pos
        d = self._drag
        if d is None:
            hov = self._clip_at(pos)
            if hov is not self._hover:
                self._hover = hov
                self.update()
            self._update_cursor(pos)
            return
        if d["kind"] == "scrub":
            self._seek_to_x(pos.x())
            self._edge_timer.start()
            return
        if not d["moved"] and abs(pos.x() - d["press_x"]) >= CLICK_PX:
            d["moved"] = True
            if d["kind"] == "pan":
                self.setCursor(Qt.ClosedHandCursor)
        if not d["moved"]:
            return
        if d["kind"] == "move":
            self._move_clip(e.modifiers())
            self._edge_timer.start()
        elif d["kind"] == "pan":
            self.view_start = d["vs0"] - (pos.x() - d["press_x"]) / self.pps
            self.update()

    def _move_clip(self, mods):
        d = self._drag
        tr = d["track"]
        fine = bool(mods & Qt.ShiftModifier)
        t = self.x2t(self._mouse.x())
        if fine != d["fine"]:          # trocou o modo no meio: re-ancora sem pular
            d["fine"], d["anchor_t"], d["anchor_off"] = fine, t, tr.offset
        k = 0.1 if fine else 1.0
        new = d["anchor_off"] + (t - d["anchor_t"]) * k
        tr.offset = self._apply_snap(tr, new, not (mods & Qt.ControlModifier) and not fine)
        self.offsetsChanged.emit()
        self.update()

    def _edge_scroll(self):
        d = self._drag
        if d is None or not d.get("moved"):
            self._edge_timer.stop()
            return
        x = self._mouse.x()
        if x < EDGE_PX:
            v = -(EDGE_PX - x)
        elif x > self.width() - EDGE_PX:
            v = x - (self.width() - EDGE_PX)
        else:
            return
        self.view_start += v * 0.25 / self.pps
        if d["kind"] == "move":
            from PySide6.QtWidgets import QApplication
            self._move_clip(QApplication.keyboardModifiers())
        elif d["kind"] == "scrub":
            self._seek_to_x(x)
        self.update()

    def mouseReleaseEvent(self, e):
        d = self._drag
        self._drag = None
        self._snap_x = None
        self._edge_timer.stop()
        if d is not None and not d["moved"] and d["kind"] in ("move", "pan") and \
                e.button() == Qt.LeftButton:
            self._seek_to_x(e.position().x())          # clique simples = ir para
        if d is not None and d["kind"] == "move" and d["moved"]:
            if d["before"] != (self.video.offset, self.music.offset):
                self.dragFinished.emit(d["before"])
        self._update_cursor(e.position())
        self.update()

    def leaveEvent(self, _):
        if self._hover is not None:
            self._hover = None
            self.update()

    def _seek_to_x(self, x):
        t = self.x2t(x) - self.video.offset
        if self.video.loaded:
            t = min(max(t, 0.0), self.video.duration)
        self.seekRequested.emit(max(t, 0.0))

    def wheelEvent(self, e):
        dx, dy = e.angleDelta().x(), e.angleDelta().y()
        if abs(dx) > abs(dy) or e.modifiers() & Qt.ShiftModifier:
            delta = dx if abs(dx) > abs(dy) else dy
            self.view_start -= delta / 120 * 80 / self.pps
            self.update()
        else:
            self.zoom(1.2 ** (dy / 120), e.position().x())
