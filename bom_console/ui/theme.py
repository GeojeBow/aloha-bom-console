"""색상과 스타일시트."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont

C = {
    "bg": "#F2F4F7", "panel": "#FFFFFF", "soft": "#EAEEF2", "line": "#DCE2E8", "ink": "#14202B", "muted": "#5D6B78",
    "accent": "#0D6E8A", "accent_soft": "#DCEDF2", "navy": "#0D3B4F",
    "ok": "#1F8A4C", "ok_soft": "#DDF1E5", "warn": "#B26A00", "warn_soft": "#FBECD3",
    "bad": "#C0392B", "bad_soft": "#F8DEDB",
    "design": "#3C5A99", "sap": "#1F6FD1", "purchase": "#C2477A",
    "cat_missing": "#C0392B", "cat_qty": "#D98A1C", "cat_code": "#A0702B", "cat_extra": "#7A4FA3",
}
CAT_COLORS = {"ok": C["ok"], "missing": C["cat_missing"], "qty": C["cat_qty"], "code": C["cat_code"], "extra": C["cat_extra"]}
AREA_COLORS = {"ER": "#2F6F9F", "Accommodation": "#3E8E6E", "On-deck": "#8A6A2F", "미지정": "#9AA5B1"}


def q(name: str) -> QColor:
    return QColor(C.get(name, name))


def font(size: float = 10, bold: bool = False, family: str | None = None) -> QFont:
    f = QFont(family or "Malgun Gothic")
    f.setStyleHint(QFont.SansSerif)
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


QSS = f"""
* {{ font-family: "Malgun Gothic", "Noto Sans CJK KR", "Segoe UI"; font-size: 10pt; color: {C['ink']}; }}
QMainWindow, #Root {{ background: {C['bg']}; }}
#TopBar {{ background: {C['panel']}; border-bottom: 1px solid {C['line']}; }}
#Crumbs {{ background: {C['soft']}; border-bottom: 1px solid {C['line']}; }}
#Card, QFrame[card="true"] {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 10px; }}
QFrame[soft="true"] {{ background: {C['soft']}; border: 1px solid {C['line']}; border-radius: 8px; }}
QLabel[muted="true"] {{ color: {C['muted']}; }}
QLabel[eyebrow="true"] {{ color: {C['muted']}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
QLabel[h1="true"] {{ font-size: 15pt; font-weight: 700; }}
QLabel[big="true"] {{ font-size: 20pt; font-weight: 700; }}
QPushButton {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {C['accent']}; color: {C['accent']}; }}
QPushButton[primary="true"] {{ background: {C['accent']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {C['navy']}; color: white; }}
QPushButton[chip="true"] {{ border-radius: 13px; padding: 4px 12px; }}
QPushButton[chip="true"]:checked {{ background: {C['accent']}; border-color: {C['accent']}; color: white; }}
QPushButton[link="true"] {{ border: none; background: transparent; color: {C['accent']}; padding: 2px 4px; text-decoration: underline; }}
QLineEdit, QComboBox, QSpinBox {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 5px 8px; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QTableView, QTableWidget, QListWidget {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 8px;
    gridline-color: {C['soft']}; selection-background-color: {C['accent_soft']}; selection-color: {C['ink']}; }}
QHeaderView::section {{ background: {C['soft']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['line']};
    padding: 6px 8px; font-weight: 600; font-size: 9pt; }}
QTabWidget::pane {{ border: 1px solid {C['line']}; border-radius: 8px; background: {C['panel']}; top: -1px; }}
QTabBar::tab {{ padding: 7px 16px; border: 1px solid {C['line']}; border-bottom: none; border-top-left-radius: 6px;
    border-top-right-radius: 6px; background: {C['soft']}; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {C['panel']}; color: {C['accent']}; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #C5CED6; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
#Banner {{ background: {C['warn_soft']}; border: 1px solid #EBCB96; border-radius: 8px; }}
#InfoBanner {{ background: {C['soft']}; border: 1px solid {C['line']}; border-radius: 8px; }}
#Toast {{ background: {C['ink']}; border-radius: 10px; }}
#Toast QLabel {{ color: white; }}
QToolTip {{ background: {C['panel']}; color: {C['ink']}; border: 1px solid {C['line']}; padding: 6px; }}
"""
