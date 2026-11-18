"""Reusable widgets: table model, status-chip delegate, flow layout, KPI card, BOM tile."""
import re
from collections import Counter

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, QRect, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
                               QTableView, QToolButton, QVBoxLayout)

from ..analyzer import ROLE_TITLE
from . import theme


class DictTableModel(QAbstractTableModel):
    """Rows are dicts; columns are (field, title). `chip_cols` render as colored pills."""

    def __init__(self, columns, rows=None, chip_cols=(), sev_field=None, parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.rows = list(rows or [])
        self.chip_cols = set(chip_cols)
        self.sev_field = sev_field

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns[section][1]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        field = self.columns[index.column()][0]
        val = row.get(field, "")
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return "" if val is None else str(val)
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:      # sort key
            try:
                return float(val)
            except (TypeError, ValueError):
                return str(val or "")
        if role == Qt.UserRole + 2:      # is chip column
            return field in self.chip_cols
        if role == Qt.UserRole + 3:      # explicit color kind (OK / WARN / ERROR / NONE)
            return row.get("_kind:" + field)
        if row.get("_deleted"):          # deleted BOM line (Mode = D): red strike-through
            if role == Qt.ForegroundRole:
                return QColor(theme.ERR)
            if role == Qt.FontRole:
                f = QFont()
                f.setStrikeOut(True)
                return f
        return None


class FilterProxy(QSortFilterProxyModel):
    """Text search across all columns + row predicate + Excel-style per-column value filters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.pred = None
        self.col_filters = {}          # column index -> set of allowed display values
        self.setSortRole(Qt.UserRole + 1)

    def set_text(self, t):
        self.text = t.lower().strip()
        self.invalidateFilter()

    def set_pred(self, pred):
        self.pred = pred
        self.invalidateFilter()

    def set_col_filter(self, col, values):
        if values is None:
            self.col_filters.pop(col, None)
        else:
            self.col_filters[col] = set(values)
        self.invalidateFilter()

    def clear_col_filters(self):
        self.col_filters.clear()
        self.invalidateFilter()

    @staticmethod
    def cell(row, field):
        v = row.get(field, "")
        return "" if v is None else str(v)

    def _accepts(self, row, skip_col=None):
        if self.pred and not self.pred(row):
            return False
        cols = self.sourceModel().columns
        for c, allowed in self.col_filters.items():
            if c != skip_col and self.cell(row, cols[c][0]) not in allowed:
                return False
        if self.text:
            hay = " ".join(str(v) for k, v in row.items() if not k.startswith("_")).lower()
            return all(t in hay for t in self.text.split())
        return True

    def filterAcceptsRow(self, r, parent):
        return self._accepts(self.sourceModel().rows[r])

    def distinct_values(self, col):
        """Values of `col` among rows that pass every other filter (like Excel), with counts."""
        field = self.sourceModel().columns[col][0]
        cnt = Counter()
        for row in self.sourceModel().rows:
            if self._accepts(row, skip_col=col):
                cnt[self.cell(row, field)] += 1
        return cnt


class FilterHeader(QHeaderView):
    """Header with an Excel-like filter button at the right edge of every column."""
    filterRequested = Signal(int)
    BTN = 18

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setSectionsClickable(True)
        self.active = set()

    def _btn_rect(self, logical):
        x = self.sectionViewportPosition(logical)
        w = self.sectionSize(logical)
        return QRect(x + w - self.BTN - 2, (self.height() - self.BTN) // 2, self.BTN, self.BTN)

    def paintSection(self, p, rect, logical):
        p.save()
        super().paintSection(p, rect, logical)
        p.restore()
        r = QRect(rect.right() - self.BTN - 1, rect.center().y() - self.BTN // 2, self.BTN, self.BTN)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        on = logical in self.active
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
        p.setPen(QColor("white" if on else theme.MUTED))
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, "▾")
        p.restore()

    def mousePressEvent(self, e):
        logical = self.logicalIndexAt(e.position().toPoint())
        if logical >= 0 and self._btn_rect(logical).contains(e.position().toPoint()):
            self.filterRequested.emit(logical)
            return
        super().mousePressEvent(e)


class ColumnFilterPopup(QFrame):
    """Search box + checkable value list, like Excel's AutoFilter drop-down."""
    applied = Signal(object)     # set of values, or None to clear

    def __init__(self, title, counts, current, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("card")
        self.setStyleSheet(f"QFrame#card{{background:{theme.SURFACE};border:1px solid {theme.LINE};"
                           f"border-radius:8px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        lay.addWidget(QLabel(f"<b>{title}</b>"))
        sort_btns = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search values…")
        lay.addWidget(self.search)
        self.all_cb = QCheckBox("(Select all)")
        lay.addWidget(self.all_cb)
        self.list = QListWidget()
        self.list.setMinimumSize(300, 280)
        self.list.setUniformItemSizes(True)
        vals = sorted(counts.items(), key=lambda kv: _natural(kv[0]))
        for v, n in vals[:5000]:
            it = QListWidgetItem(f"{v if v != '' else '(Blanks)'}    ({n:,})")
            it.setData(Qt.UserRole, v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if current is None or v in current else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        if len(vals) > 5000:
            lay.addWidget(QLabel(f"Showing first 5,000 of {len(vals):,} values — use the search box."))
        b_clear = QPushButton("Clear filter")
        b_ok = QPushButton("OK")
        b_ok.setObjectName("primary")
        sort_btns.addWidget(b_clear)
        sort_btns.addStretch(1)
        sort_btns.addWidget(b_ok)
        lay.addLayout(sort_btns)
        self._sync_all()
        self.search.textChanged.connect(self._search)
        self.all_cb.clicked.connect(self._toggle_all)
        self.list.itemChanged.connect(lambda _: self._sync_all())
        b_clear.clicked.connect(lambda: (self.applied.emit(None), self.close()))
        b_ok.clicked.connect(self._ok)
        self.search.returnPressed.connect(self._ok)
        self.search.setFocus()

    def _items(self, visible_only=False):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not visible_only or not it.isHidden():
                yield it

    def _search(self, t):
        t = t.lower().strip()
        for it in self._items():
            it.setHidden(bool(t) and t not in it.text().lower())
        if t:   # like Excel: searching selects just the matches
            self.list.blockSignals(True)
            for it in self._items():
                it.setCheckState(Qt.Unchecked if it.isHidden() else Qt.Checked)
            self.list.blockSignals(False)
        self._sync_all()

    def _toggle_all(self):
        state = Qt.Checked if self.all_cb.isChecked() else Qt.Unchecked
        self.list.blockSignals(True)
        for it in self._items(visible_only=True):
            it.setCheckState(state)
        self.list.blockSignals(False)

    def _sync_all(self):
        vis = list(self._items(visible_only=True))
        self.all_cb.setChecked(bool(vis) and all(it.checkState() == Qt.Checked for it in vis))

    def _ok(self):
        items = list(self._items())
        chosen = {it.data(Qt.UserRole) for it in items if it.checkState() == Qt.Checked}
        self.applied.emit(None if len(chosen) == len(items) else chosen)
        self.close()


def _natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]

    def lessThan(self, a, b):
        va, vb = a.data(Qt.UserRole + 1), b.data(Qt.UserRole + 1)
        if type(va) is not type(vb):
            return str(va) < str(vb)
        return va < vb


class ChipDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, opt, index):
        if not index.data(Qt.UserRole + 2):
            return super().paint(p, opt, index)
        text = index.data(Qt.DisplayRole) or ""
        if opt.state & QStyle.State_Selected:
            p.fillRect(opt.rect, opt.palette.highlight())
        kind = index.data(Qt.UserRole + 3)
        if not text or text in ("-", "—") or kind == "NONE":
            p.setPen(QColor(theme.NONE))
            p.drawText(opt.rect.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text or "")
            return
        if kind:
            ink, soft = theme.KIND_COLORS.get(kind, (theme.MUTED, theme.NONE_SOFT))
        else:
            ink, soft = theme.STATUS_COLORS.get(text.split(" (")[0], (theme.MUTED, theme.NONE_SOFT))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(opt.font)
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = min(fm.horizontalAdvance(text) + 16, opt.rect.width() - 8)
        r = QRect(opt.rect.left() + 6, opt.rect.center().y() - 10, w, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(soft))
        p.drawRoundedRect(r, 10, 10)
        p.setPen(QColor(ink))
        p.drawText(r, Qt.AlignCenter, fm.elidedText(text, Qt.ElideRight, w - 10))
        p.restore()


class DataTable(QTableView):
    def __init__(self, model, parent=None, stretch_last=True):
        super().__init__(parent)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(model)
        self.on_filter = None          # page callback to refresh its row count
        self.fheader = FilterHeader(self)
        self.setHorizontalHeader(self.fheader)
        self.fheader.filterRequested.connect(self._open_filter)
        self.fheader.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fheader.customContextMenuRequested.connect(lambda _: self.clear_filters())
        self.setModel(self.proxy)
        model.modelReset.connect(self._drop_stale_filters)
        self.setItemDelegate(ChipDelegate(self))
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.ExtendedSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setStretchLastSection(stretch_last)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.horizontalHeader().setHighlightSections(False)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QTableView.ScrollPerPixel)
        self.sortByColumn(-1, Qt.AscendingOrder)   # keep source order (already sorted) until a header is clicked

    def _open_filter(self, col):
        title = self.proxy.sourceModel().columns[col][1]
        pop = ColumnFilterPopup(title, self.proxy.distinct_values(col), self.proxy.col_filters.get(col), self)
        pop.applied.connect(lambda vals, c=col: self.set_col_filter(c, vals))
        x = self.fheader.sectionViewportPosition(col)
        pop.move(self.fheader.mapToGlobal(QPoint(max(0, x), self.fheader.height())))
        pop.show()
        self._popup = pop

    def set_col_filter(self, col, vals):
        self.proxy.set_col_filter(col, vals)
        self.fheader.active = set(self.proxy.col_filters)
        self.fheader.viewport().update()
        if self.on_filter:
            self.on_filter()

    def clear_filters(self):
        self.proxy.clear_col_filters()
        self.fheader.active = set()
        self.fheader.viewport().update()
        if self.on_filter:
            self.on_filter()

    def _drop_stale_filters(self):
        # keep column filters across data refreshes (same columns), just repaint the markers
        self.fheader.active = set(self.proxy.col_filters)
        self.fheader.viewport().update()

    def selected_rows(self):
        out = []
        for idx in self.selectionModel().selectedRows():
            out.append(self.proxy.data(idx, Qt.UserRole))
        return out

    def row_at(self, proxy_index):
        return self.proxy.data(proxy_index, Qt.UserRole)

    def set_widths(self, widths):
        for i, w in enumerate(widths):
            if w:
                self.setColumnWidth(i, w)


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self.items:
            hint = it.sizeHint()
            nx = x + hint.width() + sp
            if nx - sp > rect.right() and line_h > 0:
                x, y = rect.x(), y + line_h + sp
                nx = x + hint.width() + sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class KpiCard(QFrame):
    clicked = Signal()

    def __init__(self, label, color=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.value = QLabel("–")
        self.value.setObjectName("kpiValue")
        if color:
            self.value.setStyleSheet(f"color:{color}")
        self.label = QLabel(label)
        self.label.setObjectName("kpiLabel")
        self.sub = QLabel("")
        self.sub.setObjectName("kpiLabel")
        self.label.setWordWrap(True)
        self.sub.setWordWrap(True)     # cards narrow down on small screens instead of widening the window
        lay.addWidget(self.value)
        lay.addWidget(self.label)
        lay.addWidget(self.sub)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value, sub=""):
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))

    def mousePressEvent(self, e):
        self.clicked.emit()


