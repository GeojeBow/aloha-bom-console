"""Main window: navigation, hull filter, scan/export actions and the pages."""
import datetime as dt
import os
import pickle
import traceback
from collections import Counter, defaultdict
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, VERSION, acks, fixer
from .. import master_check as mc
from ..analyzer import (FOLDER_COLS, ISSUE_TYPES, MASTER_COLS, ROLE_TITLE, ROLES, SEV_RANK, analyze, apply_acks,
                        folder_fields)
from ..config import Config, cache_dir
from ..report import build_master_check_report, build_report
from ..scanner import discover, load_all
from . import theme
from .dialogs import AckDialog, BomDetailDialog, CopyDialog, DiffDialog, open_folder, open_path
from .widgets import BomTile, CheckTile, DataTable, DictTableModel, FlowLayout, FolderCard, KpiCard, hbox, label

RESULT_FILE = "last_result.pkl"


# ---------------------------------------------------------------- background work
class ScanWorker(QThread):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            files, others, errs = discover(self.cfg, progress=lambda m: self.progress.emit(m, 0, 0),
                                           cancel=lambda: self._cancel)
            if self._cancel:
                self.failed.emit("Scan cancelled.")
                return
            load_all(self.cfg, files, progress=lambda m, d=0, t=0: self.progress.emit(f"Reading BOMs… {m}", d, t),
                     cancel=lambda: self._cancel)
            if self._cancel:
                self.failed.emit("Scan cancelled.")
                return
            self.progress.emit("Cross-checking…", 0, 0)
            res = analyze(self.cfg, files, others, errs)
            try:
                with open(cache_dir() / RESULT_FILE, "wb") as fh:
                    pickle.dump(res, fh)
            except OSError:
                pass
            self.done.emit(res)
        except Exception:  # noqa: BLE001 - surface any failure to the user
            self.failed.emit(traceback.format_exc())


class FuncWorker(QThread):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.progress.emit))
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------- pages
class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("page")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(24, 18, 24, 18)
        self.lay.setSpacing(12)

    def refresh(self):
        pass


def _empty_note():
    return label("No scan yet. Press “Scan folders” to collect the BOMs.", "muted")


class DashboardPage(Page):
    title = "Dashboard"
    subtitle = "Every BOM of the selected hull at a glance — click a tile for its revision history"

    def __init__(self, win):
        super().__init__(win)
        self.cards = {}
        row = QHBoxLayout()
        row.setSpacing(12)
        for key, lab, color in (("boms", "BOMs", None), ("lines", "Line items", None),
                                ("bad", "BOMs needing correction", theme.ERR), ("err", "Errors", theme.ERR),
                                ("warn", "Warnings", theme.WARN), ("sync", "Work Package in sync", theme.OK)):
            c = KpiCard(lab, color)
            self.cards[key] = c
            row.addWidget(c)
        self.cards["err"].clicked.connect(lambda: win.goto_issues(sev="ERROR"))
        self.cards["warn"].clicked.connect(lambda: win.goto_issues(sev="WARN"))
        self.cards["bad"].clicked.connect(lambda: win.goto_issues(sev="ERROR"))
        self.cards["lines"].clicked.connect(lambda: win.nav_to("master"))
        self.cards["sync"].clicked.connect(lambda: win.nav_to("sync"))
        self.lay.addLayout(row)

        # health of the four source folders
        frow = QHBoxLayout()
        frow.setSpacing(12)
        self.fcards = {}
        for n, role in enumerate(ROLES):
            c = FolderCard(ROLE_TITLE[role])
            c.clicked.connect(lambda r=role: win.goto_sync(r))
            self.fcards[role] = c
            frow.addWidget(c)
        self.lay.addLayout(frow)

        body = QHBoxLayout()
        body.setSpacing(16)
        # block map
        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 14, 16, 14)
        legend = " ".join(
            f"<span style='color:{ink}'>■</span> {t}&nbsp;&nbsp;" for ink, t in
            ((theme.OK, "OK"), (theme.WARN, "Check"), (theme.ERR, "Needs correction"), (theme.NONE, "No file")))
        top = hbox(label("Block map", "h2"), None, label(legend, "muted"))
        ll.addLayout(top)
        ll.addWidget(label("Each tile: <b>P</b> 16 Prod DWG · <b>W</b> 17 Work Package · <b>D</b> 03 DCN · "
                           "<b>E</b> 04 ECN — the bar color is that folder's status", "muted"))
        self.filter_cb = QComboBox()
        self.filter_cb.addItems(["All BOMs", "Only BOMs with errors", "Only BOMs with issues",
                                 "Problem in 16 Prod DWG", "Problem in 17 Work Package", "Problem in 03 DCN",
                                 "Problem in 04 ECN", "Has DCN/ECN"])
        self.filter_cb.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find block, e.g. E410P")
        self.search.textChanged.connect(self.refresh)
        ll.addLayout(hbox(self.filter_cb, self.search, None))
        self.map_host = QWidget()
        self.map_host.setObjectName("mapHost")
        self.map_host.setStyleSheet(f"QWidget#mapHost{{background:{theme.SURFACE};}}")
        self.map_lay = QVBoxLayout(self.map_host)
        self.map_lay.setContentsMargins(0, 4, 0, 0)
        self.map_lay.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.map_host)
        ll.addWidget(sc, 1)
        body.addWidget(left, 3)

        # issue breakdown
        right = QFrame()
        right.setObjectName("card")
        right.setFixedWidth(460)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.addWidget(label("What needs fixing", "h2"))
        rl.addWidget(label("Click a line to open the action list.", "muted"))
        self.issue_host = QVBoxLayout()
        self.issue_host.setSpacing(6)
        rl.addLayout(self.issue_host)
        rl.addStretch(1)
        self.basis_note = label("", "muted", wrap=True)
        rl.addWidget(self.basis_note)
        body.addWidget(right)
        self.lay.addLayout(body, 1)

    def refresh(self):
        res = self.win.res
        for i in reversed(range(self.map_lay.count())):
            it = self.map_lay.takeAt(i)
            if it.widget():
                it.widget().deleteLater()
        for i in reversed(range(self.issue_host.count())):
            it = self.issue_host.takeAt(i)
            if it.widget():
                it.widget().deleteLater()
        if not res:
            self.map_lay.addWidget(_empty_note())
            return
        keys = self.win.visible_keys()
        issues = self.win.visible_issues()
        vis = {k.key for k in keys}
        lines = [m for m in res.master if m["_key"] in vis]
        n_del = sum(1 for m in lines if m.get("_deleted"))
        self.cards["boms"].set(f"{len(keys):,}", f"{len(res.files):,} files scanned")
        self.cards["lines"].set(f"{len(lines) - n_del:,}", f"active · {n_del:,} deleted lines (Mode D)")
        self.cards["bad"].set(f"{sum(1 for k in keys if k.worst == 'ERROR'):,}",
                              f"of {len(keys)} BOMs")
        self.cards["err"].set(f"{sum(1 for i in issues if i.sev == 'ERROR'):,}")
        n_ack = len(self.win.visible_issues("acked"))
        self.cards["warn"].set(f"{sum(1 for i in issues if i.sev == 'WARN'):,}",
                               f"+ {n_ack} acknowledged as minor (hidden)" if n_ack else "")
        with_prod = [k for k in keys if k.prod]
        sync = sum(1 for k in with_prod if k.wp_status == "SYNC")
        pct = f"{100 * sync / len(with_prod):.0f}%" if with_prod else "–"
        self.cards["sync"].set(pct, f"{sync} of {len(with_prod)} BOMs")
        for role, card in self.fcards.items():
            kinds = Counter(k.folder(role)[1] for k in keys)
            card.set_counts(kinds["OK"], kinds["WARN"], kinds["ERROR"], kinds["NONE"])

        mode = self.filter_cb.currentIndex()
        q = self.search.text().strip().upper()
        bad = lambda role: (lambda k: k.folder(role)[1] in ("ERROR", "WARN"))  # noqa: E731
        pred = [lambda k: True, lambda k: k.worst == "ERROR", lambda k: bool(k.issues),
                bad("PROD"), bad("WP"), bad("DCN"), bad("ECN"), lambda k: bool(k.cn_files)][mode]
        groups = defaultdict(list)
        for k in keys:
            if pred(k) and (not q or q in k.key):
                groups[(k.ship, k.group)].append(k)
        multi_hull = len({s for s, _ in groups}) > 1
        for (ship, g), kl in sorted(groups.items()):
            n_err = sum(1 for k in kl if k.worst == "ERROR")
            head = f"<b>{g}-blocks</b>" + (f" · {self.win.cfg.ship_label(ship)}" if multi_hull else "") + \
                   f"  <span style='color:{theme.MUTED}'>{len(kl)} BOMs" + \
                   (f" · <span style='color:{theme.ERR}'>{n_err} need correction</span>" if n_err else "") + "</span>"
            self.map_lay.addWidget(label(head))
            host = QWidget()
            fl = FlowLayout(host, spacing=6)
            for k in sorted(kl, key=lambda k: (k.block, k.phase, k.disc)):
                t = BomTile(k)
                t.clicked.connect(lambda _=False, k=k: self.win.show_bom(k))
                fl.addWidget(t)
            self.map_lay.addWidget(host)
        if not groups:
            self.map_lay.addWidget(label("No BOMs match the filter.", "muted"))
        self.map_lay.addStretch(1)

        cnt = Counter(i.code for i in issues)
        boms = defaultdict(set)
        for i in issues:
            boms[i.code].add(i.key)
        mx = max(cnt.values(), default=1)
        for code, n in sorted(cnt.items(), key=lambda kv: (-SEV_RANK[ISSUE_TYPES[kv[0]][0]], -kv[1])):
            sev, title, _ = ISSUE_TYPES[code]
            ink, soft = theme.SEV_COLORS[sev]
            b = QPushButton()
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{text-align:left;border:none;border-radius:6px;padding:6px 8px;"
                            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {soft},"
                            f"stop:{max(0.02, n / mx):.3f} {soft},stop:{min(1, n / mx + 0.001):.3f} transparent);}}"
                            f"QPushButton:hover{{border:1px solid {ink};}}")
            b.setText(f"{n:>4}   {title.replace('&', '&&')}   ({len(boms[code])} BOMs)")
            b.setToolTip(f"{title} — {n} issues in {len(boms[code])} BOMs")
            b.clicked.connect(lambda _=False, c=code: self.win.goto_issues(code=c))
            self.issue_host.addWidget(b)
        if not cnt:
            self.issue_host.addWidget(label(f"<span style='color:{theme.OK}'>No issues found.</span>"))
        sis = sorted({k.ship for k in keys if k.baseline_of})
        self.basis_note.setText(
            ("Note: " + ", ".join(self.win.cfg.ship_label(s) for s in sis) +
             f" have no BOMs in 16 Prod DWG; their Work Package / ECN copies are checked against "
             f"{self.win.cfg.ship_label(self.win.cfg['baseline_ship'])} Prod DWG.") if sis else "")


