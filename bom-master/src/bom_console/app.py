"""프로그램 시작점."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME, APP_TITLE, __version__


def asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "bom_console" / "assets" / name
    return p if p.exists() else Path(__file__).resolve().parent / "assets" / name


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if any(a in ("--scan", "--report") for a in argv):
        from .cli import main as cli_main
        return cli_main(argv)

    if os.name == "nt":
        # 작업표시줄에 python 아이콘 대신 이 프로그램 아이콘이 보이도록
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"Aloha.{APP_NAME}.{__version__}")
        except Exception:
            pass

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import updater
    from .config import load_config
    from .ui.main_window import MainWindow
    from .ui.theme import QSS, font

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_TITLE)
    icon = QIcon(str(asset("bom_app.ico")))
    app.setWindowIcon(icon)
    app.setFont(font(10))
    app.setStyleSheet(QSS)

    cfg = load_config()
    info = updater.check(cfg.update_path)
    if info and updater.can_self_update():
        QMessageBox.information(None, "업데이트", f"새 버전 {info.version}이(가) 있습니다. 업데이트 후 자동으로 다시 켜집니다."
                                + (f"\n\n{info.notes}" if info.notes else ""))
        if updater.apply(info):
            return 0

    w = MainWindow(cfg, icon)
    w.show()
    return app.exec()
