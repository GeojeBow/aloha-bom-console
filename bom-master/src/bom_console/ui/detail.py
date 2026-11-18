"""3단계: 항목 상세 (세 파일 값을 나란히, 설계 기준과 다른 칸은 빨간색)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..compare import CAT_LABELS, STAGES, request_text
from ..config import AREA_LABELS
from .theme import C, CAT_COLORS, font
from .widgets import card, label

FIELDS = [("code", "자재코드"), ("item_no", "품번"), ("name", "품명"), ("spec", "사양"), ("qty", "수량"),
          ("unit", "단위"), ("block", "블록"), ("drawing", "도면번호"), ("sheet", "시트 / 행")]


class Detail(QWidget):
    back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = None
        self.info = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 14, 20, 16)
        v.setSpacing(12)
        self.title = label("", size=14, bold=True)
        self.sub = label("", muted=True)
        hv = QHBoxLayout()
        hv.addWidget(self.title)
        hv.addWidget(self.sub, 1)
        v.addLayout(hv)
        body = QHBoxLayout()
        body.setSpacing(14)
        self.table = QTableWidget(len(FIELDS) + 1, 4)
        self.table.setHorizontalHeaderLabels(["항목", "① 설계 Master (기준)", "② SAP", "③ 구매"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(34)
        body.addWidget(self.table, 3)
        side = card()
        side.setFixedWidth(340)
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(16, 14, 16, 14)
        self.side.setSpacing(8)
        body.addWidget(side)
        v.addLayout(body, 1)

    def set_row(self, row, info):
        self.row, self.info = row, info
        r = row
        ref = r.ref
        self.title.setText(ref.item_no or ref.code)
        self.sub.setText(f"   {ref.name} · {r.hull} · Block {r.block} · {AREA_LABELS.get(r.area, r.area)}")
        srcs = [r.design, r.sap, r.purchase]
        for i, (k, lab) in enumerate(FIELDS):
            self.table.setItem(i, 0, self._item(lab, muted=True))
            for j, o in enumerate(srcs, start=1):
                if o is None:
                    it = self._item("없음")
                    it.setBackground(QBrush(QColor(C["bad_soft"])))
                    it.setForeground(QBrush(QColor(C["bad"])))
                    it.setFont(font(10, True))
                else:
                    val = f"{o.sheet} / {o.row}행" if k == "sheet" else (f"{o.qty:g}" if k == "qty" else getattr(o, k))
                    it = self._item(str(val))
                    if j == 1:
                        it.setBackground(QBrush(QColor(C["accent_soft"])))
                    elif r.design and k in ("code", "qty", "unit") and self._differs(r.design, o, k):
                        it.setBackground(QBrush(QColor(C["bad_soft"])))
                        it.setForeground(QBrush(QColor(C["bad"])))
                        it.setFont(font(10, True))
                self.table.setItem(i, j, it)
        last = len(FIELDS)
        self.table.setItem(last, 0, self._item("구매 상태", muted=True))
        self.table.setItem(last, 1, self._item("–", muted=True))
        self.table.setItem(last, 2, self._item("–", muted=True))
        p = r.purchase
        it = self._item(f"{p.status} · ETA {p.eta}" + (f" · PO {p.po}" if p.po else "") if p else "–")
        if r.late:
            it.setForeground(QBrush(QColor(C["bad"])))
        self.table.setItem(last, 3, it)
        self._side()

    @staticmethod
    def _differs(a, o, k):
        if k == "qty":
            return abs(a.qty - o.qty) > 1e-6
        va, vo = str(getattr(a, k)).lstrip("0").upper(), str(getattr(o, k)).lstrip("0").upper()
        return bool(va and vo and va != vo)

    @staticmethod
    def _item(text, muted=False):
        it = QTableWidgetItem(text)
        if muted:
            it.setForeground(QBrush(QColor(C["muted"])))
        it.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        return it

    def _side(self):
        lay = self.side
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        r = self.row
        lay.addWidget(label("리포트에 들어가는 follow-up 요청", eyebrow=True))
        lay.addWidget(label(f"받는 사람: {AREA_LABELS.get(r.area, r.area)} 담당 엔지니어", bold=True))
        any_req = False
        for s, team in (("sap", "SAP팀에"), ("purchase", "구매팀에")):
            t = request_text(r, s)
            if not t:
                continue
            any_req = True
            cat = r.cat.get(s)
            box = QFrame()
            box.setStyleSheet(f"QFrame{{border-left:3px solid {CAT_COLORS.get(cat, C['line'])};background:{C['soft']};border-radius:4px}}"
                              "QLabel{background:transparent;border:none}")
            bv = QVBoxLayout(box)
            bv.setContentsMargins(10, 8, 10, 8)
            bv.addWidget(label(f"{team} · {CAT_LABELS[s][cat]}", bold=True, size=9, color=CAT_COLORS.get(cat)))
            bv.addWidget(label(t, wrap=True))
            first, cnt = self.info.get((r.key, s), ("", 0))
            if first:
                bv.addWidget(label(f"최초 발견 {first} · 리포트 {cnt}회" + (" · 반복 미해결" if cnt >= 2 else ""),
                                   size=8.5, color=C["bad"] if cnt >= 2 else C["muted"]))
            lay.addWidget(box)
        if not any_req:
            lay.addWidget(label("설계 Master와 SAP·구매가 모두 일치합니다.", muted=True, wrap=True))
        lay.addWidget(label(f"우선순위: {r.priority()}", bold=True,
                            color={"높음": C["bad"], "중간": C["warn"]}.get(r.priority(), C["muted"])))
        lay.addStretch(1)
        b = QPushButton("← 목록으로")
        b.clicked.connect(self.back.emit)
        lay.addWidget(b)