class FolderCard(QFrame):
    """Health of one source folder: share of BOMs OK and a stacked OK / warn / error / no-file bar."""
    clicked = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(92)
        self.title = title
        self.counts = (0, 0, 0, 0)

    def set_counts(self, ok, warn, err, none):
        self.counts = (ok, warn, err, none)
        self.setToolTip(f"{self.title}: {ok} OK · {warn} to check · {err} need correction · {none} BOMs without "
                        f"a file here")
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        super().paintEvent(e)
        ok, warn, err, none = self.counts
        have = ok + warn + err
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(QRect(16, 10, self.width() - 32, 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        status, ink = ("No files", theme.NONE) if not have else \
            (("All OK", theme.OK) if not (warn or err) else
             (f"{err} need correction" if err else f"{warn} to check", theme.ERR if err else theme.WARN))
        p.setPen(QColor(ink))
        p.drawText(QRect(16, 10, self.width() - 32, 20), Qt.AlignRight | Qt.AlignVCenter, status)
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRect(16, 34, self.width() - 32, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{ok} OK   ·   {warn} check   ·   {err} error   ·   {none} no file")
        bar = QRect(16, 60, self.width() - 32, 12)
        total = max(1, ok + warn + err + none)
        x = bar.left()
        p.setPen(Qt.NoPen)
        for n, col in ((ok, theme.OK), (warn, theme.WARN), (err, theme.ERR), (none, theme.NONE_SOFT)):
            w = round(bar.width() * n / total)
            if w:
                p.setBrush(QColor(col))
                p.drawRect(QRect(x, bar.top(), w, bar.height()))
                x += w
        p.end()


class BomTile(QToolButton):
    """One BOM in the block map: colored by worst issue severity."""

    FOLDERS = (("PROD", "P"), ("WP", "W"), ("DCN", "D"), ("ECN", "E"))

    def __init__(self, ks, parent=None):
        super().__init__(parent)
        self.ks = ks
        self.folders = [(letter, *ks.folder(role)) for role, letter in self.FOLDERS]
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(112, 70))
        self.hover = False
        rev = f"R{ks.prod_rev}" if ks.prod_rev is not None else "—"
        tips = [f"<b>{ks.key}</b>"]
        for (role, _), (letter, text, kind) in zip(self.FOLDERS, self.folders):
            ink, _s = theme.KIND_COLORS[kind]
            tips.append(f"<span style='color:{ink}'>■</span> {ROLE_TITLE[role]}: {text}")
        for i in ks.issues[:6]:
            tips.append(f"• [{i.sev}] {i.title}")
        if len(ks.issues) > 6:
            tips.append(f"… +{len(ks.issues) - 6} more")
        self.setToolTip("<br>".join(tips))
        self.rev = rev

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        ks = self.ks
        ink, soft = theme.SEV_COLORS[ks.worst]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QColor(ink) if self.hover else Qt.NoPen)
        p.setBrush(QColor(soft))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ink))
        p.drawRoundedRect(QRect(r.left(), r.top(), 4, r.height()), 2, 2)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(QRect(10, 4, r.width() - 12, 16), Qt.AlignLeft | Qt.AlignVCenter, ks.block)
        f.setBold(False)
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRect(10, 20, r.width() - 12, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{ks.phase}-{ks.disc}   {self.rev}")
        # four folder status bars: P W D E
        w = (r.width() - 14 - 3 * 3) / 4
        f.setBold(True)
        f.setPointSizeF(7)
        p.setFont(f)
        for n, (letter, _t, kind) in enumerate(self.folders):
            k_ink, k_soft = theme.KIND_COLORS[kind]
            box = QRect(int(10 + n * (w + 3)), 40, int(w), 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(k_ink if kind != "NONE" else theme.SURFACE))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor("white" if kind != "NONE" else theme.NONE))
            p.drawText(box, Qt.AlignCenter, letter)
        p.end()


