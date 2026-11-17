"""BOM Master entry point: self-update check, then the GUI."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from bom_master import APP_NAME
from bom_master.config import Config
from bom_master.gui import theme
from bom_master.gui.main_window import MainWindow
from bom_master.updater import apply_update, available_update


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.QSS)
    cfg = Config.load()

    upd = available_update(cfg)
    if upd:
        ver, exe, notes = upd
        box = QMessageBox(QMessageBox.Information, APP_NAME,
                          f"Updating to version {ver}…\n\n{notes}".strip(), QMessageBox.NoButton)
        box.show()
        app.processEvents()
        try:
            apply_update(exe)
            return 0
        except OSError as e:
            box.close()
            QMessageBox.warning(None, APP_NAME, f"Update could not be applied ({e}). Continuing with this version.")

    win = MainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