FOLDER_CHIPS = tuple(c for c, _ in FOLDER_COLS) + ("overall",)
FOLDER_FILTERS = ["Any folder status", "Problem in any folder", "Problem in 16 Prod DWG",
                  "Problem in 17 Work Package", "Problem in 03 DCN", "Problem in 04 ECN", "All four folders OK"]


def folder_pred(mode):
    """Row predicate for FOLDER_FILTERS (rows carry _kind:f_prod … _kind:f_ecn)."""
    bad = ("ERROR", "WARN")
    fields = [c for c, _ in FOLDER_COLS]
    if mode == 0:
        return None
    if mode == 1:
        return lambda r: any(r.get("_kind:" + f) in bad for f in fields)
    if 2 <= mode <= 5:
        f = fields[mode - 2]
        return lambda r: r.get("_kind:" + f) in bad
    return lambda r: all(r.get("_kind:" + f) in ("OK", "NONE") for f in fields)


class MasterPage(Page):
    title = "Master BOM"
    subtitle = ("All lines of the latest Prod DWG BOMs — status of 16 Prod DWG / 17 Work Package / 03 DCN / 04 ECN "
                "per line.  ▾ in a column header = Excel-style filter, right-click header = clear filters")

    def __init__(self, win):
        super().__init__(win)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Material No., description, block…  (space = AND)")
        self.only = QComboBox()
        self.only.addItems(FOLDER_FILTERS)
        self.deleted = QComboBox()
        self.deleted.addItems(["Show deleted lines", "Hide deleted lines", "Only deleted lines"])
        self.clear = QPushButton("Clear column filters")
        self.count = label("", "muted")
        self.lay.addLayout(hbox(self.search, self.only, self.deleted, self.clear, self.count))
        self.lay.addWidget(label(f"<span style='color:{theme.ERR}'><s>Red strike-through</s></span> = deleted line "
                                 "(Mode = D in the BOM). Line Status comes from the Mode column: "
                                 "A = Added, C = Changed, D = Deleted.", "muted"))
        self.model = DictTableModel(MASTER_COLS, chip_cols=FOLDER_CHIPS + ("line_status",))
        self.table = DataTable(self.model)
        self.table.on_filter = self._filter
        self.table.set_widths([65, 170, 175, 105, 230, 150, 150, 110, 110, 165, 100, 120, 80])
        self.lay.addWidget(self.table, 1)
        self.search.textChanged.connect(self._filter)
        self.only.currentIndexChanged.connect(self._filter)
        self.deleted.currentIndexChanged.connect(self._filter)
        self.clear.clicked.connect(self.table.clear_filters)
        self.table.doubleClicked.connect(lambda ix: win.show_bom_key(self.table.row_at(ix)["_key"]))

    def refresh(self):
        res = self.win.res
        ships = self.win.ship_filter
        self.model.set_rows([m for m in res.master if m["_key"].split("-")[0] in ships] if res else [])
        self._filter()

    def set_folder_filter(self, mode):
        self.only.setCurrentIndex(mode)

    def _filter(self):
        fp = folder_pred(self.only.currentIndex())
        dm = self.deleted.currentIndex()

        def pred(r):
            if dm == 1 and r.get("_deleted") or dm == 2 and not r.get("_deleted"):
                return False
            return fp(r) if fp else True
        self.table.proxy.pred = pred
        self.table.proxy.set_text(self.search.text())
        n_del = sum(1 for r in self.model.rows if r.get("_deleted"))
        self.count.setText(f"{self.table.proxy.rowCount():,} of {self.model.rowCount():,} lines · "
                           f"{n_del:,} deleted")


