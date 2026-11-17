"""Draws the app icon (stacked BOM sheets with a check mark) to app.ico."""
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

app = QGuiApplication(sys.argv)
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
bg = QPainterPath()
bg.addRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
p.fillPath(bg, QColor("#14202E"))
for i, col in enumerate(("#3B4C61", "#6F87A6", "#FFFFFF")):
    r = QRectF(58 + i * 14, 50 + i * 14, 112, 140)
    path = QPainterPath()
    path.addRoundedRect(r, 12, 12)
    p.fillPath(path, QColor(col))
p.setPen(QPen(QColor("#C9D3DF"), 9, Qt.SolidLine, Qt.RoundCap))
for y in (112, 138, 164):
    p.drawLine(104, y, 158, y)
p.setPen(QPen(QColor("#23935F"), 20, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
path = QPainterPath()
path.moveTo(132, 196)
path.lineTo(156, 218)
path.lineTo(204, 162)
p.setBrush(Qt.NoBrush)
p.drawPath(path)
p.end()
img.save(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
