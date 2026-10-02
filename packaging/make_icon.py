"""Gera assets/icon.png e assets/icon.ico (roda uma vez, antes de empacotar)."""
import math
import os
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

app = QGuiApplication(sys.argv)
OUT = os.path.join(os.path.dirname(__file__), "..", "assets")


def draw(size):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#8b5cf6"))
    g.setColorAt(1, QColor("#4338ca"))
    p.fillPath(bg, g)
    # duas "ondas" (vídeo em cima, música embaixo), deslocadas
    for row, (col, phase) in enumerate((("#7dd3fc", 0.0), ("#fbbf24", 0.9))):
        y0 = (96 + row * 70) * s
        p.setPen(QPen(QColor(col), 9 * s, Qt.SolidLine, Qt.RoundCap))
        for i in range(9):
            x = (52 + i * 19) * s
            h = (8 + 18 * abs(math.sin(i * 0.9 + phase))) * s
            p.drawLine(QPointF(x, y0 - h), QPointF(x, y0 + h))
    # linha de alinhamento
    p.setPen(QPen(QColor("white"), 6 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(128 * s, 48 * s), QPointF(128 * s, 212 * s))
    p.setBrush(QColor("white"))
    p.setPen(Qt.NoPen)
    p.drawPolygon(QPolygonF([QPointF(112 * s, 40 * s), QPointF(144 * s, 40 * s), QPointF(128 * s, 60 * s)]))
    p.end()
    return img


os.makedirs(OUT, exist_ok=True)
draw(512).save(os.path.join(OUT, "icon.png"))
draw(256).save(os.path.join(OUT, "icon.ico"))
print("ok")
