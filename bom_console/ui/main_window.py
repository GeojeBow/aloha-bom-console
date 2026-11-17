"""메인 창: 상단 파일 상태 + 단계별 화면 + 자동 감시."""
from __future__ import annotations

import datetime as dt
import traceback

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import APP_TITLE, __version__, engine, report
from ..compare import STAGES
from ..config import SOURCE_LABELS, SOURCES, save_config
from .dashboard import Dashboard
from .detail import Detail
from .deviations import Deviations
from .settings import SettingsDialog
from .theme import C
from .widgets import Toast, label

SRC_COLORS = {"design": C["design"], "sap": C["sap"], "purchase": C["purchase"]}


class _Signals(QObject):
    done = Signal(object, object)   # RunResult, hist_data
    failed = Signal(str)


class RunJob(QRunnable):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.sig = _Signals()

    def run(self):
        try:
            res = engine.run(self.cfg, record=True)
            self.sig.done.emit(res, load_hist(self.cfg, res))
        except Exception:
            self.sig.failed.emit(traceback.format_exc())


def load_hist(cfg, res) -> dict:
    if not res.ok:
        return {}
    h = engine.history_for(cfg, res.demo)
    try:
        today = dt.date.today().isoformat()
        out = {"prev": {}, "series": {}, "reports": h.report_days(), "arrivals": h.file_days(),
               "since": h.since_last_report(), "info": h.item_info()}
        for hull in res.comparison.hulls():
            for s in STAGES:
                out["prev"][(hull, s)] = h.previous_total(s, hull, today)
        for hull in [""] + res.comparison.hulls():
            out["series"][hull] = {s: h.daily_series(s, hull or None, days=90) for s in STAGES}
        return out
    finally:
        h.close()


class SourceChip(QFrame):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.setStyleSheet(f"QFrame{{border:1px solid {C['line']};border-radius:8px;background:{C['panel']}}}"
                           "QLabel{border:none;background:transparent}")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 5, 10, 5)
        h.setSpacing(6)
        h.addWidget(label("●", color=SRC_COLORS[source], size=9))
        v = QVBoxLayout()
        v.setSpacing(0)
        self.name = label(SOURCE_LABELS[source] + (" (기준)" if source == "design" else ""), bold=True, size=9)
        self.meta = label("–", muted=True, size=8.5)
        v.addWidget(self.name)
        v.addWidget(self.meta)
        h.addLayout(v)

    def set_file(self, f, stale_days, is_new=False):
        if not f:
            self.meta.setText("<span style='color:%s'>파일 없음</span>" % C["bad"])
            self.setToolTip("")
            return
        age = f.age_days()
        when = f.modified.strftime("%m-%d %H:%M")
        tag = ""
        if is_new:
            tag = f" <b style='color:{C['ok']}'>새 파일</b>"
        elif age >= stale_days:
            tag = f" <b style='color:{C['warn']}'>{int(age)}일 전</b>"
        name = f.path.name if len(f.path.name) <= 28 else f.path.name[:25] + "…"
        self.meta.setText(f"{name} · {when}{tag}")
        self.setToolTip(str(f.path))


