"""1단계: 대시보드 (호선별 설계 → SAP → 구매 흐름, 구역별 요약, 일별 추이)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..compare import CAT_LABELS, CATS, STAGE_LABELS, STAGES
from ..config import AREA_LABELS, AREAS
from .theme import AREA_COLORS, C, CAT_COLORS, q
from .widgets import Arrow, StackBar, TrendChart, card, label


def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


class CatButton(QPushButton):
    def __init__(self, text, n, color):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton{border:none;background:transparent;text-align:left;padding:3px 6px;border-radius:5px}"
            f"QPushButton:hover{{background:{C['soft']}}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        dot = label("■", color=color, size=9)
        lay.addWidget(dot)
        lay.addWidget(label(text, size=9.5), 1)
        lay.addWidget(label(f"{n:,}", bold=True, size=10, color=C["ink"] if n else C["muted"]))
        self.setMinimumHeight(26)


class Dashboard(QWidget):
    open_list = Signal(str, str, str, str)   # hull, stage, cat, area

    def __init__(self, parent=None):
        super().__init__(parent)
        self.res = None
        self.hist = None
        self.trend_hull = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        outer.addWidget(sc)
        body = QWidget()
        body.setObjectName("Root")
        sc.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(20, 16, 20, 24)
        self.lay.setSpacing(14)

    # ------------------------------------------------------------------
    def set_data(self, res, hist_data: dict):
        self.res, self.hist = res, hist_data
        self.render()

    def render(self):
        clear(self.lay)
        cmp = self.res.comparison
        total = sum(cmp.stage_stats(h, s)["dev"] for h in cmp.hulls() for s in STAGES)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label("전체", eyebrow=True))
        t = label(f"설계 Master 기준 차이 <span style='color:{C['bad'] if total else C['ok']}'>{total:,}</span>건"
                  f"  <span style='color:{C['muted']};font-size:10pt;font-weight:400'>목표 0건</span>", size=15, bold=True)
        t.setTextFormat(Qt.RichText)
        col.addWidget(t)
        head.addLayout(col, 1)
        legend = QHBoxLayout()
        for k, txt in (("ok", "설계와 일치"), ("missing", "빠짐"), ("qty", "수량"), ("code", "코드·사양"), ("extra", "설계에 없음")):
            legend.addWidget(label(f"<span style='color:{CAT_COLORS[k]}'>■</span> {txt}", muted=True, size=9))
        head.addLayout(legend)
        self.lay.addLayout(head)

        for hull in cmp.hulls():
            self.lay.addWidget(self._pipeline(hull))
        self.lay.addWidget(self._areas())
        self.lay.addWidget(self._trend())
        self.lay.addStretch(1)

    # ------------------------------------------------------------------
    def _pipeline(self, hull):
        cmp = self.res.comparison
        f = card()
        row = QHBoxLayout(f)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(8)
        hn = label(hull, size=17, bold=True)
        hn.setFixedWidth(70)
        row.addWidget(hn)
        base = card(soft=True)
        bl = QVBoxLayout(base)
        bl.setContentsMargins(12, 10, 12, 10)
        top = QHBoxLayout()
        top.addWidget(label("① 설계 Master", bold=True))
        top.addStretch(1)
        top.addWidget(label("기준", size=8.5, bold=True, color=C["accent"]))
        bl.addLayout(top)
        bl.addWidget(label(f"{cmp.stage_stats(hull, 'sap')['base']:,}", big=True))
        bl.addWidget(label("BOM 항목", muted=True, size=9))
        bl.addStretch(1)
        base.setMinimumWidth(170)
        base.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(base, 2)
        for s in STAGES:
            row.addWidget(Arrow())
            row.addWidget(self._stage(hull, s), 3)
        return f

    def _stage(self, hull, stage):
        cmp = self.res.comparison
        st = cmp.stage_stats(hull, stage)
        f = card()
        v = QVBoxLayout(f)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(STAGE_LABELS[stage], bold=True))
        top.addStretch(1)
        top.addWidget(label("SAP 반영률" if stage == "sap" else "구매 진행률", muted=True, size=8.5))
        v.addLayout(top)
        pct = st["pct"]
        color = C["ok"] if pct >= 99.95 else C["warn"] if pct >= 70 else C["bad"]
        line = QHBoxLayout()
        line.addWidget(label(f"{pct:.1f}%", size=19, bold=True, color=color))
        prev = self.hist.get("prev", {}).get((hull, stage))
        delta = ""
        if prev is not None:
            d = st["dev"] - prev
            delta = (f" · 어제 대비 <span style='color:{C['ok']}'><b>{-d:,} 해결</b></span>" if d < 0 else
                     f" · 어제 대비 <span style='color:{C['bad']}'><b>{d:,} 증가</b></span>" if d > 0 else " · 어제와 같음")
        info = label(f"차이 <b>{st['dev']:,}</b>건{delta}", muted=True, size=9)
        info.setTextFormat(Qt.RichText)
        line.addWidget(info, 1)
        v.addLayout(line)
        bar = StackBar()
        bar.set_segments([("ok", st["counts"]["ok"], q(CAT_COLORS["ok"]), "설계와 일치")] +
                         [(c, st["counts"][c], q(CAT_COLORS[c]), CAT_LABELS[stage][c]) for c in CATS])
        bar.clicked.connect(lambda c, h=hull, s=stage: self.open_list.emit(h, s, "" if c == "ok" else c, ""))
        v.addWidget(bar)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(0)
        for i, c in enumerate(CATS):
            b = CatButton(CAT_LABELS[stage][c], st["counts"][c], CAT_COLORS[c])
            b.clicked.connect(lambda _=False, h=hull, s=stage, cc=c: self.open_list.emit(h, s, cc, ""))
            g.addWidget(b, i // 2, i % 2)
        v.addLayout(g)
        if stage == "purchase":
            v.addWidget(label(f"ETA 지난 미입고 {st['late']:,}건", size=9, bold=True, color=C["warn"]))
        return f

    # ------------------------------------------------------------------
    def _areas(self):
        cmp = self.res.comparison
        f = QFrame()
        h = QHBoxLayout(f)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        for area in AREAS:
            rows = [r for r in cmp.rows if r.area == area and r.has_dev()]
            c = card()
            c.setCursor(Qt.PointingHandCursor)
            v = QVBoxLayout(c)
            v.setContentsMargins(14, 10, 14, 10)
            top = QHBoxLayout()
            top.addWidget(label(f"<span style='color:{AREA_COLORS[area]}'>●</span> {AREA_LABELS[area]} 담당", bold=True))
            top.addStretch(1)
            top.addWidget(label("S040 · S041 · S042", muted=True, size=8.5))
            v.addLayout(top)
            line = QHBoxLayout()
            line.addWidget(label(f"{len(rows):,}", size=17, bold=True))
            line.addWidget(label("follow-up 항목", muted=True, size=9), 1)
            v.addLayout(line)
            hi = sum(1 for r in rows if r.priority() == "높음")
            v.addWidget(label(f"SAP팀 {sum(1 for r in rows if r.has_dev('sap')):,} · 구매팀 "
                              f"{sum(1 for r in rows if r.has_dev('purchase')):,} · "
                              f"<span style='color:{C['bad']}'>높음 {hi:,}</span>", size=9, muted=True))
            c.mousePressEvent = lambda _e, a=area: self.open_list.emit("", "sap", "", a)
            h.addWidget(c, 1)
        return f

    # ------------------------------------------------------------------
    def _trend(self):
        f = card()
        h = QHBoxLayout(f)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(16)
        left = QVBoxLayout()
        top = QHBoxLayout()
        tl = QVBoxLayout()
        tl.addWidget(label("Deviation 일별 추이", eyebrow=True))
        tl.addWidget(label(f"<span style='color:{C['sap']}'>━</span> ① 설계 → ② SAP    "
                           f"<span style='color:{C['purchase']}'>━</span> ① 설계 → ③ 구매", muted=True, size=9))
        top.addLayout(tl, 1)
        grp = QButtonGroup(f)
        for hcode in [""] + self.res.comparison.hulls():
            b = QPushButton(hcode or "3척 합계")
            b.setProperty("chip", True)
            b.setCheckable(True)
            b.setChecked(hcode == self.trend_hull)
            b.clicked.connect(lambda _=False, x=hcode: self._set_trend(x))
            grp.addButton(b)
            top.addWidget(b)
        left.addLayout(top)
        self.chart = TrendChart()
        left.addWidget(self.chart, 1)
        left.addWidget(label("아래 눈금: 새 파일이 들어온 날 (파랑 SAP, 분홍 구매). 매일 비교 결과가 한 점씩 쌓입니다.", muted=True, size=8.5))
        h.addLayout(left, 1)
        side = QFrame()
        side.setFixedWidth(240)
        side.setStyleSheet(f"QFrame{{border-left:1px solid {C['line']}}} QLabel{{border:none}}")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 0, 0, 0)
        since = self.hist.get("since")
        sv.addWidget(label("지난 리포트 이후", eyebrow=True))
        if since:
            sv.addWidget(label(f"{since['day']} 발송", muted=True, size=9))
            for k, txt, col in (("resolved", "해결", C["ok"]), ("open", "아직 미해결", C["bad"]), ("new", "새로 생김", C["ink"])):
                r = QHBoxLayout()
                r.addWidget(label(txt))
                r.addStretch(1)
                r.addWidget(label(f"{since[k]:,}", size=15, bold=True, color=col))
                sv.addLayout(r)
            tot = since["resolved"] + since["open"]
            r = QHBoxLayout()
            r.addWidget(label("해결률", bold=True))
            r.addStretch(1)
            r.addWidget(label(f"{since['resolved'] / tot * 100:.0f}%" if tot else "–", size=15, bold=True))
            sv.addLayout(r)
        else:
            sv.addWidget(label("아직 보낸 리포트가 없습니다. 리포트를 만들면 그 뒤로 해결 현황이 여기에 쌓입니다.", muted=True, wrap=True))
        sv.addWidget(label("0건이 되어야 완전 해결입니다.", muted=True, size=8.5, wrap=True))
        sv.addStretch(1)
        h.addWidget(side)
        self._fill_chart()
        return f

    def _set_trend(self, hull):
        self.trend_hull = hull
        self._fill_chart()

    def _fill_chart(self):
        series = self.hist.get("series", {})
        key = self.trend_hull or ""
        data = series.get(key, {})
        days = [d for d, _ in data.get("sap", [])]
        self.chart.set_data(days, {s: [n for _, n in data.get(s, [])] for s in STAGES},
                            self.hist.get("reports", []), self.hist.get("arrivals", {}))
