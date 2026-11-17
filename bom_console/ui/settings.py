"""설정 화면: 폴더, 저장 위치, 열 이름 별칭, 블록 → 구역 규칙."""
from __future__ import annotations

import copy

from PySide6.QtCore import QDir, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..compare import classify_area
from ..config import AREA_LABELS, AREAS, FIELD_LABELS, SOURCE_LABELS, SOURCES, UNASSIGNED, AppConfig
from .theme import AREA_COLORS, C
from .widgets import label


def path_row(edit: QLineEdit, parent, file_mode=False):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QPushButton("찾아보기")

    def pick():
        if file_mode:
            p, _ = QFileDialog.getSaveFileName(parent, "이력 파일 위치", edit.text() or "history.sqlite",
                                               "SQLite (*.sqlite *.db)")
        else:
            p = QFileDialog.getExistingDirectory(parent, "폴더 선택", edit.text())
        if p:
            edit.setText(QDir.toNativeSeparators(p))
    b.clicked.connect(pick)
    h.addWidget(b)
    return w


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, last_run=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(860, 620)
        self.cfg = copy.deepcopy(cfg)
        self.last_run = last_run
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        tabs.addTab(self._folders(), "파일 폴더")
        tabs.addTab(self._areas(), "구역 규칙")
        tabs.addTab(self._columns(), "열 이름")
        tabs.addTab(self._storage(), "저장 위치 · 업데이트")
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("저장")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    # ---------------- 폴더 ----------------
    def _folders(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(18, 18, 18, 18)
        f.setVerticalSpacing(12)
        f.addRow(label("세 파일이 들어오는 폴더를 지정하세요. 프로그램은 각 폴더에서 가장 최근에 수정된 파일을 비교에 씁니다.",
                       muted=True, wrap=True))
        self.folder_edits = {}
        for s in SOURCES:
            e = QLineEdit(self.cfg.folders.get(s, ""))
            e.setPlaceholderText(r"예: N:\Projects\040-042 Aloha-L\...\SAP BOM")
            self.folder_edits[s] = e
            f.addRow(SOURCE_LABELS[s], path_row(e, self))
        self.patterns = QLineEdit(self.cfg.patterns)
        f.addRow("파일 종류", self.patterns)
        self.scan = QSpinBox()
        self.scan.setRange(1, 120)
        self.scan.setSuffix(" 분마다")
        self.scan.setValue(self.cfg.scan_minutes)
        f.addRow("새 파일 확인", self.scan)
        self.stale = QSpinBox()
        self.stale.setRange(1, 90)
        self.stale.setSuffix(" 일 지나면 주황색 경고")
        self.stale.setValue(self.cfg.stale_days)
        f.addRow("오래된 파일", self.stale)
        self.demo = QCheckBox("폴더가 지정되지 않았을 때 예시 데이터로 보여주기")
        self.demo.setChecked(self.cfg.demo)
        f.addRow("", self.demo)
        return w

    # ---------------- 구역 규칙 ----------------
    def _areas(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 18, 18, 18)
        v.addWidget(label("모든 블록은 ER / Accommodation / On-deck 중 한 구역에 들어가야 합니다. 각 구역 담당자는 세 호선 모두를 맡습니다.\n"
                          "위에서부터 처음 맞는 규칙이 적용됩니다. 패턴은 정규식입니다 (예: ^E 는 E로 시작하는 블록, ^(A|DH) 는 A 또는 DH로 시작).\n"
                          "BOM 파일에 구역 열이 있으면 그 값이 우선합니다.", muted=True, wrap=True))
        h = QHBoxLayout()
        self.rules = QTableWidget(0, 2)
        self.rules.setHorizontalHeaderLabels(["블록 패턴", "구역"])
        self.rules.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rules.verticalHeader().hide()
        for pat, area in self.cfg.area_rules:
            self._add_rule(pat, area)
        self.rules.itemChanged.connect(lambda _: self._preview())
        left = QVBoxLayout()
        left.addWidget(self.rules, 1)
        bh = QHBoxLayout()
        for txt, fn in (("규칙 추가", lambda: (self._add_rule("^", AREAS[0]), self._preview())),
                        ("선택 삭제", self._del_rule), ("위로", lambda: self._move(-1)), ("아래로", lambda: self._move(1))):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            bh.addWidget(b)
        left.addLayout(bh)
        h.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview_lb = label("", bold=True)
        right.addWidget(self.preview_lb)
        self.preview = QTableWidget(0, 2)
        self.preview.setHorizontalHeaderLabels(["블록", "구역"])
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview.verticalHeader().hide()
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.preview, 1)
        h.addLayout(right, 1)
        v.addLayout(h, 1)
        self._preview()
        return w

    def _add_rule(self, pat, area):
        r = self.rules.rowCount()
        self.rules.insertRow(r)
        self.rules.setItem(r, 0, QTableWidgetItem(pat))
        cb = QComboBox()
        for a in AREAS:
            cb.addItem(AREA_LABELS[a], a)
        cb.setCurrentIndex(max(0, cb.findData(area)))
        cb.currentIndexChanged.connect(lambda _: self._preview())
        self.rules.setCellWidget(r, 1, cb)

    def _del_rule(self):
        r = self.rules.currentRow()
        if r >= 0:
            self.rules.removeRow(r)
            self._preview()

    def _move(self, d):
        r = self.rules.currentRow()
        t = r + d
        if r < 0 or not (0 <= t < self.rules.rowCount()):
            return
        rules = self._rules()
        rules[r], rules[t] = rules[t], rules[r]
        self.rules.setRowCount(0)
        for p, a in rules:
            self._add_rule(p, a)
        self.rules.setCurrentCell(t, 0)
        self._preview()

    def _rules(self):
        out = []
        for r in range(self.rules.rowCount()):
            it = self.rules.item(r, 0)
            cb = self.rules.cellWidget(r, 1)
            if it and it.text().strip() and cb:
                out.append([it.text().strip(), cb.currentData()])
        return out

    def _preview(self):
        if not hasattr(self, "preview"):
            return
        blocks = sorted({r.block for r in self.last_run.comparison.rows}) if self.last_run and self.last_run.ok else []
        rules = self._rules()
        self.preview.setRowCount(len(blocks))
        un = 0
        for i, b in enumerate(blocks):
            a = classify_area(b, "", rules)
            un += a == UNASSIGNED
            self.preview.setItem(i, 0, QTableWidgetItem(b or "(블록 없음)"))
            it = QTableWidgetItem(AREA_LABELS.get(a, a))
            it.setForeground(QBrush(QColor(AREA_COLORS.get(a, C["ink"]))))
            if a == UNASSIGNED:
                it.setBackground(QBrush(QColor(C["bad_soft"])))
            self.preview.setItem(i, 1, it)
        if not blocks:
            self.preview_lb.setText("비교한 파일이 아직 없어 미리보기를 할 수 없습니다.")
        else:
            self.preview_lb.setText(f"현재 파일의 블록 {len(blocks)}개 · " +
                                    (f"미지정 {un}개" if un else "모든 블록이 구역에 들어갔습니다 ✓"))
            self.preview_lb.setStyleSheet(f"color:{C['bad'] if un else C['ok']};font-weight:600")

    # ---------------- 열 이름 ----------------
    def _columns(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(18, 18, 18, 18)
        v.addWidget(label("파일의 머리글이 아래 별칭 중 하나와 같으면 자동으로 그 열을 씁니다 (대소문자·공백 무시). "
                          "새 파일의 열을 못 찾으면 그 머리글을 별칭에 쉼표로 추가하세요. 오른쪽은 마지막으로 읽은 파일에서 실제로 찾은 머리글입니다.",
                          muted=True, wrap=True))
        fields = list(FIELD_LABELS)
        self.cols = QTableWidget(len(fields), 2 + len(SOURCES))
        self.cols.setHorizontalHeaderLabels(["항목", "별칭 (쉼표로 구분)"] + [SOURCE_LABELS[s] for s in SOURCES])
        self.cols.verticalHeader().hide()
        hh = self.cols.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        reads = self.last_run.reads if self.last_run else {}
        for i, fld in enumerate(fields):
            it = QTableWidgetItem(FIELD_LABELS[fld])
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setData(Qt.UserRole, fld)
            self.cols.setItem(i, 0, it)
            self.cols.setItem(i, 1, QTableWidgetItem(", ".join(self.cfg.aliases.get(fld, []))))
            for j, s in enumerate(SOURCES, start=2):
                found = reads[s].columns.get(fld, "") if s in reads else ""
                it = QTableWidgetItem(found or "–")
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                it.setForeground(QBrush(QColor(C["ok"] if found else C["muted"])))
                self.cols.setItem(i, j, it)
        v.addWidget(self.cols, 1)
        return w

    # ---------------- 저장 위치 ----------------
    def _storage(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(18, 18, 18, 18)
        f.setVerticalSpacing(12)
        self.hist = QLineEdit(self.cfg.history_db)
        self.hist.setPlaceholderText(f"비우면 내 PC에 저장 ({self.cfg.history_path})")
        f.addRow("이력 파일", path_row(self.hist, self, file_mode=True))
        f.addRow("", label("여러 사람이 같은 이력을 보려면 N: 공용 폴더 안의 파일로 지정하세요.", muted=True, size=9))
        self.rep = QLineEdit(self.cfg.report_dir)
        self.rep.setPlaceholderText(str(self.cfg.report_path))
        f.addRow("리포트 저장 폴더", path_row(self.rep, self))
        self.upd = QLineEdit(self.cfg.update_dir)
        self.upd.setPlaceholderText(r"예: N:\Projects\...\AlohaBOM\release")
        f.addRow("업데이트 폴더", path_row(self.upd, self))
        f.addRow("", label("이 폴더에 새 AlohaBOM.exe 와 version.json 을 올리면, 각자 exe를 켤 때 자동으로 새 버전으로 바뀝니다.",
                           muted=True, size=9, wrap=True))
        b = QPushButton("매일 아침 7시 자동 기록 등록 (Windows 작업 스케줄러)")
        b.clicked.connect(self._register_task)
        f.addRow("일별 기록", b)
        f.addRow("", label("프로그램을 켜지 않은 날도 이 PC가 켜져 있으면 매일 아침 창 없이 비교해서 이력에 한 점씩 기록합니다. 한 사람(관리자) PC에서만 등록하면 됩니다.",
                           muted=True, size=9, wrap=True))
        return w

    def _register_task(self):
        import os
        import subprocess
        import sys
        from PySide6.QtWidgets import QMessageBox
        if os.name != "nt" or not getattr(sys, "frozen", False):
            QMessageBox.information(self, "일별 기록", "Windows에서 AlohaBOM.exe로 실행했을 때만 등록할 수 있습니다.")
            return
        cmd = ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", "07:00", "/TN", "AlohaBOM 일별 기록",
               "/TR", f'"{sys.executable}" --scan']
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            QMessageBox.information(self, "일별 기록", "등록했습니다. 매일 아침 7시에 자동으로 비교해서 이력에 기록합니다.")
        else:
            QMessageBox.warning(self, "일별 기록", "등록하지 못했습니다.\n\n" + (r.stderr or r.stdout))

    # ---------------- 저장 ----------------
    def _save(self):
        c = self.cfg
        c.folders = {s: self.folder_edits[s].text().strip() for s in SOURCES}
        c.patterns = self.patterns.text().strip() or "*.xlsx;*.xlsm;*.csv"
        c.scan_minutes = self.scan.value()
        c.stale_days = self.stale.value()
        c.demo = self.demo.isChecked()
        c.area_rules = self._rules()
        c.area_rules_confirmed = True
        for i in range(self.cols.rowCount()):
            fld = self.cols.item(i, 0).data(Qt.UserRole)
            c.aliases[fld] = [a.strip() for a in self.cols.item(i, 1).text().split(",") if a.strip()]
        c.history_db = self.hist.text().strip()
        c.report_dir = self.rep.text().strip()
        c.update_dir = self.upd.text().strip()
        self.accept()
