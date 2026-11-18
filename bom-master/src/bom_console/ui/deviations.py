"""2단계: Deviation 목록 (단계·종류·구역·블록·검색으로 좁히기)."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QTableView, QVBoxLayout, QWidget)

from ..compare import BROKEN, BROKEN_ORDER, CAT_LABELS, CATS, STAGES
from ..config import AREA_LABELS, AREAS, UNASSIGNED
from .theme import C, CAT_COLORS
from .widgets import label

PRIO_COLORS = {"높음": C["bad"], "중간": C["warn"], "낮음": C["muted"]}
PRIO_RANK = {"높음": 0, "중간": 1, "낮음": 2}


def _q(x):
    return "" if x is None else f"{x.qty:g}"


class DevModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.stage = "sap"
        self.info = {}

    @property
    def headers(self):
        arrow = {"sap": "①→②", "purchase": "①→③", "link": "②→③"}[self.stage]
        h = ["우선순위", "구분", "호선", "블록", "구역", "품번", "품명", f"자재코드 {arrow}", f"수량 {arrow}"]
        if self.stage in ("purchase", "link"):
            h.append("구매 상태 / ETA")
        return h + ["끊긴 곳 → 연락", "리포트"]

    def set_rows(self, rows, stage, info):
        self.beginResetModel()
        self.rows, self.stage, self.info = rows, stage, info
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self.headers[s]
        return None

    def _cells(self, r):
        a, o = (r.sap, r.purchase) if self.stage == "link" else (r.design, r.sap if self.stage == "sap" else r.purchase)
        ref = r.ref
        cat = r.cat.get(self.stage)
        code = (f"{a.code} → {o.code}" if a.code != o.code else a.code) if a and o else \
               (f"{a.code} → 없음" if a else f"{'SAP' if self.stage == 'link' else '설계'} 없음 → {o.code}")
        qty = (f"{_q(a)} → {_q(o)}" if a.qty != o.qty else _q(a)) if a and o else (f"{_q(a)} → –" if a else f"– → {_q(o)}")
        first, cnt = self.info.get((r.key, self.stage), ("", 0))
        cells = [r.priority(), CAT_LABELS[self.stage].get(cat, ""), r.hull, r.block, r.area, ref.item_no or "",
                 f"{ref.name} {ref.spec}".strip(), code, qty]
        if self.stage in ("purchase", "link"):
            cells.append(f"{r.purchase.status} · {r.purchase.eta}" if r.purchase else "–")
        b = BROKEN[r.broken()]
        cells.append(f"{b[0]} → {b[2]}" if b[2] else b[0])
        cells.append(f"{cnt}회" if cnt else "신규")
        return cells

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        if role == Qt.DisplayRole:
            return self._cells(r)[c]
        if role == Qt.ForegroundRole:
            if c == 0:
                return QBrush(QColor(PRIO_COLORS[r.priority()]))
            if c == 1:
                return QBrush(QColor(CAT_COLORS.get(r.cat.get(self.stage), C["ink"])))
            if c in (7, 8) and r.cat.get(self.stage) in ("missing", "extra", "qty" if c == 8 else "code"):
                return QBrush(QColor(C["bad"]))
            if self.stage in ("purchase", "link") and c == 9 and r.late:
                return QBrush(QColor(C["bad"]))
            if c == self.columnCount() - 1 and self.info.get((r.key, self.stage), ("", 0))[1] >= 2:
                return QBrush(QColor(C["bad"]))
        if role == Qt.FontRole and c in (0, 1):
            from .theme import font
            return font(9.5, True)
        if role == Qt.UserRole:
            return r
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        self.layoutAboutToBeChanged.emit()
        if column == 0:
            key = lambda r: PRIO_RANK[r.priority()]
        elif column == self.columnCount() - 1:
            key = lambda r: self.info.get((r.key, self.stage), ("", 0))[1]
        else:
            key = lambda r: str(self._cells(r)[column])
        self.rows.sort(key=key, reverse=order == Qt.DescendingOrder)
        self.layoutChanged.emit()


class Deviations(QWidget):
    open_detail = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cmp = None
        self.info = {}
        self.f = {"hull": "", "stage": "sap", "cat": "", "area": "", "block": "", "q": "", "broken": ""}
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 14, 20, 16)
        v.setSpacing(10)

        top = QHBoxLayout()
        self.stage_btns = {}
        sg = QButtonGroup(self)
        for s, txt in (("sap", "① 설계 → ② SAP"), ("link", "② SAP → ③ 구매"), ("purchase", "① 설계 → ③ 구매")):
            b = QPushButton(txt)
            b.setProperty("chip", True)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, x=s: self.set_filter(stage=x, cat="", block=""))
            sg.addButton(b)
            self.stage_btns[s] = b
            top.addWidget(b)
        top.addSpacing(16)
        self.hull_cb = QComboBox()
        self.hull_cb.currentIndexChanged.connect(lambda _: self.set_filter(hull=self.hull_cb.currentData() or "", block=""))
        top.addWidget(label("호선", muted=True))
        top.addWidget(self.hull_cb)
        self.area_cb = QComboBox()
        self.area_cb.addItem("전체 구역", "")
        for a in AREAS + (UNASSIGNED,):
            self.area_cb.addItem(AREA_LABELS.get(a, a), a)
        self.area_cb.currentIndexChanged.connect(lambda _: self.set_filter(area=self.area_cb.currentData() or "", block=""))
        top.addWidget(label("담당 구역", muted=True))
        top.addWidget(self.area_cb)
        self.broken_cb = QComboBox()
        self.broken_cb.addItem("끊긴 곳 전체", "")
        for k in BROKEN_ORDER:
            self.broken_cb.addItem(BROKEN[k][0], k)
        self.broken_cb.currentIndexChanged.connect(lambda _: self.set_filter(broken=self.broken_cb.currentData() or "",
                                                                             block=""))
        top.addWidget(label("끊긴 곳", muted=True))
        top.addWidget(self.broken_cb)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("품번, 품명, 자재코드 검색")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        self._st = QTimer(self, singleShot=True, interval=250, timeout=lambda: self.set_filter(q=self.search.text()))
        self.search.textChanged.connect(lambda _: self._st.start())
        top.addWidget(self.search)
        v.addLayout(top)

        self.chips_lay = QHBoxLayout()
        self.chips_lay.setSpacing(6)
        v.addLayout(self.chips_lay)

        body = QHBoxLayout()
        body.setSpacing(12)
        left = QVBoxLayout()
        left.addWidget(label("블록 (차이 많은 순)", eyebrow=True))
        self.blocks = QListWidget()
        self.blocks.setFixedWidth(220)
        self.blocks.itemClicked.connect(lambda it: self.set_filter(block=it.data(Qt.UserRole)))
        left.addWidget(self.blocks)
        body.addLayout(left)
        right = QVBoxLayout()
        self.count_lb = label("", muted=True)
        right.addWidget(self.count_lb)
        self.table = QTableView()
        self.model = DevModel()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.doubleClicked.connect(lambda i: self.open_detail.emit(self.model.rows[i.row()]))
        self.table.activated.connect(lambda i: self.open_detail.emit(self.model.rows[i.row()]))
        right.addWidget(self.table, 1)
        right.addWidget(label("행을 두 번 누르면 세 파일 값을 나란히 비교하는 상세 화면이 열립니다.", muted=True, size=8.5))
        body.addLayout(right, 1)
        v.addLayout(body, 1)

    def set_data(self, cmp, info):
        self.cmp, self.info = cmp, info
        self.hull_cb.blockSignals(True)
        self.hull_cb.clear()
        self.hull_cb.addItem("전체 호선", "")
        for h in cmp.hulls():
            self.hull_cb.addItem(h, h)
        self.hull_cb.blockSignals(False)
        self.apply()

    def set_filter(self, **kw):
        self.f.update(kw)
        self.apply()

    def open_with(self, hull, stage, cat, area):
        broken = ""
        if cat.startswith("broken:"):
            broken, cat = cat[7:], ""
        self.f.update(hull=hull, stage=stage, cat=cat, area=area, block="", q="", broken=broken)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.apply()

    def _sync_controls(self):
        f = self.f
        self.stage_btns[f["stage"]].setChecked(True)
        for cb, val in ((self.hull_cb, f["hull"]), (self.area_cb, f["area"]), (self.broken_cb, f["broken"])):
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(val)))
            cb.blockSignals(False)

    def apply(self):
        if not self.cmp:
            return
        self._sync_controls()
        f = self.f
        st = f["stage"]
        base = [r for r in self.cmp.rows if r.cat.get(st) not in (None, "ok")
                and (not f["hull"] or r.hull == f["hull"]) and (not f["area"] or r.area == f["area"])
                and (not f["broken"] or r.broken() == f["broken"])]
        # 종류 칩
        while self.chips_lay.count():
            w = self.chips_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        counts = {c: sum(1 for r in base if r.cat[st] == c) for c in CATS}
        grp = QButtonGroup(self)
        for c, txt in [("", f"전체  {len(base):,}")] + [(c, f"{CAT_LABELS[st][c]}  {counts[c]:,}") for c in CATS]:
            b = QPushButton(("■ " if c else "") + txt)
            b.setProperty("chip", True)
            b.setCheckable(True)
            b.setChecked(f["cat"] == c)
            if c:
                b.setStyleSheet(f"QPushButton:!checked{{color:{CAT_COLORS[c]}}}")
            b.clicked.connect(lambda _=False, x=c: self.set_filter(cat=x, block=""))
            grp.addButton(b)
            self.chips_lay.addWidget(b)
        self.chips_lay.addStretch(1)
        rows = [r for r in base if not f["cat"] or r.cat[st] == f["cat"]]
        # 블록 목록
        bc: dict[str, int] = {}
        for r in rows:
            bc[r.block] = bc.get(r.block, 0) + 1
        self.blocks.clear()
        it = QListWidgetItem(f"전체 블록    {len(rows):,}")
        it.setData(Qt.UserRole, "")
        self.blocks.addItem(it)
        for b, n in sorted(bc.items(), key=lambda x: -x[1]):
            it = QListWidgetItem(f"{b or '(블록 없음)'}    {n:,}")
            it.setData(Qt.UserRole, b)
            self.blocks.addItem(it)
            if b == f["block"]:
                it.setSelected(True)
        if f["block"]:
            rows = [r for r in rows if r.block == f["block"]]
        if f["q"]:
            qq = f["q"].lower()
            rows = [r for r in rows if qq in " ".join(filter(None, [r.ref.item_no, r.ref.code, r.ref.name, r.ref.spec,
                                                                    r.sap.code if r.sap else "", r.purchase.code if r.purchase else ""])).lower()]
        rows.sort(key=lambda r: (PRIO_RANK[r.priority()], r.hull, r.block))
        self.model.set_rows(rows, st, self.info)
        hh = self.table.horizontalHeader()
        for i in range(self.model.columnCount()):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        where = " · ".join(filter(None, [f["hull"] or "3척", AREA_LABELS.get(f["area"], f["area"]) if f["area"] else "",
                                          f"Block {f['block']}" if f["block"] else ""]))
        self.count_lb.setText(f"{where} · {len(rows):,}건")

    def crumb(self):
        st = {"sap": "① 설계 → ② SAP", "purchase": "① 설계 → ③ 구매", "link": "② SAP → ③ 구매"}[self.f["stage"]]
        return f"{self.f['hull'] or '3척'} · {st}"
