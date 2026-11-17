"""BOM detail (revision timeline + visual comparison), copy-to-fix and acknowledge dialogs."""
import os
from collections import Counter

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QStyle, QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..analyzer import ROLE_TITLE
from ..analyzer import _hash as std_hash
from ..analyzer import diff_rows
from ..fixer import can_copy
from ..scanner import FIELD_IDS, FIELD_TITLE
from . import theme
from .widgets import DataTable, DictTableModel, hbox, label

ROLES = [("PROD", "16 Prod DWG"), ("WP", "17 Work Packages"), ("DCN", "03 DCN"), ("ECN", "04 ECN")]
ROLE_ORDER = {"PROD": 0, "WP": 1, "DCN": 2, "ECN": 3}
DIFF_CODES = ("SAME_NAME_DIFF", "SAME_REV_DIFF", "WP_CONTENT_DIFF", "CN_CONTENT_DIFF", "WP_OUTDATED", "WP_AHEAD")
A_INK, B_INK = theme.ACCENT, "#7A4FD0"
A_SOFT, B_SOFT = "#DCE7FD", "#EEE6FB"


def open_path(path):
    try:
        os.startfile(path)
    except OSError:
        pass


def open_folder(path):
    try:
        os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
    except OSError:
        pass


def short(f):
    """Short name of a file for comparison labels: 'WP R2 · Arch'."""
    role = {"PROD": "Prod DWG", "WP": "WP", "DCN": "DCN", "ECN": "ECN"}[f.role]
    loc = {"ACTIVE": "", "ARCHIVE": " · Arch", "STAGING": " · WIP", "COMMENT": " · review"}[f.loc]
    sfx = f" · {f.suffix}" if f.suffix else ""
    return f"{role} R{f.rev}{loc}{sfx}"


def _size_to_screen(w, share):
    scr = QGuiApplication.primaryScreen().availableGeometry()
    w.resize(int(scr.width() * share), int(scr.height() * share))


def content_groups(files):
    """Assign letters A, B, C… to distinct contents within each revision."""
    groups, by_rev = {}, {}
    for f in files:
        if f.loc == "COMMENT" or f.error or not f.content_hash:
            continue
        h = std_hash(f, frozenset())
        hs = by_rev.setdefault(f.rev, [])
        if h not in hs:
            hs.append(h)
        groups[id(f)] = (hs.index(h), len(hs))
    return groups, {rev: len(h) for rev, h in by_rev.items()}


def _blank(r):
    return r is None or not any(r.get(f, "") for f in FIELD_IDS)


def diff_stats(a, b):
    d = [x for x in diff_rows(a.rows, b.rows)
         if (x[0] != "CHANGED" or any(not f.startswith("x:") for f in x[4]))
         and not (x[0] != "CHANGED" and _blank(x[2]) and _blank(x[3]))]
    return d, (sum(1 for x in d if x[0] == "CHANGED"), sum(1 for x in d if x[0] == "ONLY_A"),
               sum(1 for x in d if x[0] == "ONLY_B"))


# ---------------------------------------------------------------- revision timeline card
class FileChip(QFrame):
    def __init__(self, f, group, n_groups, on_set, parent=None):
        super().__init__(parent)
        self.f = f
        gi = group[0] if group else None
        self.fill = theme.GROUP_FILLS[gi % len(theme.GROUP_FILLS)] if gi is not None else theme.NONE_SOFT
        self.border = theme.ERR if n_groups and n_groups > 1 else theme.LINE
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(1)
        self.badge = QLabel("")
        tag = f"Content {'ABCDEF'[gi]}" if gi is not None else ("unreadable" if f.error else "review copy")
        lay.addLayout(hbox(QLabel(f"<b>{f.name}</b>"), None, self.badge))
        sub = QLabel(f"<span style='color:{theme.MUTED}'>{f.loc} · "
                     f"{os.path.dirname(f.rel) or '.'}<br>{len(f.rows)} lines · {tag}</span>")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        row = QHBoxLayout()
        b_open, b_dir = QPushButton("Open"), QPushButton("Folder")
        self.b_a, self.b_b = QPushButton("Set as A"), QPushButton("Set as B")
        for b in (b_open, b_dir):
            b.setStyleSheet("padding:2px 8px;font-size:8.5pt;")
        self.b_a.setStyleSheet(f"padding:2px 8px;font-size:8.5pt;color:{A_INK};font-weight:600;")
        self.b_b.setStyleSheet(f"padding:2px 8px;font-size:8.5pt;color:{B_INK};font-weight:600;")
        self.b_a.setToolTip("Use this file as A (the reference) in the comparison below")
        self.b_b.setToolTip("Use this file as B (the one checked against A) in the comparison below")
        b_open.clicked.connect(lambda: open_path(f.path))
        b_dir.clicked.connect(lambda: open_folder(f.path))
        self.b_a.clicked.connect(lambda: on_set("A", f))
        self.b_b.clicked.connect(lambda: on_set("B", f))
        for b in (b_open, b_dir, self.b_a, self.b_b):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.setToolTip(f.path)
        self.mark(None)

    def mark(self, which):
        """Highlight the card when it is picked as A or B."""
        if which:
            ink = A_INK if which == "A" else B_INK
            self.badge.setText(f"<span style='background:{ink};color:white;font-weight:700'>&nbsp;{which}&nbsp;</span>")
            border = f"3px solid {ink}"
        else:
            self.badge.setText("")
            border = f"1px solid {self.border}"
        self.setStyleSheet(f"FileChip{{background:{self.fill};border:{border};border-radius:6px;}}"
                           f"QLabel{{background:transparent;border:none;}}")