class SyncPage(Page):
    title = "Sync Matrix"
    subtitle = ("Every BOM across the four folders — latest revision in 16 Prod DWG against 17 Work Package, "
                "03 DCN and 04 ECN")
    COLS = [("hull", "Hull"), ("group", "Grp"), ("bom", "BOM")] + FOLDER_COLS + [
        ("overall", "Overall"), ("lines", "Lines"), ("n_err", "Errors"), ("n_warn", "Warnings"),
        ("prod_path", "Prod DWG file"), ("wp_path", "Work Package file"), ("cn_paths", "DCN / ECN files")]

    def __init__(self, win):
        super().__init__(win)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search BOM…")
        self.only = QComboBox()
        self.only.addItems(FOLDER_FILTERS)
        self.clear = QPushButton("Clear column filters")
        self.count = label("", "muted")
        self.lay.addLayout(hbox(self.search, self.only, self.clear, self.count))
        self.lay.addWidget(label("Folder cell = revision held there.  ✓ = consistent · “→” = outdated · “>” = ahead "
                                 "of Prod DWG · “≠” = same revision, different content · “via 1040” = hull "
                                 "without own Prod DWG BOM, checked against S040", "muted"))
        self.model = DictTableModel(self.COLS, chip_cols=FOLDER_CHIPS)
        self.table = DataTable(self.model)
        self.table.on_filter = self._filter
        self.table.set_widths([60, 50, 175, 150, 150, 120, 120, 160, 60, 60, 70, 360, 360])
        self.lay.addWidget(self.table, 1)
        self.search.textChanged.connect(self._filter)
        self.only.currentIndexChanged.connect(self._filter)
        self.clear.clicked.connect(self.table.clear_filters)
        self.table.doubleClicked.connect(lambda ix: win.show_bom_key(self.table.row_at(ix)["bom"]))

    def refresh(self):
        cfg = self.win.cfg
        rows = []
        for k in sorted(self.win.visible_keys(), key=lambda k: k.key):
            r = {"hull": cfg.ship_label(k.ship), "group": k.group, "bom": k.key,
                 "lines": len(k.prod.rows) if k.prod else 0,
                 "n_err": sum(1 for i in k.issues if i.sev == "ERROR") or "",
                 "n_warn": sum(1 for i in k.issues if i.sev == "WARN") or "",
                 "prod_path": k.prod.path if k.prod else "", "wp_path": k.wp.path if k.wp else "",
                 "cn_paths": "  |  ".join(f"{f.role}\\{f.rel}" for f in k.cn_files), "_k": k}
            r.update(folder_fields(k))
            rows.append(r)
        self.model.set_rows(rows)
        self._filter()

    def set_folder_filter(self, mode):
        self.only.setCurrentIndex(mode)

    def _filter(self):
        self.table.proxy.pred = folder_pred(self.only.currentIndex())
        self.table.proxy.set_text(self.search.text())
        self.count.setText(f"{self.table.proxy.rowCount():,} of {self.model.rowCount():,} BOMs")


class IssuesPage(Page):
    title = "Action List"
    subtitle = "Every inconsistency with its corrective action — double-click to inspect"
    COLS = [("sev", "Severity"), ("hull", "Hull"), ("bom", "BOM"), ("rev", "Rev"), ("folders", "Folder"),
            ("title", "Issue"), ("fix", "Quick fix"), ("detail", "Detail"), ("action", "Corrective action"),
            ("ack_note", "Acknowledged (by · when · why)")]

    def __init__(self, win):
        super().__init__(win)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search BOM, file, text…")
        self.state = QComboBox()
        self.state.addItems(["Open issues", "Acknowledged (minor)", "All"])
        self.state.setToolTip("Acknowledged = checked and accepted as a known minor alarm; kept out of the "
                              "error / warning counts")
        self.sev = QComboBox()
        self.sev.addItems(["All severities", "ERROR", "WARN"])
        self.code = QComboBox()
        self.code.addItem("All issue types", None)
        for c, (s, t, _) in sorted(ISSUE_TYPES.items(), key=lambda kv: (-SEV_RANK[kv[1][0]], kv[1][1])):
            self.code.addItem(t, c)
        self.count = label("", "muted")
        self.lay.addLayout(hbox(self.search, self.state, self.sev, self.code, self.count))
        self.model = DictTableModel(self.COLS, chip_cols=("sev", "folders", "fix"))
        self.table = DataTable(self.model)
        self.table.on_filter = self._filter
        self.table.set_widths([85, 60, 170, 80, 150, 300, 110, 460, 380])
        self.lay.addWidget(self.table, 1)
        b_open, b_folder, b_cmp, b_bom = (QPushButton(t) for t in ("Open file", "Open folder", "Compare files",
                                                                   "BOM detail"))
        self.b_fix = QPushButton("Copy to fix…")
        self.b_fix.setToolTip("Copy the missing / outdated BOM file between 16 Prod DWG and 17 Work Packages")
        self.b_fix.setStyleSheet(f"QPushButton{{color:{theme.ERR};font-weight:600;}}"
                                 "QPushButton:disabled{color:#A9B2BC;font-weight:400;}")
        self.b_ack = QPushButton("Acknowledge as minor…")
        self.b_ack.setToolTip("Checked and acceptable: keep the files as they are, move these alarms out of the "
                              "error / warning counts")
        self.b_unack = QPushButton("Undo acknowledge")
        b_open.clicked.connect(lambda: self._with_sel(lambda i: open_path(i.files[0].path)))
        b_folder.clicked.connect(lambda: self._with_sel(lambda i: open_folder(i.files[0].path)))
        b_cmp.clicked.connect(lambda: self._with_sel(self._compare))
        b_bom.clicked.connect(lambda: self._with_sel(lambda i: win.show_bom_key(i.key)))
        self.b_fix.clicked.connect(lambda: self._with_sel(lambda i: win.copy_fix(i)))
        self.b_ack.clicked.connect(lambda: win.acknowledge([r["_i"] for r in self.table.selected_rows()]))
        self.b_unack.clicked.connect(lambda: win.unacknowledge([r["_i"] for r in self.table.selected_rows()]))
        self.lay.addLayout(hbox(b_open, b_folder, b_cmp, b_bom, None, self.b_fix, self.b_ack, self.b_unack))
        self.search.textChanged.connect(self._filter)
        self.state.currentIndexChanged.connect(self.refresh)
        self.sev.currentIndexChanged.connect(self._filter)
        self.code.currentIndexChanged.connect(self._filter)
        self.table.doubleClicked.connect(lambda ix: self._open(self.table.row_at(ix)["_i"]))
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._buttons())

    def set_filter(self, sev=None, code=None):
        self.state.setCurrentIndex(0)
        self.sev.setCurrentIndex({"ERROR": 1, "WARN": 2}.get(sev, 0))
        idx = self.code.findData(code) if code else 0
        self.code.setCurrentIndex(max(0, idx))
        self.search.clear()

    def refresh(self):
        cfg = self.win.cfg
        order = {r: n for n, r in enumerate(ROLES)}
        which = ("open", "acked", "all")[self.state.currentIndex()]
        rows = []
        for i in self.win.visible_issues(which):
            a = i.ack or {}
            rows.append({
                "sev": "ACK" if i.ack else i.sev, "_kind:sev": "ACK" if i.ack else i.sev,
                "hull": cfg.ship_label(i.ship), "bom": i.key, "rev": i.rev,
                "folders": " + ".join(ROLE_TITLE[r] for r in sorted(i.roles, key=order.get)),
                "_kind:folders": "ACK" if i.ack else i.sev,
                "title": i.title, "fix": "Copy" if fixer.can_copy(i) and not i.ack else "",
                "_kind:fix": "INFO", "detail": i.detail, "action": i.action,
                "ack_note": f"{a.get('by', '')} · {a.get('at', '')} · {a.get('note', '')}" if i.ack else "",
                "_i": i})
        self.model.set_rows(rows)
        self._filter()

    def _buttons(self):
        sel = [r["_i"] for r in self.table.selected_rows()]
        self.b_fix.setEnabled(len(sel) == 1 and fixer.can_copy(sel[0]) and not sel[0].ack)
        self.b_ack.setEnabled(any(not i.ack for i in sel))
        self.b_unack.setEnabled(any(i.ack for i in sel))

    def _filter(self):
        sev = self.sev.currentText() if self.sev.currentIndex() else None
        code = self.code.currentData()
        self.table.proxy.pred = lambda r: (not sev or r["_i"].sev == sev) and (not code or r["_i"].code == code)
        self.table.proxy.set_text(self.search.text())
        self.count.setText(f"{self.table.proxy.rowCount():,} of {self.model.rowCount():,}")
        self._buttons()

    def _with_sel(self, fn):
        rows = self.table.selected_rows()
        if rows:
            fn(rows[0]["_i"])

    def _compare(self, i):
        fl = [f for f in i.files if f.rows]
        if len(fl) >= 2:
            DiffDialog(fl[0], fl[1], self).exec()
        else:
            self.win.show_bom_key(i.key)

    def _open(self, i):
        if i.code in ("SAME_NAME_DIFF", "WP_CONTENT_DIFF", "CN_CONTENT_DIFF", "SAME_REV_DIFF", "WP_OUTDATED") \
                and len(i.files) >= 2:
            self._compare(i)
        else:
            self.win.show_bom_key(i.key)


