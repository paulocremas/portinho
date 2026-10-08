"""Ícones desenhados em código (não dependem de fonte com os símbolos)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def make(kind, color="#e8eaf0", size=18):
    px = QPixmap(size * 2, size * 2)          # 2x para telas de alta densidade
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    s = size * 2 / 18
    pen = QPen(QColor(color), 1.8 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if kind == "fullscreen":
        a, b, k = 3 * s, 15 * s, 4.5 * s
        for (x, y, dx, dy) in ((a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))
    elif kind == "exit_fullscreen":
        a, b, k = 7 * s, 11 * s, 4.5 * s
        for (x, y, dx, dy) in ((a, a, -1, -1), (b, a, 1, -1), (a, b, -1, 1), (b, b, 1, 1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * k, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * k))
    elif kind == "popup":
        p.drawRoundedRect(QRectF(2.5 * s, 5.5 * s, 10 * s, 9 * s), 1.5 * s, 1.5 * s)
        p.drawLine(QPointF(9 * s, 2.5 * s), QPointF(15.5 * s, 2.5 * s))
        p.drawLine(QPointF(15.5 * s, 2.5 * s), QPointF(15.5 * s, 9 * s))
        p.drawLine(QPointF(15.5 * s, 2.5 * s), QPointF(9.5 * s, 8.5 * s))
    elif kind == "dock":
        p.drawRoundedRect(QRectF(2.5 * s, 3 * s, 13 * s, 12 * s), 1.5 * s, 1.5 * s)
        p.drawLine(QPointF(12 * s, 6.5 * s), QPointF(6.5 * s, 12 * s))
        p.drawLine(QPointF(6.5 * s, 12 * s), QPointF(6.5 * s, 8 * s))
        p.drawLine(QPointF(6.5 * s, 12 * s), QPointF(10.5 * s, 12 * s))
    elif kind == "loop":
        top = QPainterPath(QPointF(3 * s, 10 * s))
        top.lineTo(QPointF(3 * s, 8 * s))
        top.quadTo(QPointF(3 * s, 5 * s), QPointF(6 * s, 5 * s))
        top.lineTo(QPointF(14.5 * s, 5 * s))
        bot = QPainterPath(QPointF(15 * s, 8 * s))
        bot.lineTo(QPointF(15 * s, 10 * s))
        bot.quadTo(QPointF(15 * s, 13 * s), QPointF(12 * s, 13 * s))
        bot.lineTo(QPointF(3.5 * s, 13 * s))
        p.drawPath(top)
        p.drawPath(bot)
        p.drawLine(QPointF(14.5 * s, 5 * s), QPointF(12 * s, 2.5 * s))
        p.drawLine(QPointF(14.5 * s, 5 * s), QPointF(12 * s, 7.5 * s))
        p.drawLine(QPointF(3.5 * s, 13 * s), QPointF(6 * s, 10.5 * s))
        p.drawLine(QPointF(3.5 * s, 13 * s), QPointF(6 * s, 15.5 * s))
    p.end()
    return QIcon(px)