# ---------------------------------------------------------------- diff view
class ChangeDelegate(QStyledItemDelegate):
    """Changed cell: A value struck through in red → B value in green."""

    def paint(self, p, opt, index):
        pair = index.data(Qt.UserRole)
        if not pair:
            return super().paint(p, opt, index)
        old, new = pair
        p.save()
        p.fillRect(opt.rect, QColor(theme.WARN_SOFT))
        if opt.state & QStyle.State_Selected:
            p.fillRect(opt.rect, QColor(47, 111, 237, 40))
        f = QFont(opt.font)
        r = opt.rect.adjusted(6, 0, -4, 0)
        fm = p.fontMetrics()
        old_t = old if old != "" else "(blank)"
        new_t = new if new != "" else "(blank)"
        f.setStrikeOut(True)
        p.setFont(f)
        p.setPen(QColor(theme.ERR))
        w_old = min(fm.horizontalAdvance(old_t) + 2, r.width() // 2)
        p.drawText(QRect(r.left(), r.top(), w_old, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(old_t, Qt.ElideRight, w_old))
        f.setStrikeOut(False)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        x = r.left() + w_old + 4
        p.drawText(QRect(x, r.top(), 16, r.height()), Qt.AlignVCenter | Qt.AlignLeft, "→")
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.OK))
        p.drawText(QRect(x + 18, r.top(), r.right() - x - 18, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(new_t, Qt.ElideRight, r.right() - x - 18))
        p.restore()

    def sizeHint(self, opt, index):
        pair = index.data(Qt.UserRole)
        s = super().sizeHint(opt, index)
        if pair:
            s.setWidth(opt.fontMetrics.horizontalAdvance(f"{pair[0]} → {pair[1]}") + 40)
        return s


class StatCard(QFrame):
    """Big number + caption; click to show only that kind of line."""
    clicked = Signal()

    def __init__(self, ink, soft, parent=None):
        super().__init__(parent)
        self.ink, self.soft = ink, soft
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(0)
        self.num = QLabel("0")
        self.num.setStyleSheet(f"color:{ink};font-size:20pt;font-weight:700;background:transparent;")
        self.cap = QLabel("")
        self.cap.setWordWrap(True)
        self.cap.setStyleSheet(f"color:{theme.INK};background:transparent;")
        lay.addWidget(self.num)
        lay.addWidget(self.cap)
        self.set_on(False)

    def set_on(self, on):
        self.setStyleSheet(f"StatCard{{background:{self.soft};border:{'2px' if on else '1px'} solid "
                           f"{self.ink if on else self.soft};border-radius:8px;}}")

    def mousePressEvent(self, e):
        self.clicked.emit()


class DiffView(QWidget):
    """Plain-language comparison of two BOM files: what is missing, extra and changed in B against A."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.head = label("", wrap=True)
        self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.head)
        self.sentence = label("", wrap=True)
        self.sentence.setStyleSheet("font-size:11pt;")
        lay.addWidget(self.sentence)
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.c_a = StatCard(theme.ERR, theme.ERR_SOFT)
        self.c_b = StatCard(theme.OK, theme.OK_SOFT)
        self.c_ch = StatCard(theme.WARN, theme.WARN_SOFT)
        self.c_same = StatCard(theme.MUTED, theme.NONE_SOFT)
        for kind, c in (("ONLY_A", self.c_a), ("ONLY_B", self.c_b), ("CHANGED", self.c_ch), (None, self.c_same)):
            c.clicked.connect(lambda k=kind: self._toggle_kind(k))
            cards.addWidget(c)
        self.cards_host = QWidget()
        self.cards_host.setLayout(cards)
        lay.addWidget(self.cards_host)
        self.cols = label("", wrap=True)
        lay.addWidget(self.cols)
        self.only_diff_cols = QCheckBox("Show only the columns that differ")
        self.only_diff_cols.setChecked(True)
        self.only_diff_cols.toggled.connect(lambda _: self._render())
        self.kind_note = label("", "muted")
        lay.addLayout(hbox(self.only_diff_cols, None, self.kind_note))
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setItemDelegate(ChangeDelegate(self.table))
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        lay.addWidget(self.table, 1)
        self.b_a = QPushButton("Open file A")
        self.b_b = QPushButton("Open file B")
        lay.addLayout(hbox(self.b_a, self.b_b, None))
        self.a = self.b = None
        self.d = []
        self.kind = None
        self.b_a.clicked.connect(lambda: self.a and open_path(self.a.path))
        self.b_b.clicked.connect(lambda: self.b and open_path(self.b.path))
        self.clear("Pick two files in the timeline above (Set as A, Set as B) and press Compare.")

    def clear(self, msg=""):
        self.a = self.b = None
        self.d = []
        self.head.setText(msg)
        self.sentence.setText("")
        self.cols.setText("")
        self.cards_host.hide()
        self.only_diff_cols.hide()
        self.kind_note.setText("")
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.b_a.hide()
        self.b_b.hide()

    def show_pair(self, a, b):
        self.a, self.b = a, b
        self.d, (n_ch, n_a, n_b) = diff_stats(a, b)
        self.kind = None
        na, nb = short(a), short(b)
        self.head.setText(
            f"<span style='background:{A_INK};color:white;font-weight:700'>&nbsp;A&nbsp;</span> "
            f"<b>{na}</b> <span style='color:{theme.MUTED}'>(reference) — {a.path}</span><br>"
            f"<span style='background:{B_INK};color:white;font-weight:700'>&nbsp;B&nbsp;</span> "
            f"<b>{nb}</b> <span style='color:{theme.MUTED}'>(checked against A) — {b.path}</span>")
        n_same = max(0, len([r for r in b.rows if not _blank(r)]) - n_b - n_ch)
        if not self.d:
            note = " (only free-text note columns differ)" if a.content_hash != b.content_hash else ""
            self.sentence.setText(f"<b style='color:{theme.OK}'>✓ B is identical to A</b> in all 20 SAP columns"
                                  f"{note} — {len(a.rows)} lines.")
            self.cards_host.hide()
            self.cols.setText("")
        else:
            parts = []
            if n_a:
                parts.append(f"is <b style='color:{theme.ERR}'>missing {n_a} line{'s' * (n_a != 1)}</b> that A has")
            if n_b:
                parts.append(f"has <b style='color:{theme.OK}'>{n_b} extra line{'s' * (n_b != 1)}</b> that A does "
                             f"not have")
            if n_ch:
                parts.append(f"has <b style='color:{theme.WARN}'>{n_ch} line{'s' * (n_ch != 1)} with different "
                             f"values</b>")
            self.sentence.setText(f"Compared with A, <b>B ({nb})</b> " + ", ".join(parts[:-1]) +
                                  (" and " if len(parts) > 1 else "") + parts[-1] + ".")
            self.c_a.num.setText(str(n_a))
            self.c_a.cap.setText(f"Only in A — missing from B")
            self.c_b.num.setText(str(n_b))
            self.c_b.cap.setText(f"Only in B — not in A")
            self.c_ch.num.setText(str(n_ch))
            self.c_ch.cap.setText("Changed — same Material No., different values")
            self.c_same.num.setText(str(n_same))
            self.c_same.cap.setText("Identical lines")
            self.cards_host.show()
            cc = Counter(f for x in self.d if x[0] == "CHANGED" for f in x[4] if not f.startswith("x:"))
            self.cols.setText(("Changed columns: " + "  ".join(
                f"<span style='background:{theme.WARN_SOFT};color:{theme.WARN}'>&nbsp;<b>{FIELD_TITLE[f]}</b> "
                f"× {n}&nbsp;</span>" for f, n in cc.most_common())) if cc else "")
        self.b_a.show()
        self.b_b.show()
        self._render()

    def _toggle_kind(self, kind):
        self.kind = None if self.kind == kind else kind
        self._render()

    def _render(self):
        for c, k in ((self.c_a, "ONLY_A"), (self.c_b, "ONLY_B"), (self.c_ch, "CHANGED"), (self.c_same, None)):
            c.set_on(self.kind == k and k is not None)
        a, b = self.a, self.b
        if a is None:
            return
        d = [x for x in self.d if self.kind is None or x[0] == self.kind]
        self.only_diff_cols.setVisible(bool(self.d))
        self.kind_note.setText({None: "Click a number card to show only those lines",
                                "ONLY_A": "Showing: lines only in A  (click the card again for all)",
                                "ONLY_B": "Showing: lines only in B  (click the card again for all)",
                                "CHANGED": "Showing: changed lines  (click the card again for all)"}[self.kind])
        changed_fields = {f for x in self.d for f in x[4]}
        fields = [f for f in FIELD_IDS if f != "material"]
        if self.only_diff_cols.isChecked() and changed_fields:
            keep = {"desc1", "qty", "unit"}          # context columns that help recognise a line
            fields = [f for f in fields if f in changed_fields or f in keep]
        fields.sort(key=lambda f: (f not in changed_fields, FIELD_IDS.index(f)))
        extra = sorted(f for f in changed_fields if f.startswith("x:"))
        fields += extra
        titles = dict(FIELD_TITLE)
        titles.update({f: f[2:].replace("\n", " ") + " (note)" for f in extra})
        t = self.table
        t.clear()
        t.setRowCount(len(d))
        t.setColumnCount(2 + len(fields))
        t.setHorizontalHeaderLabels(["What", "Material No."] +
                                    [("● " if f in changed_fields else "") + titles[f] for f in fields])
        kinds = {"CHANGED": ("Changed", theme.WARN, theme.WARN_SOFT),
                 "ONLY_A": ("Missing in B", theme.ERR, theme.ERR_SOFT),
                 "ONLY_B": ("Extra in B", theme.OK, theme.OK_SOFT)}
        bold = QFont()
        bold.setBold(True)
        for r, (kind, key, ra, rb, ch) in enumerate(d):
            text, ink, soft = kinds[kind]
            it = QTableWidgetItem(text)
            it.setForeground(QColor(ink))
            it.setBackground(QColor(soft))
            it.setFont(bold)
            t.setItem(r, 0, it)
            it = QTableWidgetItem(key)
            it.setFont(bold)
            if kind != "CHANGED":
                it.setBackground(QColor(soft))
            t.setItem(r, 1, it)
            for c, f in enumerate(fields, start=2):
                va, vb = (ra or {}).get(f, ""), (rb or {}).get(f, "")
                if kind == "CHANGED" and f in ch:
                    it = QTableWidgetItem(f"{va} → {vb}")
                    it.setData(Qt.UserRole, (va, vb))
                    it.setToolTip(f"A ({short(a)}): {va}\nB ({short(b)}): {vb}")
                else:
                    it = QTableWidgetItem(va if ra else vb)
                    if kind != "CHANGED":
                        it.setBackground(QColor(soft))
                        it.setForeground(QColor(ink))
                t.setItem(r, c, it)
        t.resizeColumnsToContents()
        for c in range(t.columnCount()):
            f = fields[c - 2] if c >= 2 else None
            cap = 460 if f in changed_fields else 260
            t.setColumnWidth(c, max(70, min(t.columnWidth(c) + 10, cap)))


class DiffDialog(QDialog):
    def __init__(self, a, b, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BOM comparison")
        _size_to_screen(self, 0.85)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(label("BOM comparison", "pageTitle"))
        a, b = sorted((a, b), key=lambda f: (ROLE_ORDER[f.role], f.loc != "ACTIVE"))
        v = DiffView(self)
        v.show_pair(a, b)
        lay.addWidget(v, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addLayout(hbox(None, close))


# ---------------------------------------------------------------- comparison list item
class PairItemDelegate(QStyledItemDelegate):
    """List entry: title, sub line, and a stacked bar missing / extra / changed."""

    def sizeHint(self, opt, index):
        return QSize(opt.rect.width(), 74)

    def paint(self, p, opt, index):
        info = index.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = opt.rect.adjusted(4, 3, -4, -3)
        sel = opt.state & QStyle.State_Selected
        p.setPen(QColor(theme.ACCENT) if sel else QColor(theme.LINE))
        p.setBrush(QColor("#EEF3FE") if sel else QColor(theme.SURFACE))
        p.drawRoundedRect(r, 6, 6)
        ink = theme.KIND_COLORS[info["kind"]][0]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ink))
        p.drawRoundedRect(QRect(r.left(), r.top(), 4, r.height()), 2, 2)
        f = QFont(opt.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(QRect(r.left() + 12, r.top() + 4, r.width() - 16, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(info["title"], Qt.ElideRight, r.width() - 16))
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRect(r.left() + 12, r.top() + 24, r.width() - 16, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(info["sub"], Qt.ElideRight, r.width() - 16))
        n_ch, n_a, n_b = info["stats"]
        tot = n_ch + n_a + n_b
        bar = QRect(r.left() + 12, r.top() + 48, r.width() - 24, 10)
        if tot == 0:
            p.setBrush(QColor(theme.OK_SOFT))
            p.drawRoundedRect(bar, 3, 3)
        else:
            x = bar.left()
            for n, col in ((n_a, theme.ERR), (n_b, theme.OK), (n_ch, theme.WARN)):
                w = round(bar.width() * n / tot)
                if w:
                    p.setBrush(QColor(col))
                    p.drawRect(QRect(x, bar.top(), w, bar.height()))
                    x += w
        p.restore()


# ---------------------------------------------------------------- BOM detail
class BomDetailDialog(QDialog):
    def __init__(self, ks, win=None):
        super().__init__(win)
        self.ks = ks
        self.win = win
        self.setWindowTitle(f"BOM {ks.key}")
        _size_to_screen(self, 0.92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)
        sev = ks.worst
        ink, _ = theme.SEV_COLORS[sev]
        state = {"ERROR": "Needs correction", "WARN": "Check", None: "All folders consistent"}.get(sev, "OK")
        chips = []
        for role, _t in ROLES:
            text, kind = ks.folder(role)
            k_ink, k_soft = theme.KIND_COLORS[kind]
            chips.append(f"<span style='background:{k_soft};color:{k_ink}'>&nbsp;<b>{ROLE_TITLE[role]}</b> "
                         f"{text}&nbsp;</span>")
        lay.addLayout(hbox(label(f"{ks.key}", "pageTitle"),
                           label(f"<span style='color:{ink};font-weight:700'>● {state}</span>"), None,
                           label(" &nbsp; ".join(chips))))

        # ---- quick fixes (copy) for missing / outdated files
        fixes = [i for i in ks.open_issues if can_copy(i)]
        if fixes and win:
            bar = QHBoxLayout()
            bar.addWidget(label(f"<b style='color:{theme.ERR}'>Quick fix:</b>"))
            for i in fixes[:4]:
                b = QPushButton(f"Copy to fix — {i.title}")
                b.setStyleSheet(f"color:{theme.ERR};font-weight:600;")
                b.clicked.connect(lambda _=False, i=i: self._copy(i))
                bar.addWidget(b)
            bar.addStretch(1)
            lay.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        # ---- top: revision timeline, rows = revisions, columns = folders
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(label("Revision timeline — same color = same content · red border = copies of one revision "
                           "differ", "muted"))
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)
        groups, ngroups = content_groups(ks.files)
        revs = sorted({f.rev for f in ks.files}, reverse=True)
        grid.addWidget(label("<b>Rev</b>"), 0, 0)
        self.chips = []
        for c, (role, title) in enumerate(ROLES, start=1):
            ink_r, _ = theme.STATUS_COLORS[role]
            grid.addWidget(label(f"<b style='color:{ink_r}'>{title}</b>"), 0, c)
            grid.setColumnStretch(c, 1)
        for r, rev in enumerate(revs, start=1):
            latest = rev == ks.prod_rev
            grid.addWidget(label(f"<b>R{rev}</b>{'<br><span style=color:#2F6FED>latest</span>' if latest else ''}"),
                           r, 0, Qt.AlignTop)
            for c, (role, _) in enumerate(ROLES, start=1):
                cell = QVBoxLayout()
                cell.setSpacing(4)
                fl = [f for f in ks.files if f.role == role and f.rev == rev]
                for f in fl:
                    chip = FileChip(f, groups.get(id(f)), ngroups.get(rev, 0), self.set_side)
                    self.chips.append(chip)
                    cell.addWidget(chip)
                if not fl:
                    cell.addWidget(label(f"<span style='color:{theme.NONE}'>—</span>"))
                cell.addStretch(1)
                grid.addLayout(cell, r, c)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(grid_host)
        tl.addWidget(sc, 1)

        # ---- compare bar: pick A and B, compare, reset
        cmp_box = QFrame()
        cmp_box.setObjectName("card")
        cb = QHBoxLayout(cmp_box)
        cb.setContentsMargins(12, 8, 12, 8)
        cb.addWidget(label("<b>Compare two files</b>"))
        self.lab_a = QLabel()
        self.lab_b = QLabel()
        swap = QPushButton("⇄ Swap")
        swap.setToolTip("Exchange A and B")
        swap.clicked.connect(self._swap)
        self.b_cmp = QPushButton("Compare A ↔ B")
        self.b_cmp.setObjectName("primary")
        self.b_cmp.clicked.connect(self._compare_ab)
        reset = QPushButton("Reset comparisons")
        reset.setToolTip("Clear A / B and remove the comparisons you added — back to the automatic list")
        reset.clicked.connect(self.reset)
        cb.addWidget(self.lab_a)
        cb.addWidget(swap)
        cb.addWidget(self.lab_b)
        cb.addWidget(self.b_cmp)
        cb.addStretch(1)
        cb.addWidget(label("1 · press <b style='color:%s'>Set as A</b> on one file  2 · <b style='color:%s'>Set as "
                           "B</b> on another  3 · Compare" % (A_INK, B_INK), "muted"))
        cb.addWidget(reset)
        tl.addWidget(cmp_box)
        split.addWidget(top)

        # ---- bottom: differences (visual) + issues
        tabs = QTabWidget()
        diff_tab = QWidget()
        dl = QHBoxLayout(diff_tab)
        dl.setContentsMargins(0, 8, 0, 0)
        dl.setSpacing(12)
        left = QVBoxLayout()
        left.addWidget(label("Comparisons", "h2"))
        left.addWidget(label("Found automatically from this BOM's problems, plus the ones you add. "
                             "<span style='color:%s'>■</span> missing in B <span style='color:%s'>■</span> extra in B "
                             "<span style='color:%s'>■</span> changed" % (theme.ERR, theme.OK, theme.WARN),
                             "muted", wrap=True))
        self.pairs = QListWidget()
        self.pairs.setItemDelegate(PairItemDelegate(self.pairs))
        self.pairs.setFixedWidth(430)
        self.pairs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pairs.setStyleSheet("QListWidget{border:none;background:transparent;}"
                                 "QListWidget::item:selected{background:transparent;}")
        self.pairs.currentItemChanged.connect(self._show_current)
        left.addWidget(self.pairs, 1)
        dl.addLayout(left)
        self.view = DiffView()
        dl.addWidget(self.view, 1)
        self.side = {"A": None, "B": None}
        n_pairs = self._fill_pairs()
        tabs.addTab(diff_tab, f"What differs ({n_pairs})")

        iss_tab = QWidget()
        il = QVBoxLayout(iss_tab)
        il.setContentsMargins(0, 8, 0, 0)
        model = DictTableModel([("sev", "Severity"), ("title", "Issue"), ("rev", "Rev"), ("detail", "Detail"),
                                ("action", "Corrective action")], chip_cols=("sev",))
        model.set_rows([{"sev": "ACK" if i.ack else i.sev, "_kind:sev": "ACK" if i.ack else i.sev,
                         "title": i.title, "rev": i.rev, "detail": i.detail, "action": i.action, "_i": i}
                        for i in ks.issues])
        self.iss_table = DataTable(model)
        self.iss_table.set_widths([90, 330, 80, 520])
        il.addWidget(self.iss_table, 1)
        if win:
            b_fix = QPushButton("Copy to fix…")
            b_ack = QPushButton("Acknowledge as minor…")
            b_un = QPushButton("Undo acknowledge")
            b_fix.clicked.connect(lambda: self._sel_issue(self._copy))
            b_ack.clicked.connect(lambda: self._sel_issues(lambda l: self._done(win.acknowledge(l, self))))
            b_un.clicked.connect(lambda: self._sel_issues(lambda l: self._done(win.unacknowledge(l))))
            il.addLayout(hbox(b_fix, b_ack, b_un, None))
        n_ack = len(ks.acked_issues)
        tabs.addTab(iss_tab, f"Issues ({len(ks.open_issues)} open" + (f", {n_ack} ack'd)" if n_ack else ")"))
        split.addWidget(tabs)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        lay.addWidget(split, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addLayout(hbox(None, close))
        self._update_bar()

    # ---- A / B selection
    def set_side(self, which, f):
        other = "B" if which == "A" else "A"
        if self.side[other] is f:
            self.side[other] = None
        self.side[which] = f
        self._update_bar()

    def _swap(self):
        self.side["A"], self.side["B"] = self.side["B"], self.side["A"]
        self._update_bar()

    def _update_bar(self):
        for which, lab, ink, soft in (("A", self.lab_a, A_INK, A_SOFT), ("B", self.lab_b, B_INK, B_SOFT)):
            f = self.side[which]
            txt = f"<b>{short(f)}</b>" if f else "<i>not selected</i>"
            lab.setText(f"<span style='background:{ink};color:white;font-weight:700'>&nbsp;{which}&nbsp;</span>"
                        f"<span style='background:{soft}'>&nbsp;{txt}&nbsp;</span>")
        for chip in self.chips:
            chip.mark("A" if chip.f is self.side["A"] else "B" if chip.f is self.side["B"] else None)
        self.b_cmp.setEnabled(bool(self.side["A"] and self.side["B"]))

    def _compare_ab(self):
        a, b = self.side["A"], self.side["B"]
        if not (a and b):
            return
        for n in range(self.pairs.count()):           # same pair already listed: just show it
            info = self.pairs.item(n).data(Qt.UserRole)
            if info["a"] is a and info["b"] is b:
                self.pairs.setCurrentRow(n)
                return
        self._add_pair(a, b, "your comparison", None, select=True, user=True, keep_order=True)

    def reset(self):
        self.side = {"A": None, "B": None}
        self._update_bar()
        for i in reversed(range(self.pairs.count())):
            if self.pairs.item(i).data(Qt.UserRole).get("user"):
                self.pairs.takeItem(i)
        if self.pairs.count():
            self.pairs.setCurrentRow(0)
            self._show_current(self.pairs.currentItem(), None)
        else:
            self.view.clear("Pick two files in the timeline above (Set as A, Set as B) and press Compare.")

    # ---- comparison list
    def _fill_pairs(self):
        seen = set()
        for i in self.ks.issues:
            if i.code not in DIFF_CODES:
                continue
            fl = [f for f in i.files if f.rows and not f.error]
            if len(fl) < 2:
                continue
            for other in fl[1:]:
                self._add_pair(fl[0], other, i.title, None if i.ack else i.sev, seen)
        if self.pairs.count():
            self.pairs.setCurrentRow(0)
        else:
            self.view.clear(f"<b style='color:{theme.OK}'>No content differences between the folders.</b> "
                            "To compare any two files: Set as A, Set as B, then Compare.")
        return self.pairs.count()

    def _add_pair(self, a, b, why, sev, seen=None, select=False, user=False, keep_order=False):
        if not keep_order:
            a, b = sorted((a, b), key=lambda f: (ROLE_ORDER[f.role], f.loc != "ACTIVE", -f.rev))
        k = (a.path, b.path)
        if seen is not None:
            if k in seen:
                return
            seen.add(k)
        _d, stats = diff_stats(a, b)
        item = QListWidgetItem()
        kind = {"ERROR": "ERROR", "WARN": "WARN"}.get(sev, "INFO" if user else ("OK" if not sum(stats) else "ACK"))
        n_ch, n_a, n_b = stats
        sub = (f"{n_a} missing in B · {n_b} extra in B · {n_ch} changed" if sum(stats)
               else "identical in SAP columns") + f"  —  {why}"
        item.setData(Qt.UserRole, {"title": f"A {short(a)}  ↔  B {short(b)}", "sub": sub, "stats": stats,
                                   "kind": kind, "a": a, "b": b, "user": user})
        item.setToolTip(f"A: {a.path}\nB: {b.path}\n{why}")
        if user:
            self.pairs.insertItem(0, item)
        else:
            self.pairs.addItem(item)
        if select:
            self.pairs.setCurrentItem(item)

    def _show_current(self, cur, _prev):
        if cur:
            info = cur.data(Qt.UserRole)
            self.view.show_pair(info["a"], info["b"])

    # ---- actions
    def _sel_issues(self, fn):
        rows = self.iss_table.selected_rows()
        if rows:
            fn([r["_i"] for r in rows])

    def _sel_issue(self, fn):
        rows = self.iss_table.selected_rows()
        if rows:
            fn(rows[0]["_i"])

    def _copy(self, issue):
        if self.win:
            self._done(self.win.copy_fix(issue, self))

    def _done(self, changed):
        if changed:              # data changed: reopen with fresh state
            self.accept()
            self.win.show_bom_key(self.ks.key)


# ---------------------------------------------------------------- copy to fix
class CopyDialog(QDialog):
    """Step 1: show exactly what will be copied where. Step 2 (on Copy): final yes/no question."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Copy to fix")
        self.resize(980, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)
        i = plan.issue
        lay.addWidget(label(plan.what, "pageTitle"))
        lay.addWidget(label(f"Problem: <b>{i.title}</b> — {i.key} {i.rev}", wrap=True))

        def box(title, ink, body):
            f = QFrame()
            f.setObjectName("card")
            v = QVBoxLayout(f)
            v.setContentsMargins(14, 10, 14, 10)
            v.addWidget(label(f"<b style='color:{ink}'>{title}</b>"))
            for w in body:
                v.addWidget(w) if isinstance(w, QWidget) else v.addLayout(w)
            return f

        src = plan.src
        lay.addWidget(box(f"FROM  ·  {ROLE_TITLE[src.role]}", theme.ACCENT, [
            label(f"<b>{src.name}</b>  ·  R{src.rev}  ·  {len(src.rows)} lines  ·  {src.loc}", wrap=True),
            label(src.path, "muted", wrap=True)]))
        self.dest = QLineEdit(plan.dest_dir)
        self.dest.setPlaceholderText("Choose the destination folder")
        pick = QPushButton("Change folder…")
        pick.clicked.connect(self._pick)
        self.dest_note = label("", "muted", wrap=True)
        self.dest.textChanged.connect(self._update)
        lay.addWidget(box(f"TO  ·  {ROLE_TITLE[plan.target_role]}", "#7A4FD0", [
            label(f"<b>{src.name}</b>  (same file name, nothing is renamed)"),
            hbox(self.dest, pick), self.dest_note]))
        self.arch = None
        if plan.old:
            self.arch = QCheckBox(f"Also move the superseded file {plan.old.name} into its Arch folder")
            self.arch.setToolTip(plan.old.path)
            lay.addWidget(self.arch)
        lay.addWidget(label("Existing files are never overwritten. Every copy is written to the copy log "
                            "(Settings → Open copy log).", "muted"))
        lay.addStretch(1)
        self.b_copy = QPushButton("Copy…")
        self.b_copy.setObjectName("primary")
        self.b_copy.clicked.connect(self._confirm)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        lay.addLayout(hbox(None, cancel, self.b_copy))
        self._update()

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, "Destination folder", self.dest.text() or self.plan.src.folder)
        if d:
            self.dest.setText(os.path.normpath(d))

    def _update(self):
        d = self.dest.text().strip()
        if not d:
            self.dest_note.setText(f"<span style='color:{theme.ERR}'>{self.plan.how}</span>")
        elif os.path.exists(os.path.join(d, self.plan.src.name)):
            self.dest_note.setText(f"<span style='color:{theme.ERR}'>This folder already has a file with this "
                                   f"name — the copy will be refused.</span>")
        elif os.path.isdir(d):
            self.dest_note.setText(f"Existing folder · found: {self.plan.how}")
        else:
            self.dest_note.setText(f"<span style='color:{theme.WARN}'>New folder — it will be created.</span> "
                                   f"({self.plan.how})")
        self.b_copy.setEnabled(bool(d))

    def _confirm(self):
        d = self.dest.text().strip()
        msg = (f"복사 됩니다. 내용 정확히 확인하셨습니까?\n\n"
               f"FROM  {self.plan.src.path}\n\nTO    {os.path.join(d, self.plan.src.name)}")
        if self.arch is not None and self.arch.isChecked():
            msg += f"\n\n+ {self.plan.old.name} → Arch"
        ans = QMessageBox.question(self, "Confirm copy", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.dest_dir = d
            self.archive_old = bool(self.arch is not None and self.arch.isChecked())
            self.accept()


# ---------------------------------------------------------------- acknowledge
class AckDialog(QDialog):
    def __init__(self, issues, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acknowledge as minor")
        self.resize(720, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.addWidget(label("Acknowledge as a known minor alarm", "pageTitle"))
        lay.addWidget(label("The files stay as they are. These alarms move out of the error / warning counts and "
                            "colors into “Acknowledged”. If any of the files changes later, the alarm comes back "
                            "automatically.", "muted", wrap=True))
        lst = "".join(f"<li><b>{i.key}</b> {i.rev} — {i.title}</li>" for i in issues[:12])
        more = f"<li>… and {len(issues) - 12} more</li>" if len(issues) > 12 else ""
        lay.addWidget(label(f"<ul>{lst}{more}</ul>", wrap=True))
        lay.addWidget(label("Reason (who checked it and why it is acceptable):"))
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("e.g. Only Date of Release differs; confirmed with design lead, no rework needed.")
        lay.addWidget(self.note, 1)
        ok = QPushButton(f"Acknowledge {len(issues)} alarm{'s' * (len(issues) != 1)}")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        lay.addLayout(hbox(None, cancel, ok))

    def text(self):
        return self.note.toPlainText()