class FilesPage(Page):
    title = "File Inventory"
    subtitle = "Every BOM workbook found in the four source folders and how it was classified"
    COLS = [("role", "Source"), ("loc", "Location"), ("hull", "Hull"), ("bom", "BOM"), ("rev", "Rev"),
            ("name", "File name"), ("lines", "Lines"), ("mtime", "Modified"), ("error", "Read problem"),
            ("rel", "Folder")]

    def __init__(self, win):
        super().__init__(win)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search file or folder…")
        self.role = QComboBox()
        self.role.addItems(["All sources", "PROD", "WP", "DCN", "ECN"])
        self.loc = QComboBox()
        self.loc.addItems(["All locations", "ACTIVE", "ARCHIVE", "COMMENT", "STAGING"])
        self.count = label("", "muted")
        self.lay.addLayout(hbox(self.search, self.role, self.loc, self.count))
        self.lay.addWidget(label("ACTIVE = current release folder · ARCHIVE = Arch/old folder · COMMENT = review or "
                                 "mark-up copy (not compared) · STAGING = work-in-progress folder in Prod DWG",
                                 "muted"))
        self.model = DictTableModel(self.COLS, chip_cols=("role", "loc"))
        self.table = DataTable(self.model)
        self.table.on_filter = self._filter
        self.table.set_widths([70, 90, 60, 170, 50, 280, 60, 130, 180])
        self.lay.addWidget(self.table, 1)
        for w in (self.role, self.loc):
            w.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter)
        self.table.doubleClicked.connect(lambda ix: open_path(self.table.row_at(ix)["_f"].path))

    def refresh(self):
        res = self.win.res
        ships = self.win.ship_filter
        cfg = self.win.cfg
        rows = []
        for f in (res.files if res else []):
            if f.ship not in ships:
                continue
            rows.append({"role": f.role, "loc": f.loc, "hull": cfg.ship_label(f.ship), "bom": f.key, "rev": f.rev,
                         "name": f.name, "lines": len(f.rows),
                         "mtime": dt.datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M"),
                         "error": f.error or f.warn, "rel": os.path.dirname(f.rel), "_f": f})
        self.model.set_rows(rows)
        self._filter()

    def _filter(self):
        role = self.role.currentText() if self.role.currentIndex() else None
        loc = self.loc.currentText() if self.loc.currentIndex() else None
        self.table.proxy.pred = lambda r: (not role or r["role"] == role) and (not loc or r["loc"] == loc)
        self.table.proxy.set_text(self.search.text())
        self.count.setText(f"{self.table.proxy.rowCount():,} of {self.model.rowCount():,} files")


class IntegrationPage(Page):
    title = "SAP & Purchasing"
    subtitle = "Next step: match every BOM line with SAP upload status and purchasing status / ETA"

    def __init__(self, win):
        super().__init__(win)
        for key, head, text in (
                ("sap_file", "SAP master file",
                 "Will mark each Master BOM line as Uploaded / Not uploaded / Different in SAP (by Material No. "
                 "and BOM). Fills the 'SAP Upload' column."),
                ("purchase_file", "Purchasing master file",
                 "Will map purchasing status and ETA to each line (by Material No.). Fills the 'Purchase Status' "
                 "and 'ETA' columns.")):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(18, 14, 18, 14)
            cl.addWidget(label(head, "h2"))
            cl.addWidget(label(text, "muted", wrap=True))
            path = QLineEdit(win.cfg.get(key, ""))
            path.setPlaceholderText("Not provided yet")
            pick = QPushButton("Browse…")

            def browse(_=False, p=path, k=key):
                fn, _ = QFileDialog.getOpenFileName(self, "Select file", p.text() or str(Path.home()),
                                                    "Excel (*.xlsx *.xlsm *.xls *.csv)")
                if fn:
                    p.setText(fn)
                    win.cfg[k] = fn
                    win.cfg.save()
            pick.clicked.connect(browse)
            cl.addLayout(hbox(path, pick))
            cl.addWidget(label(f"<span style='color:{theme.WARN}'>● Waiting for file format</span> — comparison "
                               "logic is added once a sample file is available.", wrap=True))
            self.lay.addWidget(card)
        self.lay.addStretch(1)