class MainWindow(QMainWindow):
    def __init__(self, cfg, icon: QIcon | None = None):
        super().__init__()
        self.cfg = cfg
        self.res = None
        self.hist = {}
        self.running = False
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle(f"{APP_TITLE}  v{__version__}")
        if icon:
            self.setWindowIcon(icon)
        self.resize(1400, 900)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._topbar(icon))
        self.crumbs = QFrame()
        self.crumbs.setObjectName("Crumbs")
        self.crumb_lay = QHBoxLayout(self.crumbs)
        self.crumb_lay.setContentsMargins(20, 6, 20, 6)
        v.addWidget(self.crumbs)
        self.banner_box = QVBoxLayout()
        self.banner_box.setContentsMargins(20, 10, 20, 0)
        self.banner_box.setSpacing(6)
        v.addLayout(self.banner_box)
        self.stack = QStackedWidget()
        self.dash = Dashboard()
        self.devs = Deviations()
        self.detail = Detail()
        self.loading = label("세 파일을 읽고 비교하는 중입니다…", muted=True, size=12)
        self.loading.setAlignment(Qt.AlignCenter)
        for w in (self.loading, self.dash, self.devs, self.detail):
            self.stack.addWidget(w)
        v.addWidget(self.stack, 1)
        self.toast = Toast(root)
        self.dash.open_list.connect(self.open_list)
        self.devs.open_detail.connect(self.open_detail)
        self.detail.back.connect(lambda: self.go(1))

        self.timer = QTimer(self, timeout=self.check_files)
        self.timer.start(max(1, self.cfg.scan_minutes) * 60_000)
        self.level = 0
        self._render_crumbs()
        QTimer.singleShot(50, self.refresh)

    # ------------------------------------------------------------------
    def _topbar(self, icon):
        bar = QFrame()
        bar.setObjectName("TopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 20, 10)
        h.setSpacing(12)
        if icon:
            ic = QLabel()
            ic.setPixmap(icon.pixmap(36, 36))
            h.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(label(APP_TITLE, size=13, bold=True))
        self.watch = label("", muted=True, size=8.5)
        self.watch.setTextFormat(Qt.RichText)
        tv.addWidget(self.watch)
        h.addLayout(tv)
        h.addStretch(1)
        self.chips = {s: SourceChip(s) for s in SOURCES}
        for i, s in enumerate(SOURCES):
            if i:
                h.addWidget(label("→", muted=True))
            h.addWidget(self.chips[s])
        h.addSpacing(10)
        b = QPushButton("다시 비교")
        b.clicked.connect(self.refresh)
        h.addWidget(b)
        b = QPushButton("엔지니어 리포트")
        b.setProperty("primary", True)
        b.clicked.connect(self.make_report)
        h.addWidget(b)
        b = QPushButton("설정")
        b.clicked.connect(self.open_settings)
        h.addWidget(b)
        return bar

    def _set_watch(self, text_extra=""):
        now = dt.datetime.now().strftime("%H:%M")
        dot = f"<span style='color:{C['ok']}'>●</span>"
        self.watch.setText(f"{dot} 폴더 자동 감시 중 · {self.cfg.scan_minutes}분 간격 · 마지막 확인 {now}{text_extra}")

    # ------------------------------------------------------------------
    def go(self, level):
        self.level = level
        self.stack.setCurrentIndex(level + 1)
        self._render_crumbs()

    def _render_crumbs(self):
        while self.crumb_lay.count():
            w = self.crumb_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        parts = [("대시보드", 0)]
        if self.level >= 1:
            parts.append((self.devs.crumb(), 1))
        if self.level >= 2 and self.detail.row:
            parts.append((self.detail.row.ref.item_no or self.detail.row.ref.code, 2))
        for i, (txt, lv) in enumerate(parts):
            if i:
                self.crumb_lay.addWidget(label("›", muted=True))
            if lv == self.level:
                self.crumb_lay.addWidget(label(txt, bold=True))
            else:
                b = QPushButton(txt)
                b.setProperty("link", True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, x=lv: self.go(x))
                self.crumb_lay.addWidget(b)
        self.crumb_lay.addStretch(1)

    def open_list(self, hull, stage, cat, area):
        self.devs.open_with(hull, stage, cat, area)
        self.go(1)

    def open_detail(self, row):
        self.detail.set_row(row, self.hist.get("info", {}))
        self.go(2)

    # ------------------------------------------------------------------
    def refresh(self):
        if self.running:
            return
        self.running = True
        if not self.res:
            self.stack.setCurrentIndex(0)
        self._set_watch(" · <b>비교 중…</b>")
        job = RunJob(self.cfg)
        job.sig.done.connect(self._on_done)
        job.sig.failed.connect(self._on_fail)
        self.pool.start(job)

    def _on_fail(self, tb):
        self.running = False
        self._set_watch()
        QMessageBox.critical(self, "비교 중 오류", "비교 중 오류가 났습니다.\n\n" + tb[-1500:])

    def _on_done(self, res, hist):
        first = self.res is None
        prev = self.res
        self.running = False
        self.res, self.hist = res, hist
        self._set_watch()
        for s in SOURCES:
            self.chips[s].set_file(res.files.get(s), self.cfg.stale_days, s in res.new_files and not first)
        self._banners()
        if not res.ok:
            self.stack.setCurrentIndex(0)
            self.loading.setText("비교할 수 없습니다.\n\n" + "\n".join(res.errors) +
                                 "\n\n오른쪽 위 '설정'에서 세 파일의 폴더를 지정해 주세요.")
            return
        self.dash.set_data(res, hist)
        self.devs.set_data(res.comparison, hist.get("info", {}))
        if self.level == 2 and self.detail.row:
            row = next((r for r in res.comparison.rows if r.key == self.detail.row.key), None)
            if row:
                self.detail.set_row(row, hist.get("info", {}))
            else:
                self.level = 1
        self.go(self.level)
        if prev and prev.ok and res.new_files:
            names = ", ".join(SOURCE_LABELS[s] for s in res.new_files)
            before = sum(prev.comparison.stage_stats(None, s)["dev"] for s in STAGES)
            after = sum(res.comparison.stage_stats(None, s)["dev"] for s in STAGES)
            d = after - before
            self.toast.show_message(f"<b>새 파일 감지: {names}</b><br>자동으로 다시 비교했습니다. 차이 "
                                    f"{'−' if d < 0 else '+'}{abs(d):,}건. 화면과 리포트가 새 파일 기준으로 바뀌었습니다.")

    def _banners(self):
        while self.banner_box.count():
            w = self.banner_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        res = self.res
        msgs = []
        if res.demo:
            msgs.append(("info", "<b>예시 데이터로 보는 중입니다.</b> 설정에서 세 파일의 폴더를 지정하면 실제 파일로 바뀝니다.", "폴더 지정"))
        if not self.cfg.area_rules_confirmed and not res.demo:
            msgs.append(("warn", "블록 → 구역 규칙이 기본값(추정)입니다. 엔지니어별 리포트가 정확하려면 설정 > 구역 규칙에서 확인해 주세요.", "구역 규칙 확인"))
        warns = res.warnings
        if warns:
            more = f" 외 {len(warns) - 2}건" if len(warns) > 2 else ""
            msgs.append(("warn", "<br>".join(warns[:2]) + more, None))
        for kind, text, btn in msgs:
            f = QFrame()
            f.setObjectName("InfoBanner" if kind == "info" else "Banner")
            h = QHBoxLayout(f)
            h.setContentsMargins(12, 8, 12, 8)
            lb = label(text, wrap=True, size=9)
            lb.setTextFormat(Qt.RichText)
            lb.setStyleSheet("background:transparent;border:none")
            h.addWidget(lb, 1)
            if btn:
                b = QPushButton(btn)
                b.clicked.connect(self.open_settings)
                h.addWidget(b)
            self.banner_box.addWidget(f)

    # ------------------------------------------------------------------
    def check_files(self):
        """주기 감시: 폴더의 최신 파일이 바뀌었으면 다시 비교."""
        if self.running:
            return
        if self.res and self.res.at.date() != dt.date.today():
            self.refresh()  # 자정을 넘기면 오늘 날짜로 한 번 더 기록
            return
        files, _ = engine.scan(self.cfg)
        cur = {s: f.signature if f else None for s, f in (self.res.files.items() if self.res else [])}
        new = {s: f.signature if f else None for s, f in files.items()}
        if cur != new:
            self.refresh()
        else:
            self._set_watch()

    def make_report(self):
        if not self.res or not self.res.ok:
            QMessageBox.information(self, "리포트", "비교 결과가 없어 리포트를 만들 수 없습니다.")
            return
        # 리포트 직전에 폴더를 다시 확인: 더 새 파일이 있으면 먼저 재비교
        files, _ = engine.scan(self.cfg)
        if {s: f.signature if f else None for s, f in files.items()} != \
           {s: f.signature if f else None for s, f in self.res.files.items()}:
            QMessageBox.information(self, "새 파일 발견", "폴더에 더 새로운 파일이 있습니다. 먼저 새 파일로 다시 비교한 뒤 리포트를 만들어 주세요.")
            self.refresh()
            return
        box = QMessageBox(self)
        box.setWindowTitle("엔지니어 리포트")
        n = sum(1 for r in self.res.comparison.rows if r.has_dev())
        box.setText(f"follow-up 항목 {n:,}건으로 리포트를 만듭니다.\n받는 사람: ER / Accommodation / On-deck 구역 담당 엔지니어")
        one = box.addButton("한 파일 (구역별 시트)", QMessageBox.AcceptRole)
        split = box.addButton("구역별 파일로 나누기 (메일 첨부용)", QMessageBox.AcceptRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (one, split):
            return
        h = engine.history_for(self.cfg, self.res.demo)
        try:
            out = self.cfg.report_path
            paths = report.write_report(self.res.comparison, out, {s: str(f.path) for s, f in self.res.files.items()},
                                        h.item_info(), h.since_last_report(), split=box.clickedButton() is split)
            h.record_report(";".join(map(str, paths)), report.report_keys(self.res.comparison))
        except PermissionError:
            QMessageBox.warning(self, "저장 실패", "리포트 파일을 저장할 수 없습니다. 같은 이름의 파일이 엑셀에서 열려 있는지 확인해 주세요.")
            return
        finally:
            h.close()
        self.toast.show_message(f"<b>리포트를 만들었습니다</b><br>{out}<br>" + "<br>".join(p.name for p in paths))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))
        self.refresh()

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self.res, self)
        if dlg.exec():
            self.cfg = dlg.cfg
            save_config(self.cfg)
            self.timer.start(max(1, self.cfg.scan_minutes) * 60_000)
            self.res = None
            self.level = 0
            self.refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 24)
