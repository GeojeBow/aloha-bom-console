"""Colors and the application style sheet."""
from PySide6.QtGui import QColor

INK = "#1B2430"
MUTED = "#66727F"
LINE = "#DDE2E8"
BG = "#F3F5F8"
SURFACE = "#FFFFFF"
NAV = "#14202E"
NAV_INK = "#AEB9C6"
ACCENT = "#2F6FED"

OK = "#23935F"
OK_SOFT = "#DDF3E8"
WARN = "#C98A00"
WARN_SOFT = "#FCF0D2"
ERR = "#D2433F"
ERR_SOFT = "#FBE2E1"
INFO = "#3C7BD9"
INFO_SOFT = "#E1ECFB"
NONE = "#9AA5B1"
NONE_SOFT = "#EDF0F3"

ACK = "#5B6B8C"
ACK_SOFT = "#E4E8F0"
KIND_COLORS = {"OK": (OK, OK_SOFT), "WARN": (WARN, WARN_SOFT), "ERROR": (ERR, ERR_SOFT), "INFO": (INFO, INFO_SOFT),
               "NONE": (NONE, NONE_SOFT), "ACK": (ACK, ACK_SOFT)}

SEV_COLORS = {"ERROR": (ERR, ERR_SOFT), "WARN": (WARN, WARN_SOFT), "INFO": (INFO, INFO_SOFT), None: (OK, OK_SOFT)}

# label -> (ink, soft)
STATUS_COLORS = {
    "In sync": (OK, OK_SOFT), "Matches": (OK, OK_SOFT),
    "WP outdated": (ERR, ERR_SOFT), "Content differs": (ERR, ERR_SOFT), "WP ahead": (ERR, ERR_SOFT),
    "WP only": (ERR, ERR_SOFT), "Differs": (ERR, ERR_SOFT), "Rev missing": (ERR, ERR_SOFT),
    "Not in WP": (WARN, WARN_SOFT),
    "ERROR": (ERR, ERR_SOFT), "WARN": (WARN, WARN_SOFT), "INFO": (INFO, INFO_SOFT),
    "ACTIVE": (OK, OK_SOFT), "ARCHIVE": (NONE, NONE_SOFT), "COMMENT": (INFO, INFO_SOFT), "STAGING": (WARN, WARN_SOFT),
    "PROD": (ACCENT, INFO_SOFT), "WP": ("#7A4FD0", "#EEE6FB"), "DCN": ("#B5560F", "#FBEADB"), "ECN": ("#0F8A8A", "#DBF3F3"),
}

# distinct fills for "content group" A/B/C in the revision timeline
GROUP_FILLS = ["#DDF3E8", "#FBE2E1", "#E1ECFB", "#FCF0D2", "#EEE6FB", "#DBF3F3"]


def qc(hex_):
    return QColor(hex_)


QSS = f"""
* {{ font-family: "Segoe UI", "Malgun Gothic"; font-size: 10pt; color: {INK}; }}
QMainWindow, QWidget#page {{ background: {BG}; }}
QWidget#nav {{ background: {NAV}; }}
QLabel#brand {{ color: white; font-size: 13pt; font-weight: 700; padding: 18px 18px 2px 18px; }}
QLabel#brandSub {{ color: {NAV_INK}; font-size: 8.5pt; padding: 0 18px 16px 18px; }}
QPushButton#navBtn {{
  color: {NAV_INK}; background: transparent; border: none; text-align: left;
  padding: 10px 18px; font-size: 10pt; border-left: 3px solid transparent;
}}
QPushButton#navBtn:hover {{ color: white; background: #1C2B3C; }}
QPushButton#navBtn:checked {{ color: white; background: #22344A; border-left: 3px solid {ACCENT}; font-weight: 600; }}
QLabel#navFoot {{ color: #6F7D8C; font-size: 8pt; padding: 12px 18px; }}

QWidget#topbar {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}
QLabel#pageTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#muted, QLabel.muted {{ color: {MUTED}; }}
QLabel#h2 {{ font-size: 11.5pt; font-weight: 700; }}

QPushButton {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ border-color: #B8C1CC; background: #FAFBFC; }}
QPushButton:disabled {{ color: #A9B2BC; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #255FD6; }}
QPushButton#primary:disabled {{ background: #9DB8F2; border-color: #9DB8F2; color: white; }}

QPushButton#seg {{ border-radius: 0; padding: 6px 14px; margin: 0; }}
QPushButton#seg:checked {{ background: {INK}; color: white; border-color: {INK}; font-weight: 600; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 6px; padding: 5px 8px;
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; }}
QLabel#kpiValue {{ font-size: 20pt; font-weight: 700; }}
QLabel#kpiLabel {{ color: {MUTED}; font-size: 9pt; }}

QTableView {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; gridline-color: #EEF1F4;
  selection-background-color: #DCE7FD; selection-color: {INK}; alternate-background-color: #FAFBFC;
}}
QHeaderView::section {{
  background: #F0F3F6; color: {MUTED}; border: none; border-bottom: 1px solid {LINE}; border-right: 1px solid #E6EAEE;
  padding: 6px 22px 6px 8px; font-size: 8.5pt; font-weight: 600;
}}
QScrollArea {{ border: none; background: transparent; }}
QProgressBar {{ border: none; background: #E6EAEE; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QToolTip {{ background: {INK}; color: white; border: none; padding: 6px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ padding: 7px 16px; background: transparent; border-bottom: 2px solid transparent; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {INK}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
"""