class CheckTile(QToolButton):
    """One BOM in the Master BOM check map. Bars: B = BOM in both, R = revision, L = lines, V = values."""

    BARS = (("BOM", "B", "BOM in Master and folders"), ("REV", "R", "Revision"),
            ("LINES", "L", "Lines (missing / extra)"), ("VALUES", "V", "Values (Qty, Unit, Description …)"))

    def __init__(self, kc, parent=None):
        super().__init__(parent)
        self.kc = kc
        self.bars = [(letter, *kc.bar(which)) for which, letter, _ in self.BARS]
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(112, 70))
        self.hover = False
        tips = [f"<b>{kc.key}</b> — {kc.status}"]
        for (_w, _l, title), (letter, text, kind) in zip(self.BARS, self.bars):
            ink, _s = theme.KIND_COLORS[kind]
            tips.append(f"<span style='color:{ink}'>■</span> <b>{letter}</b> {title}: {text}")
        if kc.basis and kc.basis != "Prod DWG":
            tips.append(f"Checked against {kc.basis}")
        tips.append("Click to list the differences")
        self.setToolTip("<br>".join(tips))
        if kc.folder_rev is not None:
            self.rev = f"R{kc.folder_rev}"
        else:
            self.rev = "Master R" + "/".join(map(str, kc.master_revs)) if kc.master_revs else "—"

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        kc = self.kc
        ink, soft = theme.SEV_COLORS[kc.worst if kc.worst != "INFO" else None]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QColor(ink) if self.hover else Qt.NoPen)
        p.setBrush(QColor(soft))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ink))
        p.drawRoundedRect(QRect(r.left(), r.top(), 4, r.height()), 2, 2)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(QRect(10, 4, r.width() - 12, 16), Qt.AlignLeft | Qt.AlignVCenter, kc.block)
        f.setBold(False)
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRect(10, 20, r.width() - 12, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{kc.phase}-{kc.disc}   {self.rev}")
        w = (r.width() - 14 - 3 * 3) / 4
        f.setBold(True)
        f.setPointSizeF(7)
        p.setFont(f)
        for n, (letter, _t, kind) in enumerate(self.bars):
            k_ink, _k_soft = theme.KIND_COLORS[kind]
            box = QRect(int(10 + n * (w + 3)), 40, int(w), 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(k_ink if kind != "NONE" else theme.SURFACE))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor("white" if kind != "NONE" else theme.NONE))
            p.drawText(box, Qt.AlignCenter, letter)
        p.end()


def h_line():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{theme.LINE}")
    return f


def label(text, obj=None, wrap=False):
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0), stretch_at=None):
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if i == stretch_at:
            lay.addStretch(1)
        if isinstance(w, QLayout):
            lay.addLayout(w)
        elif w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    return lay
