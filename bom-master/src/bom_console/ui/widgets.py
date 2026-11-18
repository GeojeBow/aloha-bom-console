"""직접 그리는 위젯: 구성 막대, 일별 추이 그래프, 화살표, 알림."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget

from .theme import C, font, q


def label(text: str = "", *, muted=False, eyebrow=False, h1=False, big=False, bold=False, size=None, color=None,
          wrap=False) -> QLabel:
    lb = QLabel(text)
    for k, v in (("muted", muted), ("eyebrow", eyebrow), ("h1", h1), ("big", big)):
        if v:
            lb.setProperty(k, True)
    st = []
    if bold:
        st.append("font-weight:600")
    if size:
        st.append(f"font-size:{size}pt")
    if color:
        st.append(f"color:{color}")
    if st:
        lb.setStyleSheet(";".join(st))
    lb.setWordWrap(wrap)
    return lb


def card(soft=False) -> QFrame:
    f = QFrame()
    f.setProperty("soft" if soft else "card", True)
    return f


class StackBar(QWidget):
    """세그먼트 구성 막대. 세그먼트를 누르면 그 종류 키를 보낸다."""
    clicked = Signal(str)

    def __init__(self, height=14, parent=None):
        super().__init__(parent)
        self.segments: list[tuple[str, int, QColor, str]] = []  # key, n, color, label
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = None

    def set_segments(self, segs):
        self.segments = [s for s in segs if s[1] > 0]
        self.update()

    def _rects(self):
        tot = sum(s[1] for s in self.segments) or 1
        x, w = 0.0, float(self.width())
        out = []
        for s in self.segments:
            sw = w * s[1] / tot
            out.append((QRectF(x, 0, sw, self.height()), s))
            x += sw
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 4, 4)
        p.setClipPath(clip)
        p.fillRect(self.rect(), q("soft"))
        for r, s in self._rects():
            c = QColor(s[2])
            if self._hover == s[0]:
                c = c.lighter(118)
            p.fillRect(r.adjusted(0, 0, -1.5, 0), c)  # 세그먼트 사이 얇은 틈

    def mouseMoveEvent(self, e):
        for r, s in self._rects():
            if r.contains(e.position()):
                if self._hover != s[0]:
                    self._hover = s[0]
                    self.update()
                QToolTip.showText(e.globalPosition().toPoint(), f"{s[3]}  {s[1]:,}건", self)
                return
        self._hover = None
        self.update()

    def leaveEvent(self, _):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        for r, s in self._rects():
            if r.contains(e.position()):
                self.clicked.emit(s[0])
                return


class Arrow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(q("muted"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        y, x0, x1 = self.height() / 2, 4, self.width() - 6
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.drawLine(QPointF(x1 - 6, y - 6), QPointF(x1, y))
        p.drawLine(QPointF(x1 - 6, y + 6), QPointF(x1, y))


class TrendChart(QWidget):
    """일별 deviation 추이. 같은 축 하나에 SAP / 구매 두 선, 리포트 발송일은 점선, 새 파일은 아래 눈금."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.days: list[str] = []
        self.series: dict[str, list[int]] = {}
        self.colors = {"sap": q("sap"), "purchase": q("purchase")}
        self.names = {"sap": "SAP", "purchase": "구매"}
        self.reports: list[str] = []
        self.arrivals: dict[str, list[str]] = {}
        self.hover_i: int | None = None
        self.setMinimumHeight(240)
        self.setMouseTracking(True)

    def set_data(self, days, series, reports, arrivals):
        self.days, self.series, self.reports, self.arrivals = days, series, reports, arrivals
        self.update()

    def _geom(self):
        L, R, T, B = 52, 96, 24, 36
        return L, T, self.width() - L - R, self.height() - T - B

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        L, T, W, H = self._geom()
        p.setFont(font(8))
        if len(self.days) < 2:
            p.setPen(q("muted"))
            p.drawText(self.rect(), Qt.AlignCenter, "비교 기록이 이틀 이상 쌓이면 추이가 표시됩니다.")
            return
        mx = max([max(v) for v in self.series.values() if v] + [1])
        step = next(s for s in (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000) if mx / s <= 6)
        ymax = -(-mx // step) * step
        n = len(self.days)
        X = lambda i: L + i / (n - 1) * W
        Y = lambda v: T + H - v / ymax * H
        # 격자 + y축 라벨
        for v in range(0, int(ymax) + 1, step):
            p.setPen(QPen(QColor("#E6EAEE"), 1))
            p.drawLine(QPointF(L, Y(v)), QPointF(L + W, Y(v)))
            p.setPen(q("muted"))
            p.drawText(QRectF(0, Y(v) - 8, L - 8, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:,}")
        # x축 날짜 (1일, 15일)
        for i, d in enumerate(self.days):
            if (d[8:10] in ("01", "15") and i < n - 4) or i == n - 1:
                p.drawText(QRectF(X(i) - 30, T + H + 16, 60, 14), Qt.AlignCenter, f"{int(d[5:7])}/{int(d[8:10])}")
        # 리포트 발송일
        for r in self.reports:
            if r in self.days:
                x = X(self.days.index(r))
                p.setPen(QPen(q("muted"), 1, Qt.DashLine))
                p.drawLine(QPointF(x, T - 4), QPointF(x, T + H))
                p.setPen(q("muted"))
                p.drawText(QPointF(x + 4, T - 8), "리포트 발송")
        # 새 파일 눈금
        for row, src in enumerate(("sap", "purchase")):
            for d in self.arrivals.get(src, []):
                if d in self.days:
                    x = X(self.days.index(d))
                    p.fillRect(QRectF(x - 1, T + H + 3 + row * 6, 2, 5), self.colors[src])
        # 선
        for key, vals in self.series.items():
            path = QPainterPath()
            for i, v in enumerate(vals):
                (path.moveTo if i == 0 else path.lineTo)(QPointF(X(i), Y(v)))
            p.setPen(QPen(self.colors[key], 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            ex, ey = X(n - 1), Y(vals[-1])
            p.setPen(QPen(q("panel"), 2))
            p.setBrush(self.colors[key])
            p.drawEllipse(QPointF(ex, ey), 4.5, 4.5)
        # 끝 라벨 (겹치지 않게)
        labs = sorted(((Y(v[-1]), k) for k, v in self.series.items()))
        last_y = -99
        p.setFont(font(8.5, True))
        for y, k in labs:
            y = max(y, last_y + 15)
            p.setPen(q("ink"))
            p.drawText(QPointF(X(n - 1) + 10, y + 4), f"{self.names[k]} {self.series[k][-1]:,}")
            last_y = y
        # 마우스 위치 표시
        if self.hover_i is not None:
            i = self.hover_i
            x = X(i)
            p.setPen(QPen(q("muted"), 1))
            p.drawLine(QPointF(x, T), QPointF(x, T + H))
            for k, v in self.series.items():
                p.setPen(QPen(q("panel"), 2))
                p.setBrush(self.colors[k])
                p.drawEllipse(QPointF(x, Y(v[i])), 4, 4)

    def mouseMoveEvent(self, e):
        L, T, W, H = self._geom()
        if len(self.days) < 2:
            return
        i = round((e.position().x() - L) / W * (len(self.days) - 1))
        i = max(0, min(len(self.days) - 1, i))
        self.hover_i = i
        d = self.days[i]
        ev = []
        if d in self.reports:
            ev.append("리포트 발송")
        for src, nm in (("sap", "새 SAP 파일"), ("purchase", "새 구매 파일")):
            if d in self.arrivals.get(src, []):
                ev.append(nm)
        txt = f"<b>{d}</b><br>" + "<br>".join(
            f"<span style='color:{self.colors[k].name()}'>●</span> {self.names[k]} <b>{v[i]:,}</b>" for k, v in self.series.items())
        if ev:
            txt += f"<br><span style='color:{C['muted']}'>{' · '.join(ev)}</span>"
        QToolTip.showText(e.globalPosition().toPoint(), txt, self)
        self.update()

    def leaveEvent(self, _):
        self.hover_i = None
        self.update()


class Toast(QFrame):
    """창 아래쪽에 잠깐 떠 있는 알림."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self.lb = QLabel()
        self.lb.setWordWrap(True)
        self.lb.setTextFormat(Qt.RichText)
        lay.addWidget(self.lb)
        self.hide()
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_message(self, html: str, ms: int = 7000):
        self.lb.setText(html)
        w = min(560, self.parent().width() - 40)
        self.setFixedWidth(w)
        self.adjustSize()
        self.move((self.parent().width() - w) // 2, self.parent().height() - self.height() - 24)
        self.raise_()
        self.show()
        self.timer.start(ms)