class MasterCheckPage(Page):
    title = "Master BOM Check · 전장설계 Master BOM 검증"
    subtitle = ("The hand-compiled 전장설계 Master BOM must be identical to what the folders say "
                "(latest 16 Prod DWG BOM per block). Every difference is listed here.")
    MAP_FILTERS = ["All BOMs", "Only BOMs with differences", "Missing in Master", "Not in folders",
                   "Revision differs", "Lines missing / extra", "Values differ", "Matching BOMs"]

    def __init__(self, win):
        super().__init__(win)
        self.chk = None
        self.worker = None
        self._pending = False
        # ---- file
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)
        self.path = QLineEdit(win.cfg.get("master_bom_file", ""))
        self.path.setPlaceholderText("Select the 전장설계 Master BOM file (.xlsx / .xlsm)")
        self.path.editingFinished.connect(self._path_edited)
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._browse)
        self.btn_check = QPushButton("Check now")
        self.btn_check.setObjectName("primary")
        self.btn_check.clicked.connect(lambda: self.run_check(manual=True))
        self.btn_export = QPushButton("Export differences")
        self.btn_export.clicked.connect(self.export)
        cl.addLayout(hbox(label("<b>Master BOM file</b>"), self.path, pick, self.btn_check, self.btn_export))
        self.info = label("", "muted", wrap=True)
        cl.addWidget(self.info)
        self.lay.addWidget(card)
        # ---- KPIs
        row = QHBoxLayout()
        row.setSpacing(12)
        self.cards = {}
        for key, lab, color in (("boms", "BOMs compared", None), ("match", "Identical", theme.OK),
                                ("diff", "BOMs that differ", theme.ERR), ("missing", "Missing in Master", theme.ERR),
                                ("extra", "In Master, not in folders", theme.ERR),
                                ("lines", "Line / value differences", theme.ERR)):
            c = KpiCard(lab, color)
            self.cards[key] = c
            row.addWidget(c)
        self.cards["diff"].clicked.connect(lambda: self._map_filter(1))
        self.cards["missing"].clicked.connect(lambda: self._map_filter(2))
        self.cards["extra"].clicked.connect(lambda: self._map_filter(3))
        self.cards["match"].clicked.connect(lambda: self._map_filter(7))
        self.cards["lines"].clicked.connect(lambda: self.show_diffs())
        self.lay.addLayout(row)
        # ---- body: map | differences
        self.tabs = QTabWidget()
        mapw = QWidget()
        body = QHBoxLayout(mapw)
        body.setContentsMargins(0, 8, 0, 0)
        body.setSpacing(16)
        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 14, 16, 14)
        legend = " ".join(f"<span style='color:{ink}'>■</span> {t}&nbsp;&nbsp;" for ink, t in
                          ((theme.OK, "Same"), (theme.ERR, "Differs"), (theme.NONE, "Not applicable")))
        ll.addLayout(hbox(label("Block map", "h2"), None, label(legend, "muted")))
        ll.addWidget(label("Each tile: <b>B</b> BOM in Master and folders · <b>R</b> revision · <b>L</b> lines "
                           "(missing / extra) · <b>V</b> values (Qty, Unit, Description …)", "muted"))
        self.filter_cb = QComboBox()
        self.filter_cb.addItems(self.MAP_FILTERS)
        self.filter_cb.currentIndexChanged.connect(self._fill_map)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find block, e.g. E410P")
        self.search.textChanged.connect(self._fill_map)
        ll.addLayout(hbox(self.filter_cb, self.search, None))
        self.map_host = QWidget()
        self.map_host.setObjectName("mapHost")
        self.map_host.setStyleSheet(f"QWidget#mapHost{{background:{theme.SURFACE};}}")
        self.map_lay = QVBoxLayout(self.map_host)
        self.map_lay.setContentsMargins(0, 4, 0, 0)
        self.map_lay.setSpacing(10)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.map_host)
        ll.addWidget(sc, 1)
        body.addWidget(left, 3)
        right = QFrame()
        right.setObjectName("card")
        right.setFixedWidth(470)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.addWidget(label("What differs", "h2"))
        rl.addWidget(label("Click a line to list those differences.", "muted"))
        self.kind_host = QVBoxLayout()
        self.kind_host.setSpacing(6)
        rl.addLayout(self.kind_host)
        rl.addStretch(1)
        self.basis_note = label("", "muted", wrap=True)
        rl.addWidget(self.basis_note)
        body.addWidget(right)
        self.tabs.addTab(mapw, "Block map")

        dw = QWidget()
        dl = QVBoxLayout(dw)
        dl.setContentsMargins(0, 8, 0, 0)
        self.d_search = QLineEdit()
        self.d_search.setPlaceholderText("Search BOM, Material No., description…  (space = AND)")
        self.d_kind = QComboBox()
        self.d_kind.addItem("All differences", None)
        for k, (_sev, en, ko, _a) in mc.KINDS.items():
            self.d_kind.addItem(f"{en} / {ko}", k)
        self.d_bom = QComboBox()
        self.d_bom.addItem("All BOMs", None)
        self.d_clear = QPushButton("Clear filters")
        self.d_count = label("", "muted")
        dl.addLayout(hbox(self.d_search, self.d_kind, self.d_bom, self.d_clear, self.d_count))
        self.model = DictTableModel(mc.DIFF_COLS, chip_cols=("sev",))
        self.table = DataTable(self.model)
        self.table.on_filter = self._filter
        self.table.set_widths([75, 60, 170, 230, 150, 60, 230, 130, 170, 170, 130, 110, 400])
        dl.addWidget(self.table, 1)
        self.d_search.textChanged.connect(self._filter)
        self.d_kind.currentIndexChanged.connect(self._filter)
        self.d_bom.currentIndexChanged.connect(self._filter)
        self.d_clear.clicked.connect(self._clear)
        self.tabs.addTab(dw, "Differences")
        self.lay.addWidget(self.tabs, 1)

        # watch the Master file: a newer file is checked automatically
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._watch)
        self.timer.start(60_000)

    # ---- file handling
    def _browse(self):
        start = self.path.text() or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(self, "Select the 전장설계 Master BOM", start,
                                            "Excel (*.xlsx *.xlsm)")
        if fn:
            self.path.setText(fn)
            self._path_edited()

    def _path_edited(self):
        p = self.path.text().strip().strip('"')
        if p != self.win.cfg.get("master_bom_file", ""):
            self.win.cfg["master_bom_file"] = p
            self.win.cfg.save()
            self.run_check()

    def _watch(self):
        p = self.win.cfg.get("master_bom_file", "")
        if self.chk and p and os.path.isfile(p):
            try:
                if os.path.getmtime(p) != self.chk.mtime:
                    self.run_check()
            except OSError:
                pass

    def run_check(self, manual=False):
        """Compare now (in the background). Called after every folder scan and when the file changes."""
        p = self.win.cfg.get("master_bom_file", "")
        if not p:
            if manual:
                self.win.toast("Select the 전장설계 Master BOM file first.")
            self._show_info()
            return
        if not os.path.isfile(p):
            self.info.setText(f"<span style='color:{theme.ERR}'>File not found:</span> {p}")
            return
        if not self.win.res:
            self.info.setText("Scan the folders first — the Master BOM is checked against the scan result.")
            return
        if self.worker and self.worker.isRunning():
            self._pending = True
            return
        res, cfg = self.win.res, self.win.cfg
        self.worker = FuncWorker(lambda prog: mc.check(cfg, res, p, progress=prog))
        self.worker.progress.connect(lambda m: self.info.setText(m))
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.btn_check.setEnabled(False)
        self.info.setText("Checking the Master BOM…")
        self.worker.start()

    def _done(self, chk):
        self.btn_check.setEnabled(True)
        old = self.chk
        self.chk = chk
        self.refresh()
        n = sum(1 for k in chk.keys.values() if k.n_errors)
        if old and old.mtime != chk.mtime:
            self.win.toast(f"New Master BOM file detected and checked — {n} BOMs differ from the folders.")
        if self._pending:
            self._pending = False
            self.run_check()

    def _failed(self, msg):
        self.btn_check.setEnabled(True)
        self.info.setText(f"<span style='color:{theme.ERR}'>Could not read the Master BOM file.</span> "
                          f"{msg.strip().splitlines()[-1][:300]}")

    def _show_info(self):
        chk = self.chk
        if not chk:
            self.info.setText("No check yet. Select the Master BOM file — it is compared automatically after "
                              "each folder scan and whenever the file is saved again.")
            return
        when = dt.datetime.fromtimestamp(chk.checked_at).strftime("%Y-%m-%d %H:%M")
        saved = dt.datetime.fromtimestamp(chk.mtime).strftime("%Y-%m-%d %H:%M")
        scan = dt.datetime.fromtimestamp(self.win.res.scanned_at).strftime("%Y-%m-%d %H:%M") if self.win.res else "–"
        txt = (f"File saved {saved} · {chk.master_rows:,} lines in sheet(s) {', '.join(chk.sheets) or '–'} · "
               f"checked {when} against the folder scan of {scan}")
        if chk.warnings:
            txt += "<br>" + "<br>".join(f"<span style='color:{theme.WARN}'>●</span> {w}" for w in chk.warnings)
        self.info.setText(txt)

    # ---- views
    def _keys(self):
        if not self.chk:
            return []
        ships = self.win.ship_filter
        return [k for k in self.chk.keys.values() if k.ship in ships]

    def refresh(self):
        self._show_info()
        keys = self._keys()
        if not self.chk:
            for c in self.cards.values():
                c.set("–")
        else:
            st = Counter(k.status for k in keys)
            both = [k for k in keys if k.in_folder and k.in_master]
            self.cards["boms"].set(f"{len(keys):,}", f"{sum(1 for k in keys if k.in_folder):,} in folders · "
                                                     f"{sum(1 for k in keys if k.in_master):,} in Master")
            pct = f"{100 * st['Matches'] / len(keys):.0f}% of BOMs" if keys else ""
            self.cards["match"].set(f"{st['Matches']:,}", pct)
            self.cards["diff"].set(f"{st['Differs']:,}", f"of {len(both):,} BOMs in both")
            self.cards["missing"].set(f"{st['Missing in Master']:,}")
            self.cards["extra"].set(f"{st['Not in folders']:,}")
            kinds = Counter(d.kind for k in keys for d in k.diffs)
            n = kinds["LINE_MISSING"] + kinds["LINE_EXTRA"] + kinds["VALUE_DIFF"] + kinds["REV_DIFF"]
            self.cards["lines"].set(f"{n:,}", f"{kinds['LINE_MISSING']:,} missing · {kinds['LINE_EXTRA']:,} extra · "
                                              f"{kinds['VALUE_DIFF']:,} values")
        self._fill_map()
        self._fill_kinds(keys)
        rows = [mc.diff_row(d, self.win.cfg, k) for k in sorted(keys, key=lambda k: k.key) for d in k.diffs]
        self.model.set_rows(rows)
        cur = self.d_bom.currentData()
        self.d_bom.blockSignals(True)
        self.d_bom.clear()
        self.d_bom.addItem("All BOMs", None)
        for k in sorted(k.key for k in keys if k.diffs):
            self.d_bom.addItem(k, k)
        i = self.d_bom.findData(cur)
        self.d_bom.setCurrentIndex(max(0, i))
        self.d_bom.blockSignals(False)
        self._filter()

    def _map_filter(self, i):
        self.tabs.setCurrentIndex(0)
        self.filter_cb.setCurrentIndex(i)

    def _fill_map(self):
        for i in reversed(range(self.map_lay.count())):
            it = self.map_lay.takeAt(i)
            if it.widget():
                it.widget().deleteLater()
        keys = self._keys()
        if not self.chk:
            self.map_lay.addWidget(label("No check yet.", "muted"))
            return
        has = lambda *kinds: (lambda k: any(d.kind in kinds for d in k.diffs))  # noqa: E731
        pred = [lambda k: True, lambda k: k.n_errors > 0, lambda k: k.status == "Missing in Master",
                lambda k: k.status == "Not in folders", has("REV_DIFF"), has("LINE_MISSING", "LINE_EXTRA"),
                has("VALUE_DIFF"), lambda k: k.status == "Matches"][self.filter_cb.currentIndex()]
        q = self.search.text().strip().upper()
        groups = defaultdict(list)
        for k in keys:
            if pred(k) and (not q or q in k.key):
                groups[(k.ship, k.group)].append(k)
        multi = len({s for s, _ in groups}) > 1
        for (ship, g), kl in sorted(groups.items()):
            n_bad = sum(1 for k in kl if k.n_errors)
            head = f"<b>{g}-blocks</b>" + (f" · {self.win.cfg.ship_label(ship)}" if multi else "") + \
                   f"  <span style='color:{theme.MUTED}'>{len(kl)} BOMs" + \
                   (f" · <span style='color:{theme.ERR}'>{n_bad} differ</span>" if n_bad else "") + "</span>"
            self.map_lay.addWidget(label(head))
            host = QWidget()
            fl = FlowLayout(host, spacing=6)
            for k in sorted(kl, key=lambda k: (k.block, k.phase, k.disc)):
                t = CheckTile(k)
                t.clicked.connect(lambda _=False, key=k.key: self.show_diffs(bom=key))
                fl.addWidget(t)
            self.map_lay.addWidget(host)
        if not groups:
            self.map_lay.addWidget(label("No BOMs match the filter.", "muted"))
        self.map_lay.addStretch(1)

    def _fill_kinds(self, keys):
        for i in reversed(range(self.kind_host.count())):
            it = self.kind_host.takeAt(i)
            if it.widget():
                it.widget().deleteLater()
        if not self.chk:
            return
        cnt = Counter(d.kind for k in keys for d in k.diffs)
        boms = defaultdict(set)
        for k in keys:
            for d in k.diffs:
                boms[d.kind].add(k.key)
        mx = max([n for kd, n in cnt.items() if kd != "DELETED_OMITTED"], default=1)
        for kind, (sev, en, ko, _a) in mc.KINDS.items():
            n = cnt[kind]
            if not n:
                continue
            ink, soft = theme.SEV_COLORS[sev]
            frac = min(1.0, n / mx)
            b = QPushButton()
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{text-align:left;border:none;border-radius:6px;padding:6px 8px;"
                            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {soft},"
                            f"stop:{max(0.02, frac):.3f} {soft},stop:{min(1, frac + 0.001):.3f} transparent);}}"
                            f"QPushButton:hover{{border:1px solid {ink};}}")
            b.setText(f"{n:>5}   {en} / {ko}  · {len(boms[kind])} BOMs")
            b.setToolTip(mc.KINDS[kind][3])
            b.clicked.connect(lambda _=False, kd=kind: self.show_diffs(kind=kd))
            self.kind_host.addWidget(b)
        if not any(n for kd, n in cnt.items() if kd != "DELETED_OMITTED"):
            self.kind_host.addWidget(label(f"<span style='color:{theme.OK}'>The Master BOM matches the folders."
                                           "</span>"))
        sis = sorted({k.ship for k in keys if k.basis and k.basis != "Prod DWG"})
        self.basis_note.setText(
            ("Note: " + ", ".join(self.win.cfg.ship_label(s) for s in sis) +
             " have no own Prod DWG BOMs; their Master BOM lines are checked against "
             f"{self.win.cfg.ship_label(self.win.cfg['baseline_ship'])} Prod DWG. Ship No. is not compared.")
            if sis else "")

    def show_diffs(self, kind=None, bom=None):
        self.d_kind.setCurrentIndex(max(0, self.d_kind.findData(kind)))
        self.d_bom.setCurrentIndex(max(0, self.d_bom.findData(bom)))
        self.tabs.setCurrentIndex(1)
        self._filter()

    def _clear(self):
        self.d_search.clear()
        self.d_kind.setCurrentIndex(0)
        self.d_bom.setCurrentIndex(0)
        self.table.clear_filters()

    def _filter(self):
        kind, bom = self.d_kind.currentData(), self.d_bom.currentData()
        hide_info = kind != "DELETED_OMITTED"
        self.table.proxy.pred = lambda r: ((not kind or r["_kind"] == kind) and (not bom or r["_key"] == bom)
                                           and not (hide_info and r["_kind"] == "DELETED_OMITTED"))
        self.table.proxy.set_text(self.d_search.text())
        self.d_count.setText(f"{self.table.proxy.rowCount():,} of {self.model.rowCount():,} differences")

    def export(self):
        if not self.chk:
            self.win.toast("Run the check first.")
            return
        ships = sorted(self.win.ship_filter)
        tag = "-".join(self.win.cfg.ship_label(s) for s in ships) if len(ships) < len(self.win.cfg["ships"]) else "All"
        default = Path.home() / "Documents" / f"MasterBOM_Check_{tag}_{dt.date.today():%Y%m%d}.xlsx"
        fn, _ = QFileDialog.getSaveFileName(self, "Export differences", str(default), "Excel workbook (*.xlsx)")
        if not fn:
            return
        try:
            build_master_check_report(self.win.cfg, self.chk, fn, ships)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, APP_NAME, f"Could not write the report:\n\n{e}")
            return
        self.win.toast(f"Report saved: {fn}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(fn))


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Source folders and classification rules"

    def __init__(self, win):
        super().__init__(win)
        cfg = win.cfg
        card = QFrame()
        card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        self.base = QLineEdit(cfg["base"])
        self.roots = {r: QLineEdit(cfg["roots"][r]) for r in ("PROD", "WP", "DCN", "ECN")}
        self.arch = QLineEdit(", ".join(cfg["archive_tokens"]))
        self.comm = QLineEdit(", ".join(cfg["comment_tokens"]))
        self.stag = QLineEdit(", ".join(cfg["prod_staging_folders"]))
        self.skip = QLineEdit(", ".join(cfg["skip_name_tokens"]))
        self.base_ship = QLineEdit(cfg["baseline_ship"])
        self.exempt = QLineEdit(", ".join(cfg["dup_exempt_status"]))
        self.ignore = QLineEdit(", ".join(cfg["compare_ignore_fields"]))
        self.mc_ignore = QLineEdit(", ".join(cfg.get("master_check_ignore", [])))
        self.mc_ignore.setPlaceholderText("field ids, e.g. release_date, weight  (Ship No. is never compared)")
        self.upd = QLineEdit(cfg["update_dir"])
        self.ackf = QLineEdit(cfg.get("ack_file", ""))
        self.ackf.setPlaceholderText(f"empty = this PC only ({acks.ack_path(cfg)})")
        self.workers = QSpinBox()
        self.workers.setRange(1, 32)
        self.workers.setValue(int(cfg["workers"]))
        form.addRow("Project folder", self.base)
        for r, t in (("PROD", "Prod DWG folder"), ("WP", "Work Package folder"), ("DCN", "DCN folder"),
                     ("ECN", "ECN folder")):
            form.addRow(t, self.roots[r])
        form.addRow("Archive folder words", self.arch)
        form.addRow("Review / mark-up words", self.comm)
        form.addRow("Prod DWG work-in-progress folders", self.stag)
        form.addRow("Not-a-BOM file words", self.skip)
        form.addRow("Baseline hull (Ship No.)", self.base_ship)
        form.addRow("Material status allowed to repeat", self.exempt)
        form.addRow("Columns ignored in comparison", self.ignore)
        form.addRow("Columns ignored in Master BOM check", self.mc_ignore)
        form.addRow("Update folder", self.upd)
        form.addRow("Acknowledged alarms file (share with team)", self.ackf)
        form.addRow("Parallel readers", self.workers)
        self.lay.addWidget(card)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        clear = QPushButton("Clear file cache")
        clear.clicked.connect(self.clear_cache)
        log = QPushButton("Open copy log")
        log.setToolTip(str(fixer.log_path()))
        log.clicked.connect(lambda: open_path(str(fixer.log_path())) if fixer.log_path().exists()
                            else self.win.toast("No copies made yet."))
        self.lay.addLayout(hbox(save, clear, log, None))
        self.lay.addWidget(label(f"Settings file: {Config.path}<br>Cache: {cache_dir()}", "muted"))
        self.lay.addStretch(1)

    @staticmethod
    def _list(w):
        return [x.strip() for x in w.text().split(",") if x.strip()]

    def save(self):
        cfg = self.win.cfg
        cfg["base"] = self.base.text().strip()
        for r, w in self.roots.items():
            cfg["roots"][r] = w.text().strip()
        cfg["archive_tokens"] = [x.lower() for x in self._list(self.arch)]
        cfg["comment_tokens"] = [x.lower() for x in self._list(self.comm)]
        cfg["prod_staging_folders"] = self._list(self.stag)
        cfg["skip_name_tokens"] = [x.lower() for x in self._list(self.skip)]
        cfg["baseline_ship"] = self.base_ship.text().strip()
        cfg["dup_exempt_status"] = self._list(self.exempt)
        cfg["compare_ignore_fields"] = self._list(self.ignore)
        cfg["master_check_ignore"] = self._list(self.mc_ignore)
        cfg["update_dir"] = self.upd.text().strip()
        cfg["ack_file"] = self.ackf.text().strip()
        cfg["workers"] = self.workers.value()
        cfg.save()
        self.win.toast("Settings saved. Run a new scan to apply them.")

    def clear_cache(self):
        p = cache_dir() / "bomcache.sqlite"
        try:
            p.unlink()
            self.win.toast("Cache cleared — the next scan re-reads every file.")
        except OSError as e:
            self.win.toast(f"Could not clear cache: {e}")


# ---------------------------------------------------------------- window
class MainWindow(QMainWindow):
    PAGES = [("dash", "Dashboard", DashboardPage), ("master", "Master BOM", MasterPage),
             ("sync", "Sync Matrix", SyncPage), ("issues", "Action List", IssuesPage),
             ("mcheck", "Master BOM Check", MasterCheckPage),
             ("files", "File Inventory", FilesPage), ("integr", "SAP & Purchasing", IntegrationPage),
             ("settings", "Settings", SettingsPage)]

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.res = None
        self.worker = None
        self.ship_filter = set(cfg["ships"])
        self.setWindowTitle(f"{APP_NAME}  v{VERSION}")
        self.resize(1500, 920)

        root = QWidget()
        rl = QHBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        nav = QWidget()
        nav.setObjectName("nav")
        nav.setFixedWidth(210)
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        nl.addWidget(label("BOM Master", "brand"))
        nl.addWidget(label("Electrical · Aloha-L 040–042", "brandSub"))
        self.nav_group = QButtonGroup(self)
        self.nav_btn = {}
        for key, text, _ in self.PAGES:
            b = QPushButton(text.replace("&", "&&"))
            b.setObjectName("navBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.nav_to(k))
            self.nav_group.addButton(b)
            self.nav_btn[key] = b
            nl.addWidget(b)
        nl.addStretch(1)
        self.nav_foot = label(f"v{VERSION}", "navFoot")
        nl.addWidget(self.nav_foot)
        rl.addWidget(nav)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = QWidget()
        top.setObjectName("topbar")
        tl = QGridLayout(top)
        tl.setContentsMargins(24, 14, 24, 12)
        tl.setHorizontalSpacing(12)
        self.page_title = label("", "pageTitle")
        self.page_sub = label("", "muted")
        tl.addWidget(self.page_title, 0, 0)
        tl.addWidget(self.page_sub, 1, 0)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.hull_btns = {}
        hb_group = QButtonGroup(self)
        for code in ["ALL"] + list(cfg["ships"]):
            b = QPushButton("All hulls" if code == "ALL" else cfg.ship_label(code))
            b.setObjectName("seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, c=code: self.set_hull(c))
            hb_group.addButton(b)
            self.hull_btns[code] = b
            seg.addWidget(b)
        self.hull_btns["ALL"].setChecked(True)
        tl.addLayout(seg, 0, 1, 2, 1, Qt.AlignVCenter)
        self.btn_export = QPushButton("Export report")
        self.btn_export.clicked.connect(self.export)
        self.btn_scan = QPushButton("Scan folders")
        self.btn_scan.setObjectName("primary")
        self.btn_scan.clicked.connect(self.scan)
        tl.addWidget(self.btn_export, 0, 2, 2, 1, Qt.AlignVCenter)
        tl.addWidget(self.btn_scan, 0, 3, 2, 1, Qt.AlignVCenter)
        tl.setColumnStretch(0, 1)
        ml.addWidget(top)

        status = QWidget()
        status.setObjectName("topbar")
        sl = QHBoxLayout(status)
        sl.setContentsMargins(24, 4, 24, 6)
        self.status = label("", "muted")
        self.bar = QProgressBar()
        self.bar.setFixedWidth(260)
        self.bar.setTextVisible(False)
        self.bar.hide()
        sl.addWidget(self.status, 1)
        sl.addWidget(self.bar)
        ml.addWidget(status)

        self.stack = QStackedWidget()
        self.pages = {}
        for key, _, cls in self.PAGES:
            p = cls(self)
            self.pages[key] = p
            self.stack.addWidget(p)
        ml.addWidget(self.stack, 1)
        rl.addWidget(main, 1)
        self.setCentralWidget(root)
        self.nav_to("dash")
        self._load_last()

    # ---- state
    def visible_keys(self):
        if not self.res:
            return []
        return [k for k in self.res.keys.values() if k.ship in self.ship_filter]

    def visible_issues(self, which="open"):
        """which: 'open' (default — what needs attention), 'acked' (known minor alarms) or 'all'."""
        if not self.res:
            return []
        out = [i for i in self.res.issues if i.ship in self.ship_filter]
        if which == "open":
            return [i for i in out if not i.ack]
        if which == "acked":
            return [i for i in out if i.ack]
        return out

    # ---- acknowledge / copy-to-fix (all return True when the data changed)
    def _reapply(self, ack_data=None):
        apply_acks(self.cfg, self.res, ack_data if ack_data is not None else acks.load(self.cfg))
        self._save_result()
        self.refresh_all()

    def acknowledge(self, issues, parent=None):
        issues = [i for i in issues if not i.ack]
        if not issues:
            return False
        dlg = AckDialog(issues, parent or self)
        if not dlg.exec():
            return False
        try:
            data = acks.acknowledge(self.cfg, issues, dlg.text())
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save the acknowledgement:\n{e}")
            return False
        self._reapply(data)
        self.toast(f"{len(issues)} alarm(s) acknowledged as minor — see Action List → Acknowledged.")
        return True

    def unacknowledge(self, issues):
        issues = [i for i in issues if i.ack]
        if not issues:
            return False
        try:
            data = acks.unacknowledge(self.cfg, issues)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not save:\n{e}")
            return False
        self._reapply(data)
        self.toast(f"{len(issues)} alarm(s) moved back to the open list.")
        return True

    def copy_fix(self, issue, parent=None):
        plan = fixer.plan_copy(self.cfg, self.res, issue)
        if plan is None:
            QMessageBox.information(parent or self, APP_NAME,
                                    "This problem cannot be fixed by copying a file.\n"
                                    "(Copy-to-fix covers files missing or outdated in 16 Prod DWG / "
                                    "17 Work Packages. S041/S042 are not copied from S040.)")
            return False
        dlg = CopyDialog(plan, parent or self)
        if not dlg.exec():
            return False
        try:
            new, moved = fixer.execute(self.cfg, plan, dlg.dest_dir, dlg.archive_old)
        except OSError as e:
            QMessageBox.warning(parent or self, APP_NAME, str(e))
            return False
        files = [moved if (moved and f is plan.old) else f for f in self.res.files] + [new]
        res = analyze(self.cfg, files, self.res.others, self.res.scan_errors)
        res.scanned_at = self.res.scanned_at
        self.res = res
        self._reapply()
        QMessageBox.information(parent or self, APP_NAME,
                                f"Copied.\n\n{new.path}" + (f"\n\nMoved to Arch:\n{moved.path}" if moved else "") +
                                "\n\nThe checks have been updated.")
        return True

    def _save_result(self):
        try:
            with open(cache_dir() / RESULT_FILE, "wb") as fh:
                pickle.dump(self.res, fh)
        except OSError:
            pass

    def set_hull(self, code):
        self.ship_filter = set(self.cfg["ships"]) if code == "ALL" else {code}
        self.refresh_all()

    def refresh_all(self):
        for p in self.pages.values():
            p.refresh()
        self._status_text()

    def _status_text(self):
        if self.res:
            when = dt.datetime.fromtimestamp(self.res.scanned_at).strftime("%Y-%m-%d %H:%M")
            self.status.setText(f"Last scan {when}  ·  {len(self.res.files):,} BOM files  ·  "
                                f"{len(self.res.keys):,} BOMs  ·  {len(self.res.master):,} lines  ·  "
                                f"source {self.cfg['base']}")
        else:
            self.status.setText("No scan yet.")

    def nav_to(self, key):
        self.nav_btn[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.page_title.setText(page.title)
        self.page_sub.setText(page.subtitle)

    def goto_sync(self, role):
        self.pages["sync"].set_folder_filter(2 + ROLES.index(role))
        self.nav_to("sync")

    def goto_issues(self, sev=None, code=None):
        self.pages["issues"].set_filter(sev, code)
        self.nav_to("issues")

    def show_bom_key(self, key):
        ks = self.res.keys.get(key) if self.res else None
        if ks:
            self.show_bom(ks)

    def show_bom(self, ks):
        BomDetailDialog(ks, self).exec()

    def toast(self, msg):
        self.status.setText(msg)
        QTimer.singleShot(6000, self._status_text)

    # ---- scan
    def _load_last(self):
        p = cache_dir() / RESULT_FILE
        if p.exists():
            try:
                with open(p, "rb") as fh:
                    self.res = pickle.load(fh)
            except Exception:  # noqa: BLE001 - stale pickle from an older version
                self.res = None
        if self.res:
            try:
                apply_acks(self.cfg, self.res, acks.load(self.cfg))   # others may have acknowledged meanwhile
            except Exception:  # noqa: BLE001 - result from an older version: rescan
                self.res = None
        self.refresh_all()
        if not self.res:
            QTimer.singleShot(300, self.scan)
        else:
            QTimer.singleShot(500, self.pages["mcheck"].run_check)

    def scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.btn_scan.setText("Cancelling…")
            return
        if not os.path.isdir(self.cfg["base"]):
            QMessageBox.warning(self, APP_NAME, f"The project folder is not reachable:\n{self.cfg['base']}\n\n"
                                                "Check the N: drive connection or the path in Settings.")
            return
        self.worker = ScanWorker(self.cfg)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._scan_done)
        self.worker.failed.connect(self._scan_failed)
        self.btn_scan.setText("Cancel scan")
        self.btn_export.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.worker.start()

    def _progress(self, msg, done, total):
        self.status.setText(msg)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        else:
            self.bar.setRange(0, 0)

    def _scan_finished_ui(self):
        self.bar.hide()
        self.btn_scan.setText("Scan folders")
        self.btn_export.setEnabled(True)

    def _scan_done(self, res):
        self._scan_finished_ui()
        self.res = res
        self._reapply()
        n_open = sum(1 for i in res.issues if not i.ack)
        self.pages["mcheck"].run_check()
        self.toast(f"Scan complete — {n_open:,} open issues in {len(res.keys):,} BOMs "
                   f"({len(res.issues) - n_open} acknowledged).")

    def _scan_failed(self, msg):
        self._scan_finished_ui()
        self._status_text()
        if "cancelled" not in msg:
            QMessageBox.critical(self, APP_NAME, f"The scan failed:\n\n{msg[-1500:]}")

    # ---- export
    def export(self):
        if not self.res:
            return
        ships = sorted(self.ship_filter)
        tag = "-".join(self.cfg.ship_label(s) for s in ships) if len(ships) < len(self.cfg["ships"]) else "All"
        default = Path.home() / "Documents" / f"BOM_Consistency_{tag}_{dt.date.today():%Y%m%d}.xlsx"
        fn, _ = QFileDialog.getSaveFileName(self, "Export report", str(default), "Excel workbook (*.xlsx)")
        if not fn:
            return
        self.btn_export.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        w = FuncWorker(lambda prog: build_report(self.cfg, self.res, fn, ships, progress=prog))
        w.progress.connect(lambda m: self.status.setText(f"Writing report… {m}"))

        def ok(path):
            self.bar.hide()
            self.btn_export.setEnabled(True)
            self.toast(f"Report saved: {path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

        def bad(msg):
            self.bar.hide()
            self.btn_export.setEnabled(True)
            QMessageBox.critical(self, APP_NAME, f"Could not write the report:\n\n{msg[-1500:]}")
        w.done.connect(ok)
        w.failed.connect(bad)
        self._export_worker = w
        w.start()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(e)
